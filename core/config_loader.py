#!/usr/bin/env python3
"""配置读取与选择模块。

- 支持 claude / codex 两类配置
- 提供加载、列表、按索引或名称模糊匹配选择
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# PyInstaller 打包后 __file__ 指向临时解压目录，需要用 sys.executable 获取真实路径
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后的可执行文件
    SCRIPT_DIR = Path(sys.executable).resolve().parent
else:
    # 普通 Python 运行
    SCRIPT_DIR = Path(__file__).resolve().parent.parent

CONFIG_MAP = {
    "claude": {
        "file": SCRIPT_DIR / "claude_configs.json",
        "env_token": "ANTHROPIC_AUTH_TOKEN",
        "env_url": "ANTHROPIC_BASE_URL",
        "json_token": "token",
        "json_url": "url",
    },
    "codex": {
        "file": SCRIPT_DIR / "codex_configs.json",
        "env_token": "OPENAI_API_KEY",
        "env_url": "OPENAI_BASE_URL",
        "json_token": "api_key",
        "json_url": "base_url",
    },
}


class ConfigLoadError(RuntimeError):
    """用于统一抛出配置加载相关错误。"""


def load_configs(ai_type: str) -> List[Dict[str, Any]]:
    if ai_type not in CONFIG_MAP:
        raise ConfigLoadError(f"无效的 AI 类型: {ai_type}")
    cfg_path = CONFIG_MAP[ai_type]["file"]
    if not cfg_path.exists():
        raise ConfigLoadError(f"配置文件不存在: {cfg_path}")
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # noqa: BLE001
        raise ConfigLoadError(f"读取配置失败: {exc}") from exc

    configs = data.get("configs") or []
    if not isinstance(configs, list):
        raise ConfigLoadError(f"配置文件格式不正确: {cfg_path}")
    return configs


def list_configs(ai_type: str, configs: List[Dict[str, Any]]) -> List[str]:
    """返回可展示的配置名称列表（不显示 channel_id）。"""
    names: List[str] = []
    for idx, cfg in enumerate(configs):
        name = cfg.get("name", "<未命名>")
        group = cfg.get("group", "")
        suffix = f"  ({group})" if group else ""
        names.append(f"[{idx}] {name}{suffix}")
    return names


def pick_config(
    configs: List[Dict[str, Any]],
    index: Optional[int],
    name: Optional[str],
) -> Tuple[int, Dict[str, Any]]:
    """按 index 或名称模糊匹配返回 (索引, 配置)。"""
    if index is None and not name:
        raise ConfigLoadError("请选择配置: 需要 --index 或 --name")

    if index is not None:
        if index < 0 or index >= len(configs):
            raise ConfigLoadError(f"索引超出范围 (0~{len(configs) - 1})")
        return index, configs[index]

    name = name.lower()
    matches = [(i, c) for i, c in enumerate(configs) if name in str(c.get("name", "")).lower()]
    if not matches:
        raise ConfigLoadError(f"未找到名称包含 '{name}' 的配置")
    if len(matches) > 1:
        options = ", ".join(f"[{i}] {c.get('name')}" for i, c in matches)
        raise ConfigLoadError(f"找到多条匹配，请用索引指定: {options}")
    return matches[0]







