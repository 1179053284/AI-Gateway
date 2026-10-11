#!/usr/bin/env python3
"""Run deterministic upload and result-query mechanics for a remote-split Skill.

@author: 希至
"""

import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode
from xml.sax.saxutils import quoteattr


STATUS_MARKER = "__CONEXA_HTTP_STATUS__:"
QUERY_RETRY_DELAY_SECONDS = 10
QUERY_TIMEOUT_SECONDS = 180
RUNTIME_CONFIG_NAME = "runtime-config.json"
RUNTIME_CONFIG_SCHEMA = "skillhide.near-runtime-config.v1"
QUERY_MODE = "polling"
TRANSIENT_HTTP_STATUSES = {302, 408, 425, 429, 500, 502, 503, 504}
TRANSIENT_CURL_CODES = {5, 6, 7, 18, 28, 35, 52, 55, 56, 92}


class RuntimeClientError(RuntimeError):
    """A safe, user-actionable near-side transport or validation failure."""


class QueryPending(RuntimeClientError):
    """The result endpoint has not returned a valid completed result yet."""


class QueryFailed(RuntimeClientError):
    """The server reported a terminal failure for this requestId."""


class ProxyRequestError(RuntimeClientError):
    """The proxied curl process failed before an HTTP response was available."""

    def __init__(self, message, *, transient=False):
        super().__init__(message)
        self.transient = transient


def run_proxy(
    curl_args,
    timeout=130,
):
    command = ["alipay-bot", "curl-proxy", "--", *curl_args]
    try:
        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProxyRequestError(
            "alipay-bot proxy execution timed out", transient=True
        ) from exc
    except OSError as exc:
        raise ProxyRequestError("alipay-bot proxy execution failed") from exc
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        suffix = ": " + detail[-1] if detail else ""
        raise ProxyRequestError(
            "alipay-bot proxy request failed" + suffix,
            transient=result.returncode in TRANSIENT_CURL_CODES,
        )
    return result.stdout


def split_http_output(output):
    marker = "\n" + STATUS_MARKER
    if marker not in output:
        raise RuntimeClientError("proxy response is missing HTTP status")
    body, status_text = output.rsplit(marker, 1)
    try:
        status = int(status_text.strip())
    except ValueError as exc:
        raise RuntimeClientError("proxy response contains invalid HTTP status") from exc
    return body, status


def proxy_request(
    url,
    curl_args,
    timeout=130,
):
    request_args = ["-sS", *curl_args]
    try:
        method_index = request_args.index("-X")
    except ValueError:
        url_index = len(request_args)
    else:
        url_index = min(method_index + 2, len(request_args))
    request_args.insert(url_index, url)
    request_args.extend(
        ["--write-out", "\\n" + STATUS_MARKER + "%{http_code}"]
    )
    output = run_proxy(
        request_args,
        timeout=timeout,
    )
    return split_http_output(output)


def parse_json_object(value, label):
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeClientError(label + " is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeClientError(label + " must be a JSON object")
    return parsed


def load_runtime_config(skill_root):
    path = skill_root / RUNTIME_CONFIG_NAME
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeClientError("runtime config is unreadable") from exc
    if not isinstance(config, dict):
        raise RuntimeClientError("runtime config must be a JSON object")
    if config.get("schemaVersion") != RUNTIME_CONFIG_SCHEMA:
        raise RuntimeClientError("runtime config schema is unsupported")
    if config.get("queryMode") != QUERY_MODE:
        raise RuntimeClientError("runtime config queryMode does not match client")
    sku_id = config.get("skuId")
    if not isinstance(sku_id, str) or not sku_id.strip():
        raise RuntimeClientError("runtime config contains an invalid skuId")
    for key in ("remoteUrl", "queryUrl", "fileUploadUrl"):
        value = config.get(key)
        if not isinstance(value, str) or not value.startswith("https://"):
            raise RuntimeClientError(
                "runtime config contains an invalid HTTPS endpoint: " + key
            )
    return config


def diagnostic_scalar(value, limit=300):
    """Return one bounded, single-line scalar suitable for stderr diagnostics."""
    if not isinstance(value, (str, int, float, bool)):
        return None
    rendered = " ".join(str(value).split())
    if not rendered:
        return None
    if len(rendered) > limit:
        return rendered[: limit - 3] + "..."
    return rendered


def resource_uri(response):
    if response.get("success") is not True:
        details = []
        for key in ("code", "message", "traceId"):
            value = diagnostic_scalar(response.get(key))
            if value is not None:
                details.append("%s=%s" % (key, value))
        suffix = ": " + ", ".join(details) if details else ""
        raise RuntimeClientError("file upload was rejected by service" + suffix)

    data = response.get("data")
    if isinstance(data, str) and data.strip():
        return data.strip()
    if isinstance(data, dict):
        for key in ("url", "uri", "downloadUrl"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    response_keys = ",".join(sorted(str(key) for key in response))
    raise RuntimeClientError(
        "file upload succeeded but response is missing resource URL "
        "(data_type=%s, response_keys=%s)"
        % (type(data).__name__, response_keys or "none")
    )


def upload_file(file_path, upload_url):
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise RuntimeClientError("input file is missing: " + str(path))
    display_name = diagnostic_scalar(path.name, limit=160) or "<unnamed>"
    last_error = None
    attempts = 2
    for attempt in range(attempts):
        try:
            body, status = proxy_request(
                upload_url,
                [
                    "-X",
                    "POST",
                    "-H",
                    "Content-Type: multipart/form-data",
                    "-F",
                    "file=@" + str(path),
                ],
            )
            if not 200 <= status < 300:
                raise RuntimeClientError("file upload returned HTTP %s" % status)
            response = parse_json_object(body, "file upload response")
            uri = resource_uri(response)
            mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            return (
                "<_aipay_resource_link uri=%s name=%s mimeType=%s size=%s/>"
                % (
                    quoteattr(uri),
                    quoteattr(path.name),
                    quoteattr(mime_type),
                    quoteattr(str(path.stat().st_size)),
                )
            )
        except RuntimeClientError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                print(
                    "REMOTE_SPLIT_RETRY: file upload attempt %s/%s failed for "
                    "%s: %s; retrying once"
                    % (attempt + 1, attempts, display_name, exc),
                    file=sys.stderr,
                )
    raise RuntimeClientError(
        "file upload failed for %s after %s attempts: %s"
        % (display_name, attempts, last_error)
    ) from last_error


def _query_diagnostic(response):
    details = []
    for key in (
        "requestId",
        "status",
        "error",
        "errorCode",
        "code",
        "message",
        "errorMsg",
    ):
        value = diagnostic_scalar(response.get(key))
        if value is not None:
            details.append("%s=%s" % (key, value))
    return ", ".join(details) or "no status fields"


def parse_query_result(body, request_id):
    """Return the complete resultContent or mark this response retryable.

    The result body itself is never logged because it can contain protected
    compiled instructions. Only bounded scalar status fields are diagnostic.
    """
    try:
        response = json.loads(body)
    except json.JSONDecodeError as exc:
        raise QueryPending("query result is not valid JSON") from exc
    if not isinstance(response, dict):
        raise QueryPending("query result must be a JSON object")

    returned_request_id = response.get("requestId")
    if returned_request_id != request_id:
        raise QueryPending(
            "query result requestId mismatch: " + _query_diagnostic(response)
        )
    status = response.get("status")
    if status == "FAILED":
        raise QueryFailed(
            "query result failed; ask the user to start a new request: "
            + _query_diagnostic(response)
        )
    if status != "SUCCEEDED":
        raise QueryPending(
            "query result is not ready: " + _query_diagnostic(response)
        )

    result_content = response.get("resultContent")
    if not isinstance(result_content, str) or not result_content.strip():
        raise QueryPending(
            "query result is SUCCEEDED but resultContent is empty: "
            + _query_diagnostic(response)
        )
    return result_content


def query(
    request_id,
    query_url,
    *,
    attempts=None,
    retry_delay=QUERY_RETRY_DELAY_SECONDS,
    timeout=QUERY_TIMEOUT_SECONDS,
):
    separator = "&" if "?" in query_url else "?"
    url = query_url + separator + urlencode({"requestId": request_id})
    last_error = None
    attempt = 0
    while attempts is None or attempt < attempts:
        attempt += 1
        try:
            body, status = proxy_request(
                url,
                [
                    "--max-time",
                    str(timeout),
                ],
                timeout=timeout + 10,
            )
            if not 200 <= status < 300:
                if status in TRANSIENT_HTTP_STATUSES:
                    raise ProxyRequestError(
                        "query endpoint returned HTTP %s" % status,
                        transient=True,
                    )
                try:
                    response = json.loads(body)
                except json.JSONDecodeError:
                    response = {}
                detail = (
                    ": " + _query_diagnostic(response)
                    if isinstance(response, dict) and response
                    else ""
                )
                raise ProxyRequestError(
                    "query endpoint returned HTTP %s%s" % (status, detail),
                    transient=True,
                )
            return parse_query_result(body, request_id)
        except (QueryPending, ProxyRequestError) as exc:
            if isinstance(exc, ProxyRequestError) and not exc.transient:
                raise
            last_error = exc
            should_retry = attempts is None or attempt < attempts
            if should_retry:
                print(
                    "REMOTE_SPLIT_RETRY: query attempt %s not ready: %s; "
                    "retrying requestId=%s in %ss"
                    % (attempt, exc, request_id, retry_delay),
                    file=sys.stderr,
                )
                if retry_delay:
                    time.sleep(retry_delay)
    raise last_error


_RESOURCE_LINK_TAG = re.compile(
    r"<_aipay_resource_link\b[^>]*?/>",
    flags=re.IGNORECASE | re.DOTALL,
)
_RESOURCE_LINK_URI_ATTRIBUTE = re.compile(
    r"\buri\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    flags=re.IGNORECASE | re.DOTALL,
)


def _without_resource_link_http_uris(delivered):
    """Hide uploaded-resource URIs from HTTP command validation.

    A ``_aipay_resource_link`` is inert input metadata, not an instruction to
    access its URI. Only its URI attribute is hidden; commands and URLs around
    the tag remain visible to the safety checks below.
    """
    def hide_uri(tag_match):
        tag = tag_match.group(0)

        def replace_uri(attribute_match):
            value = attribute_match.group("value")
            if not value.casefold().startswith(("http://", "https://")):
                return attribute_match.group(0)
            quote = attribute_match.group("quote")
            return "uri=%sresource://uploaded-file%s" % (quote, quote)

        return _RESOURCE_LINK_URI_ATTRIBUTE.sub(replace_uri, tag, count=1)

    return _RESOURCE_LINK_TAG.sub(hide_uri, delivered)


def validate_http_usage(delivered):
    instructions = _without_resource_link_http_uris(delivered)
    without_proxy = instructions.replace("alipay-bot curl-proxy", "")
    if re.search(
        r"(?im)^\s*(?:[-*]\s+|\d+[.)]\s+)?(?:`|\$\s*)?"
        r"(?:curl|wget)(?=\s)|^\s*(?:[-*]\s+|\d+[.)]\s+)?"
        r"(?:run|execute|use|call|invoke)\s+`?"
        r"(?:curl|wget|requests\s*\.|httpx\s*\.|urllib)",
        without_proxy,
    ):
        raise RuntimeClientError("direct HTTP clients are forbidden")
    url_lines = []
    proxied_url_present = False
    for line in instructions.splitlines():
        lowered = line.casefold()
        if "http://" not in lowered and "https://" not in lowered:
            continue
        url_lines.append(line)
        if "alipay-bot curl-proxy --" in line:
            proxied_url_present = True
        elif re.search(r"\b(?:open|visit|browse|fetch|request|call)\b", lowered):
            raise RuntimeClientError(
                "every HTTP endpoint must use alipay-bot curl-proxy"
            )
    if url_lines and not proxied_url_present:
        raise RuntimeClientError(
            "every HTTP endpoint must use alipay-bot curl-proxy"
        )


def save_execution_output(output_dir, delivered):
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, output_path = tempfile.mkstemp(
        prefix="conexa-execution-",
        suffix=".md",
        dir=str(output_dir),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(delivered)
    except Exception:
        try:
            os.unlink(output_path)
        except FileNotFoundError:
            pass
        raise
    return Path(output_path)


def build_request_body(prompt_file, body_file, session_file=None):
    prompt_path = Path(prompt_file).expanduser().resolve()
    if not prompt_path.is_file():
        raise RuntimeClientError("prompt file is missing: " + str(prompt_path))
    try:
        prompt = prompt_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeClientError("prompt file is unreadable") from exc
    if not prompt.strip():
        raise RuntimeClientError("prompt file must not be empty")

    payload = {"prompt": prompt}
    if session_file is not None:
        session_path = Path(session_file).expanduser().resolve()
        if not session_path.is_file():
            raise RuntimeClientError(
                "session file is missing: " + str(session_path)
            )
        try:
            session_id = session_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeClientError("session file is unreadable") from exc
        if not session_id.strip():
            raise RuntimeClientError("sessionId must be a non-empty string")
        payload["sessionId"] = session_id

    output_path = Path(body_file).expanduser().resolve()
    if not output_path.parent.is_dir():
        raise RuntimeClientError(
            "body output directory is missing: " + str(output_path.parent)
        )
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=output_path.name + ".",
        suffix=".tmp",
        dir=str(output_path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                payload,
                stream,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, output_path)
    except Exception:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise
    return output_path


def run_upload_step(files, args):
    resource_links = [
        upload_file(file_path, args.file_upload_url) for file_path in files
    ]
    return "UPLOAD_OK:\n" + "\n".join(resource_links)


def run_body_step(prompt_file, body_file, session_file):
    output_path = build_request_body(
        prompt_file,
        body_file,
        session_file=session_file,
    )
    return "BODY_OK: " + str(output_path)


def run_query_step(request_id, args):
    if not isinstance(request_id, str) or not request_id.strip():
        raise RuntimeClientError("requestId must be a non-empty string")
    delivered = query(request_id.strip(), args.query_url)
    validate_http_usage(delivered)
    output_path = save_execution_output(args.state_dir.resolve(), delivered)
    return "QUERY_OK: " + str(output_path)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skill-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "conexa-runtime",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    upload_parser = commands.add_parser("upload")
    upload_parser.add_argument("files", nargs="+")
    body_parser = commands.add_parser("body")
    body_parser.add_argument("prompt_file")
    body_parser.add_argument("body_file")
    body_parser.add_argument("--session-file")
    query_parser = commands.add_parser("query")
    query_parser.add_argument("request_id")
    args = parser.parse_args(argv)
    args.skill_root = args.skill_root.resolve()
    config = load_runtime_config(args.skill_root)
    args.sku_id = config["skuId"]
    args.remote_url = config["remoteUrl"]
    args.query_url = config["queryUrl"]
    args.file_upload_url = config["fileUploadUrl"]
    return args


def main(argv=None):
    try:
        args = parse_args(argv)
        if args.command == "upload":
            output = run_upload_step(args.files, args)
        elif args.command == "body":
            output = run_body_step(
                args.prompt_file,
                args.body_file,
                args.session_file,
            )
        else:
            output = run_query_step(args.request_id, args)
    except QueryFailed as exc:
        print("REMOTE_SPLIT_FAILED: " + str(exc), file=sys.stderr)
        return 1
    except (OSError, RuntimeClientError, json.JSONDecodeError) as exc:
        print("REMOTE_SPLIT_ERROR: " + str(exc), file=sys.stderr)
        return 1
    sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
