"""配置加载：YAML → pydantic 校验 → 内存快照；原子写（tech-design §4.7）。

- 加载：data/config.yaml（默认路径，可由参数/环境变量覆盖）；不存在 → 内置默认值 + 警告。
- 校验失败 → 抛 ConfigError（errors 逐条指明位置），启动时拒绝、热重载时保留旧快照。
- 写入：tempfile + os.replace 原子替换（同目录，保证同文件系统）。
- 热重载（mtime 轮询 + 管理界面保存）：M1 任务 9 完整实现，本模块提供基础。
- 环境变量引用 ${VAR}（P1）与 vendor_model 枚举池校验：M1 任务 3 接入 enums/matcher 后启用。
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

import yaml
from pydantic import ValidationError

from model_gateway.config.schemas import AppConfig

from model_gateway.core.paths import resolve_config_path  # noqa: E402


class ConfigError(Exception):
    """配置校验失败：errors 逐条指明位置（tech-design §4.7）。"""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("配置校验失败（" + "；".join(errors) + "）")


def load_config(path: Path | str | None = None) -> AppConfig:
    """加载并校验配置；文件不存在时返回内置默认配置（附警告）。"""
    path = resolve_config_path(path)
    if not path.exists():
        cfg = AppConfig()
        cfg.warnings.append(f"配置文件不存在：{path}（使用内置默认配置）")
        return cfg

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError([f"{path}: 配置根节点必须是映射（mapping），实际为 {type(raw).__name__}"])

    # 🔴 R7-K4（2026-10-06）：版本位守卫——**比本程序新的 schema 版本**明确拒绝，
    #    不允许"半懂"地读下去（旧程序读新配置 = 未知键已由 forbid 报错，这里补版本维度）。
    #    旧文件缺键 ⇒ AppConfig.schema_version 默认 1，零迁移。
    declared = raw.get("schema_version", 1)
    if not isinstance(declared, int) or isinstance(declared, bool) or declared < 1:
        raise ConfigError([f"{path}: schema_version 必须是 ≥1 的整数，实际为 {declared!r}"])
    if declared > AppConfig.model_fields["schema_version"].default:
        raise ConfigError([
            f"{path}: 配置 schema 版本 {declared} 高于本程序支持的版本 "
            f"{AppConfig.model_fields['schema_version'].default}——请升级 model-gateway "
            f"后再使用这份配置（拒绝半懂地读取，防止静默走缺省）"])

    try:
        return AppConfig.model_validate(raw)
    except ValidationError as e:
        errors: list[str] = []
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "(root)"
            errors.append(f"{path} → {loc}: {err['msg']}")
        raise ConfigError(errors) from e


def save_config(config: AppConfig, path: Path | str | None = None) -> None:
    """原子写：tempfile + os.replace（tech-design §4.7 / §8-3；中断不留半截文件）。"""
    path = resolve_config_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(mode="json", exclude={"warnings"}, exclude_none=False)
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)

    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
