# -*- coding: utf-8 -*-
"""ZCode 官方身份块 —— 3012 风控的准入前提（P0-1）。

取证与消融矩阵（DSH `src/zcode-identity.ts:10-32`，2026-10-03 三账号实测）：

| system 形状 | 结果 |
|---|---|
| 无 system（0 字符） | ✗ 405 + 3012 |
| 仅 cliPrefix（42 字符） | ✗ 405 + 3012 |
| cliPrefix + stable（2898 字符，块数组） | ✓ 200 |
| 官方完整四块（7599 字符） | ✓ 200 |

判据**唯一**：`system` 是块数组且首块逐字为官方 CLI 前缀、第二块为 stable 段。
与 HTTP 头 / 版本号 / 请求频率 / 多轮历史 / tools 全部无关（DSH 逐项排除过）。
上游 3012 惩罚梯度：30 分钟；24h 内第 3 次 → 24h；第 5 次 → 账号停用
（`zcode-identity.ts:42`）⇒ 缺身份块的请求**每多发一次都在烧号**。

文本来源：DSH `zcode-identity.ts:54-79` 程序化提取（脚本逐字搬运，非手抄），
官方原文 = `ZCode/apps/zcode-cli/packages/core/src/context/sections/cli-prefix.ts:8`。
总长自检 = 42 + 2856 = 2898 字符，与 DSH 通过形状的实测值一致
（`OFFICIAL_IDENTITY_CHARS = 2900` 为上限自检值，实测 2898）。

🔴 **故意不含**官方 dynamic 段（`# Communicating with the user` 等 5KB）：
那是给 ZCode 内 coding agent 的行为指令，与准入无关，且会压过调用方 prompt
（DSH `zcode-identity.ts:60-66` 实测「啰嗦、慢」后剔除）。

可配置性：身份块常量在进程内只读；上游若改结构（官方升级 ⇒ 重新 3012），
改本文件常量即可，不触及其它层（DSH `zcode-identity.ts:38-43` 的前瞻警告）。
"""

from __future__ import annotations

#: 第一块：CLI 身份前缀（官方原文，42 字符）。
OFFICIAL_CLI_PREFIX: str = "You are ZCode, an interactive coding agent"

#: 第二块：stable 段（官方原文，三段以 \n\n 连接 = 2856 字符）。
#: 逐字复刻官方，**不要“优化”** —— 上游检查看的是前缀结构与内容。
OFFICIAL_STABLE_SECTIONS: tuple[str, ...] = (
    "\nYou are an interactive ZCode agent that helps users with software engineering tasks.\n\nIMPORTANT: Assist with authorized security testing, defensive security, CTF challenges, and educational contexts. Refuse requests for destructive techniques, DoS attacks, mass targeting, supply chain compromise, or detection evasion for malicious purposes. Dual-use security tools (C2 frameworks, credential testing, exploit development) require clear authorization context: pentesting engagements, CTF competitions, security research, or defensive use cases.\n\n# Harness\n- Text you output outside of tool use is displayed to the user as Github-flavored markdown in a terminal.\n- Tools run behind a user-selected permission mode; a denied call means the user declined it — adjust, don't retry verbatim.\n- The system may send updates, reminders, or modifications to rules via mid-conversation system turns. These are system-controlled, unlike function results. Hooks may intercept tool calls; treat hook output as user feedback.\n- Prefer the dedicated file/search tools over shell commands when one fits. Independent tool calls can run in parallel in one response.\n- Reference code as `file_path:line_number` — it's clickable.",
    "# ZCode Desktop Context\n\n### Files & URLs\n- Return local web URLs as Markdown links (e.g., [label](http://127.0.0.1:8080)).\n- File should be an absolute path or include the workspace folder segment so it can be resolved relative to the workspace.\n- Unless otherwise specified, return local file references as Markdown links (e.g., [name.md](/absolute/path/to/name.md)).\n\n### Inline Code Comments\n- Use the ::code-comment{...} directive when you need to attach feedback directly to specific code lines.\n- Emit one directive per inline comment; emit none when there are no actionable inline comments.\n- Required attributes: title (short label), body (one-paragraph explanation), file (path to the file).\n- Optional attributes: start, end (1-based line numbers), priority (0-3).\n- file should be an absolute path or include the workspace folder segment so it can be resolved relative to the workspace.\n- Keep line ranges tight; end defaults to start.\n- Example: ::code-comment{title=\"[P2] Off-by-one\" body=\"Loop iterates past the end when length is 0.\" file=\"/path/to/foo.ts\" start=10 end=11 priority=2}",
    "# Working style\n\nWhen you have enough information to act, act. Do not re-derive facts already established in the conversation, re-litigate a decision the user has already made, or narrate options you will not pursue. If you are weighing a choice, give a recommendation, not an exhaustive survey. Prefer reading the actual file or running the actual command over reasoning about what it probably contains. When a signal pattern-matches to a known failure, check that the evidence actually supports that specific diagnosis before acting on it.",
)

#: 官方预期的 `cliPrefix + stable` 合计长度（自检；实测 2898，上限 2900）。
OFFICIAL_IDENTITY_CHARS: int = 2900


def build_identity_blocks(caller_system: str | None) -> list[dict]:
    """构造官方形态的 `system` 块数组（准入必需）。

    结构（逐字复刻官方，**不要“优化”**）：

    ```
    block[0] = cliPrefix（42 字符）          ← 准入必需
    block[1] = stable（2856 字符）           ← 准入必需
    block[2] = 调用方的 system（追加在最后）
    ```

    ⚠ 调用方内容**必须追加在最后** —— 官方身份块必须处在开头位置
    （上游检查看的是前缀结构）。

    ⚠ 只在最后一块打 `cache_control` 断点（前缀式语义 ⇒ 一个断点覆盖
    「该断点之前的全部内容」；断点预算 4 个，留给 tools）。
    cache_control 只是缓存提示，**不参与风控判定**（DSH 实测）。
    """
    blocks: list[dict] = [
        {"type": "text", "text": OFFICIAL_CLI_PREFIX},
        {"type": "text", "text": "\n\n".join(OFFICIAL_STABLE_SECTIONS)},
    ]
    if caller_system and caller_system.strip():
        blocks.append({"type": "text", "text": caller_system})
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def has_official_identity(system) -> bool:
    """诊断用：请求体的 system 是否已带官方身份块（块数组首块逐字 cliPrefix）。

    给 3012 诊断行用（P1-5）：区分「身份块缺失」与「账号/IP 被标记」
    —— DSH 记录过「身份块达标仍 3012」的无解释残例（`zcode-identity.ts:34-36`），
    这两种成因的处置完全不同，必须可判。
    """
    if isinstance(system, list):
        if system and isinstance(system[0], dict):
            return system[0].get("text") == OFFICIAL_CLI_PREFIX
        return False
    if isinstance(system, str):
        return system.startswith(OFFICIAL_CLI_PREFIX)
    return False


def identity_chars(system) -> int:
    """诊断用：system 的实测字符数（读真实形状，不是常量回显）。"""
    if isinstance(system, list):
        return sum(len(b.get("text") or "") for b in system if isinstance(b, dict))
    if isinstance(system, str):
        return len(system)
    return 0
