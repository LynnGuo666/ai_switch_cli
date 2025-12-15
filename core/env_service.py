#!/usr/bin/env python3
"""环境变量处理与持久化模块。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict, List


def determine_shell_config() -> Path:
    """返回首选的 shell 配置文件路径（zsh 优先）。"""
    shell = os.environ.get("SHELL", "")
    if "zsh" in shell or shutil.which("zsh"):
        return Path.home() / ".zshrc"
    return Path.home() / ".bash_profile"


def build_export_lines(env_vars: Dict[str, str]) -> str:
    """构造 export 命令文本，多行。"""
    return "\n".join(f'export {k}="{v}"' for k, v in env_vars.items())


def write_permanent(env_vars: Dict[str, str]) -> Path:
    """写入 shell 配置，先移除旧值再追加新值。"""
    shell_cfg = determine_shell_config()
    shell_cfg.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    if shell_cfg.exists():
        lines = [ln.rstrip("\n") for ln in shell_cfg.read_text(encoding="utf-8").splitlines()]

    keys = set(env_vars.keys())

    def should_keep(line: str) -> bool:
        stripped = line.strip()
        for k in keys:
            if stripped.startswith(f"export {k}=") or stripped.startswith(f"{k}="):
                return False
        return True

    filtered = [ln for ln in lines if should_keep(ln)]
    if filtered and filtered[-1].strip():
        filtered.append("")  # 保证空行分隔
    for k, v in env_vars.items():
        filtered.append(f'export {k}="{v}"')

    shell_cfg.write_text("\n".join(filtered) + "\n", encoding="utf-8")
    return shell_cfg


def remove_permanent(keys: List[str]) -> Path:
    """从 shell 配置中移除指定环境变量行。"""
    shell_cfg = determine_shell_config()
    shell_cfg.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    if shell_cfg.exists():
        lines = [ln.rstrip("\n") for ln in shell_cfg.read_text(encoding="utf-8").splitlines()]

    keyset = set(keys)

    def should_keep(line: str) -> bool:
        stripped = line.strip()
        for k in keyset:
            if stripped.startswith(f"export {k}=") or stripped.startswith(f"{k}="):
                return False
        return True

    filtered = [ln for ln in lines if should_keep(ln)]
    shell_cfg.write_text("\n".join(filtered) + ("\n" if filtered else ""), encoding="utf-8")
    return shell_cfg







