#!/bin/bash
# 健康检查相关函数

# 默认健康检查URL（如果没有配置文件或配置文件为空时使用）
DEFAULT_HEALTH_CHECK_URL="https://check-cx.59188888.xyz/health"

# 健康检查数据缓存（避免频繁请求）
HEALTH_CHECK_CACHE_FILE="/tmp/ai_health_check_cache.json"
HEALTH_CHECK_CACHE_TTL=60  # 缓存60秒

# 函数：获取健康检查URL列表
get_health_check_urls() {
    # 如果配置文件存在，从中读取URL列表
    if [[ -f "$HEALTH_CHECK_CONFIG_FILE" ]]; then
        local urls=$(jq -r '.health_check_urls[]?' "$HEALTH_CHECK_CONFIG_FILE" 2>/dev/null)
        if [[ -n "$urls" ]]; then
            echo "$urls"
            return
        fi
    fi

    # 如果没有配置文件或配置文件为空，使用默认URL
    echo "$DEFAULT_HEALTH_CHECK_URL"
}

# 函数：从单个URL获取健康检查状态
fetch_single_health_status() {
    local url="$1"
    local response=$(curl -s --max-time 5 "$url" 2>/dev/null)
    if [[ $? -eq 0 && -n "$response" ]]; then
        echo "$response"
    else
        echo '{"services":{}}'
    fi
}

# 函数：合并多个健康检查数据
merge_health_data() {
    local merged='{"services":{}}'

    # 读取所有URL并合并数据
    while IFS= read -r url; do
        if [[ -z "$url" || "$url" == "null" ]]; then
            continue
        fi

        local data=$(fetch_single_health_status "$url")
        if [[ -n "$data" && "$data" != '{"services":{}}' ]]; then
            # 使用jq合并services对象
            merged=$(echo "$merged" | jq --argjson new "$data" '.services * $new.services | {services: .}' 2>/dev/null || echo "$merged")
        fi
    done <<< "$(get_health_check_urls)"

    echo "$merged"
}

# 函数：获取健康检查状态（实时拉取，不使用缓存）
# 支持从多个URL获取数据并合并
fetch_health_status() {
    echo -e "${GRAY}正在拉取渠道状态...${RESET}" >&2
    merge_health_data
}

# 函数：根据channel_id获取服务状态和lastCheck时间（从已拉取的数据中）
get_channel_info_from_data() {
    local channel_id="$1"
    local health_data="$2"

    local status=$(echo "$health_data" | jq -r ".services.\"$channel_id\".status // \"unknown\"" 2>/dev/null)
    local last_check=$(echo "$health_data" | jq -r ".services.\"$channel_id\".lastCheck // \"\"" 2>/dev/null)

    if [[ "$status" == "null" || "$status" == "" ]]; then
        echo "unknown||"
    else
        echo "$status|$last_check|"
    fi
}

# 函数：根据channel_id获取服务状态和lastCheck时间
get_channel_status() {
    local channel_id="$1"
    local health_data=$(fetch_health_status)

    local status=$(echo "$health_data" | jq -r ".services.\"$channel_id\".status // \"unknown\"" 2>/dev/null)
    local last_check=$(echo "$health_data" | jq -r ".services.\"$channel_id\".lastCheck // \"\"" 2>/dev/null)

    if [[ "$status" == "null" || "$status" == "" ]]; then
        echo "unknown|"
    else
        echo "$status|$last_check"
    fi
}

# 函数：显示所有渠道状态
show_status() {
    echo -e "${BOLD}渠道状态检查${RESET}"
    echo "=========================================="

    # 拉取实时状态
    local health_data=$(fetch_health_status)

    local services=$(echo "$health_data" | jq -r '.services | keys[]' 2>/dev/null)

    if [[ -z "$services" ]]; then
        echo -e "${YELLOW}[Warning] 无法获取渠道状态${RESET}"
        return
    fi

    echo "$health_data" | jq -r '.services | to_entries[] | "\(.key): \(.value.status): \(.value.lastCheck)"' 2>/dev/null | while IFS=':' read -r channel_id status_val last_check; do
        # 清理变量（去除空格）
        channel_id=$(echo "$channel_id" | xargs)
        status_val=$(echo "$status_val" | xargs)
        last_check=$(echo "$last_check" | xargs)

        local time_ago=$(format_time_ago "$last_check")

        if [[ "$status_val" == "ok" ]]; then
            if [[ -n "$time_ago" ]]; then
                echo -e "$STATUS_OK ${CYAN}$channel_id${RESET} ${GRAY}-${RESET} ${GREEN}ok${RESET} ${GRAY}($time_ago)${RESET}"
            else
                echo -e "$STATUS_OK ${CYAN}$channel_id${RESET} ${GRAY}-${RESET} ${GREEN}ok${RESET}"
            fi
        elif [[ "$status_val" == "error" ]]; then
            if [[ -n "$time_ago" ]]; then
                echo -e "$STATUS_ERROR ${CYAN}$channel_id${RESET} ${GRAY}-${RESET} ${RED}error${RESET} ${GRAY}($time_ago)${RESET}"
            else
                echo -e "$STATUS_ERROR ${CYAN}$channel_id${RESET} ${GRAY}-${RESET} ${RED}error${RESET}"
            fi
        elif [[ "$status_val" == "timeout" ]]; then
            if [[ -n "$time_ago" ]]; then
                echo -e "$STATUS_TIMEOUT ${CYAN}$channel_id${RESET} ${GRAY}-${RESET} ${YELLOW}timeout${RESET} ${GRAY}($time_ago)${RESET}"
            else
                echo -e "$STATUS_TIMEOUT ${CYAN}$channel_id${RESET} ${GRAY}-${RESET} ${YELLOW}timeout${RESET}"
            fi
        else
            if [[ -n "$time_ago" ]]; then
                echo -e "$STATUS_UNKNOWN ${CYAN}$channel_id${RESET} ${GRAY}-${RESET} ${GRAY}unknown${RESET} ${GRAY}($time_ago)${RESET}"
            else
                echo -e "$STATUS_UNKNOWN ${CYAN}$channel_id${RESET} ${GRAY}-${RESET} ${GRAY}unknown${RESET}"
            fi
        fi
    done

    echo ""
    echo -e "${BOLD}配置中的渠道匹配:${RESET}"
    echo "----------------------------------------"

    # 检查Claude配置
    if [[ -f "$CLAUDE_CONFIG_FILE" ]]; then
        local claude_count=$(jq '.configs | length' "$CLAUDE_CONFIG_FILE" 2>/dev/null || echo "0")
        for ((i=0; i<claude_count; i++)); do
            local name=$(jq -r ".configs[$i].name" "$CLAUDE_CONFIG_FILE" 2>/dev/null)
            local channel_id=$(jq -r ".configs[$i].channel_id // \"\"" "$CLAUDE_CONFIG_FILE" 2>/dev/null)
            if [[ -n "$channel_id" && "$channel_id" != "null" && "$channel_id" != "" ]]; then
                local channel_info=$(get_channel_info_from_data "$channel_id" "$health_data")
                local status=$(echo "$channel_info" | cut -d'|' -f1)
                local last_check=$(echo "$channel_info" | cut -d'|' -f2)
                local time_ago=$(format_time_ago "$last_check")

                if [[ "$status" == "ok" ]]; then
                    if [[ -n "$time_ago" ]]; then
                        echo -e "$STATUS_OK ${BOLD}Claude:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET} ${GRAY}($time_ago)${RESET}"
                    else
                        echo -e "$STATUS_OK ${BOLD}Claude:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET}"
                    fi
                elif [[ "$status" == "error" ]]; then
                    if [[ -n "$time_ago" ]]; then
                        echo -e "$STATUS_ERROR ${BOLD}Claude:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET} ${GRAY}($time_ago)${RESET}"
                    else
                        echo -e "$STATUS_ERROR ${BOLD}Claude:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET}"
                    fi
                elif [[ "$status" == "timeout" ]]; then
                    if [[ -n "$time_ago" ]]; then
                        echo -e "$STATUS_TIMEOUT ${BOLD}Claude:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET} ${GRAY}($time_ago)${RESET}"
                    else
                        echo -e "$STATUS_TIMEOUT ${BOLD}Claude:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET}"
                    fi
                else
                    echo -e "$STATUS_UNKNOWN ${BOLD}Claude:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET} ${GRAY}- 未找到${RESET}"
                fi
            fi
        done
    fi

    # 检查Codex配置
    if [[ -f "$CODEX_CONFIG_FILE" ]]; then
        local codex_count=$(jq '.configs | length' "$CODEX_CONFIG_FILE" 2>/dev/null || echo "0")
        for ((i=0; i<codex_count; i++)); do
            local name=$(jq -r ".configs[$i].name" "$CODEX_CONFIG_FILE" 2>/dev/null)
            local channel_id=$(jq -r ".configs[$i].channel_id // \"\"" "$CODEX_CONFIG_FILE" 2>/dev/null)
            if [[ -n "$channel_id" && "$channel_id" != "null" && "$channel_id" != "" ]]; then
                local channel_info=$(get_channel_info_from_data "$channel_id" "$health_data")
                local status=$(echo "$channel_info" | cut -d'|' -f1)
                local last_check=$(echo "$channel_info" | cut -d'|' -f2)
                local time_ago=$(format_time_ago "$last_check")

                if [[ "$status" == "ok" ]]; then
                    if [[ -n "$time_ago" ]]; then
                        echo -e "$STATUS_OK ${BOLD}Codex:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET} ${GRAY}($time_ago)${RESET}"
                    else
                        echo -e "$STATUS_OK ${BOLD}Codex:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET}"
                    fi
                elif [[ "$status" == "error" ]]; then
                    if [[ -n "$time_ago" ]]; then
                        echo -e "$STATUS_ERROR ${BOLD}Codex:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET} ${GRAY}($time_ago)${RESET}"
                    else
                        echo -e "$STATUS_ERROR ${BOLD}Codex:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET}"
                    fi
                elif [[ "$status" == "timeout" ]]; then
                    if [[ -n "$time_ago" ]]; then
                        echo -e "$STATUS_TIMEOUT ${BOLD}Codex:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET} ${GRAY}($time_ago)${RESET}"
                    else
                        echo -e "$STATUS_TIMEOUT ${BOLD}Codex:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET}"
                    fi
                else
                    echo -e "$STATUS_UNKNOWN ${BOLD}Codex:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET} ${GRAY}- 未找到${RESET}"
                fi
            fi
        done
    fi
}
