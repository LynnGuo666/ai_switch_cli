# AI 配置管理工具

这是一个用于管理 Claude (Anthropic) 和 Codex (OpenAI) 配置的 Bash 脚本工具，支持配置切换、健康检查和管理功能。

## 功能特性

- 支持 Claude 和 Codex 配置管理
- 交互式配置切换（临时/永久）
- 命令行模式管理配置
- 实时渠道健康检查
- 配置价格显示和排序
- 支持 Codex 文件夹配置 (.codex/)
- 自动检测当前激活配置

## 安装要求

- Bash
- jq (JSON 处理工具)
- curl (用于健康检查)
- bc (可选，用于价格排序)

### 安装依赖

**macOS:**
```bash
brew install jq curl
```

**Ubuntu/Debian:**
```bash
sudo apt install jq curl
```

## 使用方法

### 交互式模式

直接运行脚本启动交互式配置切换：

```bash
./ai.sh
```

在交互式模式中，你可以：
1. 选择 AI 类型 (Claude/Codex)
2. 查看所有可用配置（按价格排序）
3. 查看实时渠道状态
4. 临时或永久切换配置

### 命令行模式

**添加配置:**
```bash
./ai.sh --add claude    # 添加 Claude 配置
./ai.sh --add codex     # 添加 Codex 配置
```

**编辑配置:**
```bash
./ai.sh --edit claude 0  # 编辑 Claude 配置索引 0
./ai.sh --edit codex 1   # 编辑 Codex 配置索引 1
```

**删除配置:**
```bash
./ai.sh --delete claude 0  # 删除 Claude 配置索引 0
./ai.sh --delete codex 1   # 删除 Codex 配置索引 1
```

**列出配置:**
```bash
./ai.sh --list claude  # 列出所有 Claude 配置
./ai.sh --list codex   # 列出所有 Codex 配置
```

**查看渠道状态:**
```bash
./ai.sh --status  # 显示所有渠道健康状态
```

**显示帮助:**
```bash
./ai.sh --help    # 显示帮助信息
```

## 配置文件

### Claude 配置 (`claude_configs.json`)

```json
{
  "configs": [
    {
      "name": "配置名称",
      "token": "ANTHROPIC_AUTH_TOKEN",
      "url": "ANTHROPIC_BASE_URL",
      "channel_id": "渠道ID (可选)",
      "pricing": {
        "input": "¥1.5/1M tokens",
        "output": "¥1.5/1M tokens",
        "description": "配置描述 (可选)"
      }
    }
  ]
}
```

### Codex 配置 (`codex_configs.json`)

```json
{
  "configs": [
    {
      "name": "配置名称",
      "api_key": "OPENAI_API_KEY",
      "base_url": "OPENAI_BASE_URL",
      "codex_folder": "文件夹名称 (可选)",
      "channel_id": "渠道ID (可选)",
      "pricing": {
        "input": "¥1.5/1M tokens",
        "output": "¥1.5/1M tokens",
        "description": "配置描述 (可选)"
      }
    }
  ]
}
```

### Codex 文件夹配置

为 Codex 配置支持文件夹存储方式：

目录结构：
```
./codex/
├── 配置名称1/
│   ├── auth.json
│   └── config.toml
└── 配置名称2/
    ├── auth.json
    └── config.toml
```

在配置文件中添加 `codex_folder` 字段：
```json
{
  "name": "自定义名称",
  "codex_folder": "配置名称1",
  "channel_id": "渠道ID",
  "pricing": {
    "input": "¥1.5/1M tokens",
    "output": "¥1.5/1M tokens"
  }
}
```

程序会自动将配置文件复制到 `.codex/` 目录。

### 健康检查配置 (`health_check_configs.json`)

配置健康检查 URL：

```json
{
  "health_check_urls": [
    "https://check-cx.59188888.xyz/health",
    "https://其他健康检查地址/health"
  ]
}
```

如果不配置此文件，脚本将使用默认 URL：
`https://check-cx.59188888.xyz/health`

## 环境变量

脚本会设置以下环境变量：

**Claude:**
- `ANTHROPIC_AUTH_TOKEN` - API Token
- `ANTHROPIC_BASE_URL` - API Base URL

**Codex:**
- `OPENAI_API_KEY` - API Key
- `OPENAI_BASE_URL` - API Base URL

## 渠道状态

支持多种渠道状态显示：

- **● 正常 (绿色)** - 服务正常运行
- **● 错误 (红色)** - 服务异常
- **● 超时 (黄色)** - 请求超时
- **○ 未知 (灰色)** - 状态未知

状态信息会显示最后检查时间（如"5分钟前"）。

## 版本信息

当前版本：v1.8.0

版本更新：
- v1.8.0: 增强 Codex 配置管理，支持文件夹配置
- v1.7.0: 动态健康检查 URL 配置
- v1.6.0: 时间格式化功能

## 许可证

MIT License

## 作者

Lynn
