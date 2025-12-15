#!/usr/bin/env python3
"""基于 ai.sh 的简单环境变量切换工具（Python 版）。

支持 claude / codex:
- 临时模式: 输出 export 行，便于 `eval "$(python ai_env.py ...)"` 使用
- 永久模式: 写入默认 shell 配置文件（zsh 优先，其次 bash_profile）
- 列表模式: 查看配置索引和名称
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent

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


def load_configs(ai_type: str) -> List[Dict[str, Any]]:
    cfg_info = CONFIG_MAP[ai_type]
    cfg_path = cfg_info["file"]
    if not cfg_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    configs = data.get("configs") or []
    if not isinstance(configs, list):
        raise ValueError(f"配置文件格式不正确: {cfg_path}")
    return configs


def list_configs(ai_type: str, configs: List[Dict[str, Any]]) -> None:
    print(f"可用配置 ({ai_type}):")
    for idx, cfg in enumerate(configs):
        name = cfg.get("name", "<未命名>")
        channel_id = cfg.get("channel_id")
        print(f"[{idx}] {name}" + (f" | channel_id: {channel_id}" if channel_id else ""))


def pick_config(
    configs: List[Dict[str, Any]],
    index: Optional[int],
    name: Optional[str],
) -> Tuple[int, Dict[str, Any]]:
    if index is None and not name:
        raise ValueError("请选择配置: 需要 --index 或 --name")

    if index is not None:
        if index < 0 or index >= len(configs):
            raise IndexError(f"索引超出范围 (0~{len(configs) - 1})")
        return index, configs[index]

    # name 模糊匹配
    name = name.lower()
    matches = [(i, c) for i, c in enumerate(configs) if name in str(c.get("name", "")).lower()]
    if not matches:
        raise ValueError(f"未找到名称包含 '{name}' 的配置")
    if len(matches) > 1:
        options = ", ".join(f"[{i}] {c.get('name')}" for i, c in matches)
        raise ValueError(f"找到多条匹配，请用 --index 指定: {options}")
    return matches[0]


def determine_shell_config() -> Path:
    # zsh 优先，其次 bash_profile
    shell = os.environ.get("SHELL", "")
    if "zsh" in shell or shutil.which("zsh"):
        return Path.home() / ".zshrc"
    return Path.home() / ".bash_profile"


def write_permanent(env_vars: Dict[str, str]) -> Path:
    shell_cfg = determine_shell_config()
    shell_cfg.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    if shell_cfg.exists():
        with shell_cfg.open("r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines()]

    keys = set(env_vars.keys())

    def should_keep(line: str) -> bool:
        stripped = line.strip()
        for k in keys:
            if stripped.startswith(f"export {k}=") or stripped.startswith(f"{k}="):
                return False
        return True

    filtered = [ln for ln in lines if should_keep(ln)]
    if filtered and filtered[-1].strip():
        filtered.append("")  # 保证换行隔开
    for k, v in env_vars.items():
        filtered.append(f'export {k}="{v}"')
    shell_cfg.write_text("\n".join(filtered) + "\n", encoding="utf-8")
    return shell_cfg


def copy_codex_folder(codex_folder: str) -> None:
    src = SCRIPT_DIR / "codex" / codex_folder
    dst = SCRIPT_DIR / ".codex"
    if not src.exists():
        raise FileNotFoundError(f"未找到 codex 文件夹: {src}")
    dst.mkdir(parents=True, exist_ok=True)
    for fname in ("config.toml", "auth.json"):
        src_file = src / fname
        if src_file.exists():
            shutil.copy2(src_file, dst / fname)
        else:
            raise FileNotFoundError(f"缺少必要文件: {src_file}")


def build_export_lines(env_vars: Dict[str, str]) -> str:
    return "\n".join(f'export {k}="{v}"' for k, v in env_vars.items())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI 环境变量切换 (Python)")
    parser.add_argument("--type", choices=["claude", "codex"], required=True, help="选择 ai 类型")
    parser.add_argument("--index", type=int, help="配置索引")
    parser.add_argument("--name", help="配置名称模糊匹配")
    parser.add_argument(
        "--mode",
        choices=["temp", "permanent"],
        default="temp",
        help="temp: 输出 export 行; permanent: 写入 shell 配置文件",
    )
    parser.add_argument("--list", action="store_true", help="仅列出配置并退出")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg_info = CONFIG_MAP[args.type]

    try:
        configs = load_configs(args.type)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[Error] {exc}", file=sys.stderr)
        return 1

    if args.list:
        list_configs(args.type, configs)
        return 0

    try:
        idx, cfg = pick_config(configs, args.index, args.name)
    except (ValueError, IndexError) as exc:
        print(f"[Error] {exc}", file=sys.stderr)
        list_configs(args.type, configs)
        return 1

    token = str(cfg.get(cfg_info["json_token"], "") or "")
    base_url = str(cfg.get(cfg_info["json_url"], "") or "")
    env_vars = {cfg_info["env_token"]: token, cfg_info["env_url"]: base_url}

    codex_folder = cfg.get("codex_folder")
    using_codex_folder = args.type == "codex" and codex_folder not in (None, "", "null")

    if using_codex_folder:
        try:
            copy_codex_folder(str(codex_folder))
        except FileNotFoundError as exc:
            print(f"[Error] {exc}", file=sys.stderr)
            return 1

    if args.mode == "temp":
        if using_codex_folder:
            print(f"# 已切换到 codex 文件夹配置: {cfg.get('name', idx)}")
            print(f"# 已复制 codex/{codex_folder} -> .codex/")
            print("# 此模式不设置 OPENAI_* 环境变量（与 ai.sh 保持一致）")
        else:
            print(build_export_lines(env_vars))
            print(f"# 已输出 export 行，配置: [{idx}] {cfg.get('name', '<未命名>')}")
            print("# 建议执行: eval \"$(python ai_env.py --type {t} --index {i})\"".format(
                t=args.type, i=idx
            ))
        return 0

    # permanent
    if using_codex_folder:
        print(f"[Info] 已复制 codex/{codex_folder} 到 .codex/，未写入环境变量")
        return 0

    shell_cfg = write_permanent(env_vars)
    print("已写入配置:")
    for k, v in env_vars.items():
        print(f"  {k}={v}")
    print(f"目标文件: {shell_cfg}")
    print(f"请执行: source {shell_cfg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())





