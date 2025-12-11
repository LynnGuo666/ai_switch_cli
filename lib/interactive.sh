#!/bin/bash
# 交互式界面代码

# 函数：运行交互式配置选择界面
run_interactive() {
    # 清除屏幕内容
    clear

    # 检查配置文件是否存在
    CLAUDE_CONFIG_EXISTS=false
    CODEX_CONFIG_EXISTS=false

    if [[ -f "$CLAUDE_CONFIG_FILE" ]]; then
        CLAUDE_CONFIG_EXISTS=true
    fi

    if [[ -f "$CODEX_CONFIG_FILE" ]]; then
        CODEX_CONFIG_EXISTS=true
    fi

    # 选择AI类型（使用循环，支持输入0返回）
    while true; do
        # 获取当前Claude配置
        CURRENT_CLAUDE_CONFIG="未配置"
        if [[ $CLAUDE_CONFIG_EXISTS == true && -n "$ANTHROPIC_AUTH_TOKEN" && -n "$ANTHROPIC_BASE_URL" ]]; then
            config_count=$(jq '.configs | length' "$CLAUDE_CONFIG_FILE" 2>/dev/null || echo "0")
            for ((i=0; i<config_count; i++)); do
                token=$(jq -r ".configs[$i].token" "$CLAUDE_CONFIG_FILE" 2>/dev/null)
                url=$(jq -r ".configs[$i].url" "$CLAUDE_CONFIG_FILE" 2>/dev/null)
                if [[ "$token" == "$ANTHROPIC_AUTH_TOKEN" && "$url" == "$ANTHROPIC_BASE_URL" ]]; then
                    CURRENT_CLAUDE_CONFIG=$(jq -r ".configs[$i].name" "$CLAUDE_CONFIG_FILE" 2>/dev/null)
                    break
                fi
            done
        fi

        # 获取当前Codex配置
        CURRENT_CODEX_CONFIG="未配置"
        # 优先从 .codex/config.toml 读取当前节点
        current_node=$(get_current_codex_node)

        if [[ -n "$current_node" && $CODEX_CONFIG_EXISTS == true ]]; then
            # 根据节点名称匹配配置
            # 首先尝试通过配置中的 codex_folder 字段匹配
            config_count=$(jq '.configs | length' "$CODEX_CONFIG_FILE" 2>/dev/null || echo "0")
            for ((i=0; i<config_count; i++)); do
                codex_folder=$(jq -r ".configs[$i].codex_folder // \"\"" "$CODEX_CONFIG_FILE" 2>/dev/null)
                if [[ "$codex_folder" == "$current_node" ]]; then
                    CURRENT_CODEX_CONFIG=$(jq -r ".configs[$i].name" "$CODEX_CONFIG_FILE" 2>/dev/null)
                    break
                fi
            done

            # 如果没有匹配到，尝试通过环境变量匹配（向后兼容）
            if [[ "$CURRENT_CODEX_CONFIG" == "未配置" && -n "$OPENAI_API_KEY" && -n "$OPENAI_BASE_URL" ]]; then
                config_count=$(jq '.configs | length' "$CODEX_CONFIG_FILE" 2>/dev/null || echo "0")
                for ((i=0; i<config_count; i++)); do
                    api_key=$(jq -r ".configs[$i].api_key" "$CODEX_CONFIG_FILE" 2>/dev/null)
                    base_url=$(jq -r ".configs[$i].base_url" "$CODEX_CONFIG_FILE" 2>/dev/null)
                    if [[ "$api_key" == "$OPENAI_API_KEY" && "$base_url" == "$OPENAI_BASE_URL" ]]; then
                        CURRENT_CODEX_CONFIG=$(jq -r ".configs[$i].name" "$CODEX_CONFIG_FILE" 2>/dev/null)
                        break
                    fi
                done
            fi
        elif [[ $CODEX_CONFIG_EXISTS == true && -n "$OPENAI_API_KEY" && -n "$OPENAI_BASE_URL" ]]; then
            # 如果没有 .codex/config.toml，使用环境变量匹配（向后兼容）
            config_count=$(jq '.configs | length' "$CODEX_CONFIG_FILE" 2>/dev/null || echo "0")
            for ((i=0; i<config_count; i++)); do
                api_key=$(jq -r ".configs[$i].api_key" "$CODEX_CONFIG_FILE" 2>/dev/null)
                base_url=$(jq -r ".configs[$i].base_url" "$CODEX_CONFIG_FILE" 2>/dev/null)
                if [[ "$api_key" == "$OPENAI_API_KEY" && "$base_url" == "$OPENAI_BASE_URL" ]]; then
                    CURRENT_CODEX_CONFIG=$(jq -r ".configs[$i].name" "$CODEX_CONFIG_FILE" 2>/dev/null)
                    break
                fi
            done
        fi

        # 选择AI类型
        clear
        echo "=========================================="
        echo "AI 配置切换工具"
        echo "=========================================="
        echo ""
        echo "请选择 AI 类型:"
        echo "1) Claude (当前: $CURRENT_CLAUDE_CONFIG)"
        echo "2) Codex (OpenAI) (当前: $CURRENT_CODEX_CONFIG)"
        echo ""
        read -p "选择 [1/2]: " ai_choice

        # 根据选择设置配置文件和环境变量类型
        if [ "$ai_choice" = "1" ]; then
            AI_TYPE="claude"
            CONFIG_FILE="$CLAUDE_CONFIG_FILE"
            ENV_TOKEN_NAME="ANTHROPIC_AUTH_TOKEN"
            ENV_URL_NAME="ANTHROPIC_BASE_URL"
            DISPLAY_NAME="Claude"
        elif [ "$ai_choice" = "2" ]; then
            AI_TYPE="codex"
            CONFIG_FILE="$CODEX_CONFIG_FILE"
            ENV_TOKEN_NAME="OPENAI_API_KEY"
            ENV_URL_NAME="OPENAI_BASE_URL"
            DISPLAY_NAME="Codex"
        else
            echo "[Error] 无效选择"
            continue
        fi

        clear

        # 检查配置文件是否存在
        if [[ ! -f "$CONFIG_FILE" ]]; then
            echo "[Error] 配置文件不存在: $CONFIG_FILE"
            echo "请创建配置文件，JSON格式"
            exit 1
        fi

        # 检查是否通过source运行（使用主入口传递的 IS_SOURCED 变量）
        echo "=========================================="
        if [[ "$IS_SOURCED" == "false" ]]; then
            echo "$DISPLAY_NAME 配置切换工具"
            echo "永久设置模式"
            FORCE_PERMANENT=true
            TEMP_SETTING_AVAILABLE=false
        else
            echo "$DISPLAY_NAME 配置切换工具"
            echo ""
            FORCE_PERMANENT=""
            TEMP_SETTING_AVAILABLE=true
        fi
        echo "作者：Lynn v1.8.0"
        echo "=========================================="

        # 读取配置文件并显示选项
        echo ""

        # 获取配置数量
        config_count=$(jq '.configs | length' "$CONFIG_FILE")

        # 创建临时文件来存储排序后的配置
        temp_file=$(mktemp)

        # 在脚本开始时拉取健康检查状态（全局使用，运行期间都可以使用）
        health_data=$(fetch_health_status)

        # 获取当前配置名称（用于高亮显示）
        current_config_name=""
        # 根据AI类型检查不同的环境变量
        if [ "$AI_TYPE" = "claude" ]; then
            CURRENT_TOKEN="$ANTHROPIC_AUTH_TOKEN"
            CURRENT_URL="$ANTHROPIC_BASE_URL"
            TOKEN_FIELD="token"
            URL_FIELD="url"
        else
            CURRENT_TOKEN="$OPENAI_API_KEY"
            CURRENT_URL="$OPENAI_BASE_URL"
            TOKEN_FIELD="api_key"
            URL_FIELD="base_url"
        fi

        if [[ -n "$CURRENT_TOKEN" && -n "$CURRENT_URL" ]]; then
            config_count_check=$(jq '.configs | length' "$CONFIG_FILE")
            for ((i=0; i<config_count_check; i++)); do
                token=$(jq -r ".configs[$i].$TOKEN_FIELD" "$CONFIG_FILE")
                url=$(jq -r ".configs[$i].$URL_FIELD" "$CONFIG_FILE")
                if [[ "$token" == "$CURRENT_TOKEN" && "$url" == "$CURRENT_URL" ]]; then
                    current_config_name=$(jq -r ".configs[$i].name" "$CONFIG_FILE")
                    break
                fi
            done
        fi

        # 将配置信息写入临时文件，包含索引信息
        for ((i=0; i<config_count; i++)); do
            name=$(jq -r ".configs[$i].name" "$CONFIG_FILE")
            channel_id=$(jq -r ".configs[$i].channel_id // \"\"" "$CONFIG_FILE")
            input_price=$(jq -r ".configs[$i].pricing.input" "$CONFIG_FILE")
            output_price=$(jq -r ".configs[$i].pricing.output" "$CONFIG_FILE")
            description=$(jq -r ".configs[$i].pricing.description" "$CONFIG_FILE")

            # 获取渠道状态
            status_icon=""
            status_color=""
            last_check_time=""
            if [[ -n "$channel_id" && "$channel_id" != "null" && "$channel_id" != "" ]]; then
                channel_info=$(get_channel_info_from_data "$channel_id" "$health_data")
                status=$(echo "$channel_info" | cut -d'|' -f1)
                last_check_time=$(echo "$channel_info" | cut -d'|' -f2)

                if [[ "$status" == "ok" ]]; then
                    status_icon="$STATUS_OK"
                    status_color="ok"
                elif [[ "$status" == "error" ]]; then
                    status_icon="$STATUS_ERROR"
                    status_color="error"
                elif [[ "$status" == "timeout" ]]; then
                    status_icon="$STATUS_TIMEOUT"
                    status_color="timeout"
                else
                    status_icon="$STATUS_UNKNOWN"
                    status_color="unknown"
                fi
            else
                # 没有channel_id时，使用灰色点
                status_icon="$STATUS_UNKNOWN"
                status_color=""
            fi

            # 提取价格数字用于排序（处理 ¥0.9/1M tokens 或 $3/1M tokens 格式）
            input_num=$(echo "$input_price" | grep -o '[0-9]*\.\?[0-9]*' | head -1)
            output_num=$(echo "$output_price" | grep -o '[0-9]*\.\?[0-9]*' | head -1)

            # 如果无法提取数字，使用0
            input_num=${input_num:-0}
            output_num=${output_num:-0}

            # 检查是否为美元价格，如果是则乘以7转换为人民币
            if [[ "$input_price" == *"$"* ]]; then
                input_num=$(echo "$input_num * 7" | bc -l 2>/dev/null || echo "$input_num")
            fi
            if [[ "$output_price" == *"$"* ]]; then
                output_num=$(echo "$output_num * 7" | bc -l 2>/dev/null || echo "$output_num")
            fi

            # 计算总价格（输入+输出）
            total_price=$(echo "$input_num + $output_num" | bc -l 2>/dev/null || echo "0")

            echo "$i|$name|$input_price|$output_price|$description|$total_price|$status_icon|$channel_id|$status_color|$last_check_time" >> "$temp_file"
        done

        # 按总价格排序（从低到高）
        if command -v bc &> /dev/null; then
            sort -t'|' -k6,6n "$temp_file" > "${temp_file}.sorted"
            mv "${temp_file}.sorted" "$temp_file"
        else
            echo "[Warning] 未找到bc命令，将按原始顺序显示"
        fi

        # 显示排序后的配置
        line_num=1
        while IFS='|' read -r index name input_price output_price description total_price status_icon channel_id status_color last_check_time; do
            # 判断是否是当前配置
            if [[ "$name" == "$current_config_name" ]]; then
                name_color="${GOLD}"
            else
                name_color="${WHITE}"
            fi

            # 显示配置名称（前面始终有点，有状态用对应颜色，无状态用灰色）
            if [[ -n "$last_check_time" && "$last_check_time" != "" ]]; then
                # 格式化时间显示为"xx分钟前"
                time_ago=$(format_time_ago "$last_check_time")
                if [[ -n "$time_ago" ]]; then
                    echo -e "${BOLD}$line_num)${RESET} $status_icon ${name_color}$name${RESET} ${GRAY}($time_ago)${RESET}"
                else
                    echo -e "${BOLD}$line_num)${RESET} $status_icon ${name_color}$name${RESET}"
                fi
            else
                echo -e "${BOLD}$line_num)${RESET} $status_icon ${name_color}$name${RESET}"
            fi

            # 显示价格信息（全部改为灰色）
            echo -e "    ${GRAY}输入: $input_price | 输出: $output_price${RESET}"

            # 计算并显示转换后的人民币价格
            input_num=$(echo "$input_price" | grep -o '[0-9]*\.\?[0-9]*' | head -1)
            output_num=$(echo "$output_price" | grep -o '[0-9]*\.\?[0-9]*' | head -1)
            input_num=${input_num:-0}
            output_num=${output_num:-0}

            # 检查是否为美元价格，如果是则乘以7转换为人民币
            if [[ "$input_price" == *"$"* ]]; then
                input_cny=$(echo "$input_num * 7" | bc -l 2>/dev/null || echo "$input_num")
                output_cny=$(echo "$output_num * 7" | bc -l 2>/dev/null || echo "$output_num")
                echo -e "    ${GRAY}(约 ¥${input_cny}/1M tokens | ¥${output_cny}/1M tokens)${RESET}"
            fi

            # 只有当描述不为空且不是null时才显示（改为灰色）
            if [[ -n "$description" && "$description" != "null" ]]; then
                echo -e "    ${GRAY}$description${RESET}"
            fi
            echo ""

            # 保存索引映射
            eval "config_index_$line_num=$index"

            line_num=$((line_num + 1))
        done < "$temp_file"

        # 清理临时文件
        rm -f "$temp_file"

        # 在列表末尾显示当前设置
        if [[ -n "$current_config_name" ]]; then
            echo "当前设置：$current_config_name"
        else
            echo "当前设置：未配置"
        fi
        echo "=========================================="
        if [[ "$AI_TYPE" == "codex" ]]; then
            echo "0) 清除 Codex 环境变量 (恢复官方设置)"
            echo "b) 返回AI类型选择"
        else
            echo "0) 返回AI类型选择"
        fi
        echo ""

        read -p "#? " choice

        if [[ "$AI_TYPE" == "codex" && ( "$choice" == "b" || "$choice" == "B" ) ]]; then
            continue
        fi

        if [[ "$AI_TYPE" != "codex" && "$choice" == "0" ]]; then
            continue
        fi

        if [[ "$AI_TYPE" == "codex" && "$choice" == "0" ]]; then
            if [[ -z "$FORCE_PERMANENT" ]]; then
                echo ""
                echo "请选择清除方式:"
                echo "1) 临时清除 (仅当前终端会话有效)"
                echo "2) 永久清除 (移除 shell 配置文件)"
                read -p "设置方式 [1/2]: " clear_mode
            else
                clear_mode="2"
            fi

            if [[ "$clear_mode" == "1" || "$clear_mode" == "2" ]]; then
                clear_codex_env_vars "$clear_mode"
            else
                echo "[Error] 无效的清除方式选择"
            fi
            read -p "按 Enter 返回配置列表..." _
            continue
        fi

        if [[ -z "$FORCE_PERMANENT" ]]; then
            echo ""
            echo "请选择设置方式:"
            echo "1) 临时设置 (仅当前终端会话有效)"
            echo "2) 永久设置 (写入配置文件)"

            read -p "设置方式 [1/2]: " mode
        else
            mode="2"
        fi

        # 验证选择并获取配置
        if [[ $choice -ge 1 && $choice -le $((line_num-1)) ]]; then
            # 使用保存的索引映射
            eval "index=\$config_index_$choice"
            CONFIG_NAME=$(jq -r ".configs[$index].name" "$CONFIG_FILE")

            # 根据AI类型读取不同的字段
            if [ "$AI_TYPE" = "claude" ]; then
                TOKEN=$(jq -r ".configs[$index].token" "$CONFIG_FILE")
                BASE_URL=$(jq -r ".configs[$index].url" "$CONFIG_FILE")
                USE_CODEX_FOLDER=false
            else
                TOKEN=$(jq -r ".configs[$index].api_key" "$CONFIG_FILE")
                BASE_URL=$(jq -r ".configs[$index].base_url" "$CONFIG_FILE")

                # 如果是 Codex 配置，检查是否有 codex_folder 字段
                codex_folder=$(jq -r ".configs[$index].codex_folder // \"\"" "$CONFIG_FILE")
                if [[ -n "$codex_folder" && "$codex_folder" != "null" && "$codex_folder" != "" ]]; then
                    # 如果有 codex_folder，复制配置文件到 .codex/，但不设置环境变量
                    copy_codex_configs "$codex_folder" >/dev/null 2>&1 || true
                    # 标记为使用文件夹配置，跳过环境变量设置
                    USE_CODEX_FOLDER=true
                else
                    USE_CODEX_FOLDER=false
                fi
            fi
        else
            echo "[Error] 无效选择"
            continue
        fi

        if [ "$mode" = "1" ]; then
            # 临时设置
            if [[ "$AI_TYPE" == "codex" && "$USE_CODEX_FOLDER" == "true" ]]; then
                # 如果使用 codex_folder，只复制配置文件，不设置环境变量
                echo "已切换到: $CONFIG_NAME (临时设置)"
                echo "配置文件已复制到 .codex/ 文件夹"
                echo "仅在当前终端会话中有效"
            else
                # 其他情况正常设置环境变量
                export "$ENV_TOKEN_NAME=$TOKEN"
                export "$ENV_URL_NAME=$BASE_URL"
                echo "已切换到: $CONFIG_NAME (临时设置)"
                echo "仅在当前终端会话中有效"
            fi
            break
        elif [ "$mode" = "2" ]; then
            # 永久设置
            if [[ "$AI_TYPE" == "codex" && "$USE_CODEX_FOLDER" == "true" ]]; then
                # 如果使用 codex_folder，只复制配置文件，不设置环境变量
                echo "已切换到: $CONFIG_NAME (永久设置)"
                echo "配置文件已复制到 .codex/ 文件夹"
            else
                # 检测当前shell类型
                if [ -n "$ZSH_VERSION" ] || [ "$SHELL" = "/bin/zsh" ] || [ "$SHELL" = "/usr/bin/zsh" ]; then
                    SHELL_CONFIG_FILE="$HOME/.zshrc"
                else
                    SHELL_CONFIG_FILE="$HOME/.bash_profile"
                fi

                # 1. 先在内存中准备好要输出的内容
                output_message="切换配置任务清单:
■ 配置已写入: $SHELL_CONFIG_FILE
□ 刷新配置生效
□ 请手动执行以下命令以刷新配置：
   source $SHELL_CONFIG_FILE

✓ 已切换到: $CONFIG_NAME (永久设置)"

                # 2. 执行文件写入操作
                # 移除旧的配置（如果存在）
                grep -v "$ENV_TOKEN_NAME=" "$SHELL_CONFIG_FILE" > "$SHELL_CONFIG_FILE.tmp" 2>/dev/null || touch "$SHELL_CONFIG_FILE.tmp"
                grep -v "$ENV_URL_NAME=" "$SHELL_CONFIG_FILE.tmp" > "$SHELL_CONFIG_FILE.tmp2"
                mv "$SHELL_CONFIG_FILE.tmp2" "$SHELL_CONFIG_FILE"
                rm -f "$SHELL_CONFIG_FILE.tmp"

                # 添加新配置
                echo "export $ENV_TOKEN_NAME=\"$TOKEN\"" >> "$SHELL_CONFIG_FILE"
                echo "export $ENV_URL_NAME=\"$BASE_URL\"" >> "$SHELL_CONFIG_FILE"

                # 3. 最后，一次性打印所有输出
                echo "$output_message"
            fi
            break
        else
            echo "[Error] 无效的设置方式选择"
            continue
        fi
    done
}
