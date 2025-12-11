#!/bin/bash
# 配置管理函数（增删改查）

# 函数：初始化配置文件
init_config_file() {
    local config_file="$1"
    if [[ ! -f "$config_file" ]]; then
        echo '{"configs":[]}' > "$config_file"
    fi
}

# 函数：添加配置
add_config() {
    local ai_type="$1"
    local config_file

    if [[ "$ai_type" == "claude" ]]; then
        config_file="$CLAUDE_CONFIG_FILE"
        init_config_file "$config_file"
    elif [[ "$ai_type" == "codex" ]]; then
        config_file="$CODEX_CONFIG_FILE"
        init_config_file "$config_file"
    else
        echo "[Error] 无效的AI类型: $ai_type (应为 claude 或 codex)"
        exit 1
    fi

    echo "添加新配置 ($ai_type):"
    read -p "配置名称: " name
    read -p "渠道ID (channel_id，用于匹配健康检查，可选): " channel_id

    if [[ "$ai_type" == "claude" ]]; then
        read -p "Token: " token
        read -p "URL: " url
    else
        read -p "API Key: " api_key
        read -p "Base URL: " base_url
    fi

    read -p "输入价格 (例如: ¥1.5/1M tokens): " input_price
    read -p "输出价格 (例如: ¥1.5/1M tokens): " output_price
    read -p "描述 (可选): " description

    # 构建新配置JSON
    local new_config
    if [[ "$ai_type" == "claude" ]]; then
        new_config=$(jq -n \
            --arg name "$name" \
            --arg token "$token" \
            --arg url "$url" \
            --arg input "$input_price" \
            --arg output "$output_price" \
            --arg desc "$description" \
            --arg channel_id "$channel_id" \
            '{
                name: $name,
                token: $token,
                url: $url,
                channel_id: (if $channel_id == "" then null else $channel_id end),
                pricing: {
                    input: $input,
                    output: $output,
                    description: $desc
                }
            }')
    else
        new_config=$(jq -n \
            --arg name "$name" \
            --arg api_key "$api_key" \
            --arg base_url "$base_url" \
            --arg input "$input_price" \
            --arg output "$output_price" \
            --arg desc "$description" \
            --arg channel_id "$channel_id" \
            '{
                name: $name,
                api_key: $api_key,
                base_url: $base_url,
                channel_id: (if $channel_id == "" then null else $channel_id end),
                pricing: {
                    input: $input,
                    output: $output,
                    description: $desc
                }
            }')
    fi

    # 添加到配置文件
    jq ".configs += [$new_config]" "$config_file" > "${config_file}.tmp" && mv "${config_file}.tmp" "$config_file"
    echo "[Success] 配置已添加"
}

# 函数：编辑配置
edit_config() {
    local ai_type="$1"
    local index="$2"
    local config_file

    if [[ "$ai_type" == "claude" ]]; then
        config_file="$CLAUDE_CONFIG_FILE"
    elif [[ "$ai_type" == "codex" ]]; then
        config_file="$CODEX_CONFIG_FILE"
    else
        echo "[Error] 无效的AI类型: $ai_type"
        exit 1
    fi

    if [[ ! -f "$config_file" ]]; then
        echo "[Error] 配置文件不存在: $config_file"
        exit 1
    fi

    local config_count=$(jq '.configs | length' "$config_file")
    if [[ $index -lt 0 || $index -ge $config_count ]]; then
        echo "[Error] 无效的配置索引: $index (范围: 0-$((config_count-1)))"
        exit 1
    fi

    echo "编辑配置 ($ai_type) #$index:"

    # 显示当前配置
    local current_name=$(jq -r ".configs[$index].name" "$config_file")
    local current_channel_id=$(jq -r ".configs[$index].channel_id // \"\"" "$config_file")
    echo "当前配置: $current_name"
    echo ""

    read -p "配置名称 [回车保持 '$current_name']: " name
    name=${name:-$current_name}

    read -p "渠道ID [回车保持 '$current_channel_id']: " channel_id
    channel_id=${channel_id:-$current_channel_id}

    if [[ "$ai_type" == "claude" ]]; then
        local current_token=$(jq -r ".configs[$index].token" "$config_file")
        local current_url=$(jq -r ".configs[$index].url" "$config_file")
        read -p "Token [回车保持当前值]: " token
        token=${token:-$current_token}
        read -p "URL [回车保持当前值]: " url
        url=${url:-$current_url}

        jq ".configs[$index] |= . + {
            name: \"$name\",
            token: \"$token\",
            url: \"$url\",
            channel_id: (if \"$channel_id\" == \"\" then null else \"$channel_id\" end)
        }" "$config_file" > "${config_file}.tmp" && mv "${config_file}.tmp" "$config_file"
    else
        local current_api_key=$(jq -r ".configs[$index].api_key" "$config_file")
        local current_base_url=$(jq -r ".configs[$index].base_url" "$config_file")
        read -p "API Key [回车保持当前值]: " api_key
        api_key=${api_key:-$current_api_key}
        read -p "Base URL [回车保持当前值]: " base_url
        base_url=${base_url:-$current_base_url}

        jq ".configs[$index] |= . + {
            name: \"$name\",
            api_key: \"$api_key\",
            base_url: \"$base_url\",
            channel_id: (if \"$channel_id\" == \"\" then null else \"$channel_id\" end)
        }" "$config_file" > "${config_file}.tmp" && mv "${config_file}.tmp" "$config_file"
    fi

    echo "[Success] 配置已更新"
}

# 函数：删除配置
delete_config() {
    local ai_type="$1"
    local index="$2"
    local config_file

    if [[ "$ai_type" == "claude" ]]; then
        config_file="$CLAUDE_CONFIG_FILE"
    elif [[ "$ai_type" == "codex" ]]; then
        config_file="$CODEX_CONFIG_FILE"
    else
        echo "[Error] 无效的AI类型: $ai_type"
        exit 1
    fi

    if [[ ! -f "$config_file" ]]; then
        echo "[Error] 配置文件不存在: $config_file"
        exit 1
    fi

    local config_count=$(jq '.configs | length' "$config_file")
    if [[ $index -lt 0 || $index -ge $config_count ]]; then
        echo "[Error] 无效的配置索引: $index (范围: 0-$((config_count-1)))"
        exit 1
    fi

    local config_name=$(jq -r ".configs[$index].name" "$config_file")
    echo "确定要删除配置 '$config_name' (索引 $index) 吗? (y/N)"
    read -p "> " confirm

    if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
        jq "del(.configs[$index])" "$config_file" > "${config_file}.tmp" && mv "${config_file}.tmp" "$config_file"
        echo "[Success] 配置已删除"
    else
        echo "[Cancel] 已取消删除"
    fi
}

# 函数：列出配置
list_configs() {
    local ai_type="$1"
    local config_file

    if [[ "$ai_type" == "claude" ]]; then
        config_file="$CLAUDE_CONFIG_FILE"
    elif [[ "$ai_type" == "codex" ]]; then
        config_file="$CODEX_CONFIG_FILE"
    else
        echo "[Error] 无效的AI类型: $ai_type"
        exit 1
    fi

    if [[ ! -f "$config_file" ]]; then
        echo "[Error] 配置文件不存在: $config_file"
        exit 1
    fi

    local config_count=$(jq '.configs | length' "$config_file")
    if [[ $config_count -eq 0 ]]; then
        echo "没有配置"
        return
    fi

    # 拉取实时状态（仅在list_configs中使用）
    local health_data=$(fetch_health_status)

    echo -e "${BOLD}配置列表 ($ai_type):${RESET}"
    echo "=========================================="

    for ((i=0; i<config_count; i++)); do
        local name=$(jq -r ".configs[$i].name" "$config_file")
        local channel_id=$(jq -r ".configs[$i].channel_id // \"\"" "$config_file")
        local status=""
        local status_icon=""
        local last_check=""

        if [[ -n "$channel_id" && "$channel_id" != "null" && "$channel_id" != "" ]]; then
            local channel_info=$(get_channel_info_from_data "$channel_id" "$health_data")
            local status_val=$(echo "$channel_info" | cut -d'|' -f1)
            last_check=$(echo "$channel_info" | cut -d'|' -f2)

            if [[ "$status_val" == "ok" ]]; then
                status_icon="$STATUS_OK"
                status="$STATUS_OK_TEXT"
            elif [[ "$status_val" == "error" ]]; then
                status_icon="$STATUS_ERROR"
                status="$STATUS_ERROR_TEXT"
            elif [[ "$status_val" == "timeout" ]]; then
                status_icon="$STATUS_TIMEOUT"
                status="$STATUS_TIMEOUT_TEXT"
            else
                status_icon="$STATUS_UNKNOWN"
                status="$STATUS_UNKNOWN_TEXT"
            fi
        else
            status_icon="$STATUS_UNKNOWN"
            status="$STATUS_UNKNOWN_TEXT (未配置)"
        fi

        echo -e "${BOLD}[$i]${RESET} $status_icon ${GOLD}$name${RESET}"
        if [[ -n "$channel_id" && "$channel_id" != "null" && "$channel_id" != "" ]]; then
            local time_ago=$(format_time_ago "$last_check")
            if [[ -n "$time_ago" ]]; then
                echo -e "    ${GRAY}渠道ID:${RESET} ${CYAN}$channel_id${RESET} ${GRAY}|${RESET} ${GRAY}状态:${RESET} $status ${GRAY}($time_ago)${RESET}"
            else
                echo -e "    ${GRAY}渠道ID:${RESET} ${CYAN}$channel_id${RESET} ${GRAY}|${RESET} ${GRAY}状态:${RESET} $status"
            fi
        fi

        if [[ "$ai_type" == "claude" ]]; then
            local url=$(jq -r ".configs[$i].url" "$config_file")
            local clickable_url=$(format_clickable_url "$url")
            echo -e "    ${GRAY}URL:${RESET} $clickable_url"
        else
            local base_url=$(jq -r ".configs[$i].base_url" "$config_file")
            local clickable_url=$(format_clickable_url "$base_url")
            echo -e "    ${GRAY}Base URL:${RESET} $clickable_url"
        fi
        echo ""
    done
}
