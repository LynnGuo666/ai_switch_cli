#!/bin/bash
# Codex 特定函数

# 函数：从 .codex/config.toml 读取当前节点信息
get_current_codex_node() {
    local codex_config_dir="$SCRIPT_DIR/.codex"
    local config_toml="$codex_config_dir/config.toml"

    if [[ ! -f "$config_toml" ]]; then
        echo ""
        return
    fi

    # 读取 model_provider 字段（如果存在）
    # 使用 grep 和 sed 来解析 TOML 文件
    # 处理 model_provider = "anyrouter" 或 model_provider = anyrouter
    local model_provider=$(grep -E "^model_provider\s*=" "$config_toml" 2>/dev/null | sed -E 's/^model_provider\s*=\s*"([^"]+)".*/\1/' | sed -E 's/^model_provider\s*=\s*([^[:space:]]+).*/\1/')

    if [[ -n "$model_provider" && "$model_provider" != "null" ]]; then
        echo "$model_provider"
    else
        # 如果没有 model_provider，尝试从 [model_providers.*] 部分读取
        local provider_name=$(grep -E "^\[model_providers\." "$config_toml" 2>/dev/null | sed -E 's/^\[model_providers\.([^]]+)\].*/\1/')
        if [[ -n "$provider_name" && "$provider_name" != "null" ]]; then
            echo "$provider_name"
        else
            echo ""
        fi
    fi
}

# 函数：复制 codex 配置文件到 .codex/ 文件夹
copy_codex_configs() {
    local config_folder="$1"
    local codex_source_dir="$SCRIPT_DIR/codex/$config_folder"
    local codex_target_dir="$SCRIPT_DIR/.codex"

    # 检查源文件夹是否存在
    if [[ ! -d "$codex_source_dir" ]]; then
        return 1
    fi

    # 创建目标文件夹（如果不存在）
    mkdir -p "$codex_target_dir"

    # 复制 config.toml 和 auth.json
    if [[ -f "$codex_source_dir/config.toml" ]]; then
        cp "$codex_source_dir/config.toml" "$codex_target_dir/config.toml"
    else
        return 1
    fi

    if [[ -f "$codex_source_dir/auth.json" ]]; then
        cp "$codex_source_dir/auth.json" "$codex_target_dir/auth.json"
    else
        return 1
    fi

    return 0
}

# 函数：清除 Codex 环境变量
clear_codex_env_vars() {
    local mode="$1"

    if [[ "$mode" == "1" ]]; then
        unset OPENAI_API_KEY
        unset OPENAI_BASE_URL
        echo "[Success] 已临时清除 Codex 环境变量"
        echo "仅在当前终端会话中生效"
        return 0
    elif [[ "$mode" == "2" ]]; then
        local shell_config_file
        if [ -n "$ZSH_VERSION" ] || [ "$SHELL" = "/bin/zsh" ] || [ "$SHELL" = "/usr/bin/zsh" ]; then
            shell_config_file="$HOME/.zshrc"
        else
            shell_config_file="$HOME/.bash_profile"
        fi

        touch "$shell_config_file"
        local tmp_file="${shell_config_file}.tmp"
        sed -e '/OPENAI_API_KEY=/d' -e '/OPENAI_BASE_URL=/d' "$shell_config_file" > "$tmp_file"
        mv "$tmp_file" "$shell_config_file"

        unset OPENAI_API_KEY
        unset OPENAI_BASE_URL

        echo "[Success] 已从 $shell_config_file 中移除 Codex 环境变量"
        echo "请执行: source $shell_config_file"
        return 0
    fi

    echo "[Error] 无效的清除模式"
    return 1
}
