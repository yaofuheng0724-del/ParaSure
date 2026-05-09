# ParaSureV2

ParaSureV2 是一个用于确认长亭产品参数是否满足客户招标参数的命令行 AI Agent。

它采用 Harness Engineering 思路实现：LLM 负责规划、工具选择、观察整合和复核结论；产品参数知识库、Web/API 只读验证、Excel 导出作为 Agent 工具运行；会话记忆保存工具轨迹和关键结论。

## 当前能力

- 导入长亭全产品招标参数 Excel，自动识别不同表头结构。
- 将内置产品参数目录自动索引到本地 SQLite 知识库。
- 通过 OpenAI 兼容 API 接入 LLM，支持自定义 `base_url`、`api_key`、`model`。
- `chat` 模式下像 Claude Code 一样对话，LLM 可调用工具完成参数核验任务。
- 支持少量参数的自然语言输入，不强制要求 Excel。
- 对资料不足的参数，会先列出待二次验证清单，再请求用户授权。
- 输出符合性矩阵，包含结论、证据来源、证据摘要、证据位置、风险备注和建议应答口径。
- 提供只读 Web/API 验证工具层；Web 验证依赖可选的 `playwright`。
- 会话记忆持久化到 `.paramsure/sessions/*.jsonl`。
- 配置文件支持直接编辑 `.paramsure/config.json`。

## 安装

```bash
cd /path/to/ParaSure
./paramsure config show
```

`venv` 和 `.venv` 是 Python 虚拟环境机制。当前版本已经提供仓库内启动脚本 `./paramsure`：

- 第一次运行会自动创建 `.venv`。
- 第一次运行会自动执行 `pip install -e .` 安装基础依赖，例如 `openpyxl`。
- 后续运行会复用 `.venv`。

Linux 服务器需要先具备 Python 3.10+、`python3-venv`，并且首次安装依赖时可以访问 Python 包源。Ubuntu/Debian 可先安装：

```bash
apt install python3 python3-venv
```

如果自动安装依赖失败，也可以手动执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

第一次运行会自动生成 `.paramsure/config.json`。你可以直接编辑这个文件，或者用命令写入。

配置 LLM：

```bash
./paramsure config set api_key "<your-key>"
./paramsure config set base_url "https://api.openai.com/v1"
./paramsure config set model "gpt-4.1-mini"
```

如需 Web 验证：

```bash
.venv/bin/python -m pip install -e '.[web]'
.venv/bin/python -m playwright install chromium
```

## 快速开始

直接查看当前配置：

```bash
./paramsure config show
```

查看可用产品名：

```bash
./paramsure products
```

直接运行确定性核验工具链：

```bash
./paramsure check 客户招标参数.xlsx \
  --product "慧鉴-智能源代码审计产品" \
  --out result.xlsx
```

进入 Claude Code 风格 Agent 对话：

```bash
./paramsure chat
```

交互模式下可使用斜杠命令：

```text
/products
/check 客户招标参数.xlsx --product 慧鉴-智能源代码审计产品 --out result.xlsx
/exit
```

也可以直接自然语言驱动 Agent：

```text
用户登录支持对接SSO、至少支持CAS、OIDC协议的一种，这条参数长亭的雷池web应用防火墙是否支持
帮我核验 ./客户参数.xlsx，产品选 慧鉴-智能源代码审计产品，输出到 ./result.xlsx
先列一下当前知识库里有哪些产品
```

少量参数自然语言输入会走 V2 二阶段流程：

1. Agent 只加载目标产品的上下文包，例如只加载雷池参数。
2. Agent 基于产品招标参数给出第一阶段结论。
3. 如果资料不足，Agent 会列出建议 Web/API 二次验证的条目。
4. 你确认 `y/N` 后，再输入本次准确的产品演示环境 URL。
5. Agent 复用本地已登录 Chrome 做只读验证。

## Agent 架构

- `LLM Runtime`: OpenAI 兼容 chat completions，负责 plan/act/observe/evaluate。
- `Memory`: 会话轨迹、工具观察、最终结论写入 `.paramsure/sessions/`。
- `Tools`: 自然语言需求解析、产品级上下文包、Excel 解析、参数检索、只读 Web/API 验证、Excel 导出。
- `Deterministic Pipeline`: 保留为 fallback 工具，适合一键批量跑矩阵。

## 内置产品参数

当前仓库已经内置产品参数目录：

```text
data/product_params/
```

Agent 启动时会自动检测这个目录中的 Excel 文件，并在首次运行或文件变更时自动重新索引。

这意味着：

- 你不需要在每次使用前手动导入参数。
- 未来产品招标参数更新时，只需要替换或新增 `data/product_params/*.xlsx`。
- 如果你仍然想手动导入其他目录，也可以继续使用 `ingest` 命令。

## Web/API 验证

默认流程只使用产品参数库。若资料证据不足，可配置只读验证：

```bash
./paramsure check 客户招标参数.xlsx \
  --product "雷池- Web应用防火墙" \
  --web-url "http://127.0.0.1:9443" \
  --out result.xlsx
```

推荐通过配置文件写入本地已登录 Chrome 的 CDP 地址：

```bash
./paramsure config set chrome.cdp_url "http://127.0.0.1:9222"
```

产品演示环境 URL 不要求固定配置。V2 会在你确认执行第二阶段 Web/API 验证之后，再要求你输入本次准确的 URL。

API Token 可选：

```bash
./paramsure check 客户招标参数.xlsx \
  --product "万象-SOC安全运营平台" \
  --api-base-url "http://127.0.0.1:3000/api/v1/health" \
  --api-token "$TOKEN" \
  --out result.xlsx
```

在 Agent 对话中，你可以直接自然语言触发：

```text
用本地已登录 Chrome 去雷池演示环境确认这个参数是否满足
去慧鉴的演示环境页面里查一下有没有这个功能，并截图留证
```

## 设计边界

- V2 支持 Excel 输入和少量自然语言参数输入。
- 每次由用户指定产品，不自动跨全产品做最终判断。
- Web/API 工具默认只读，不执行新增、删除、修改配置。
- LLM 上下文采用产品级渐进式披露：核验雷池时只加载雷池产品上下文，不加载其他产品参数全文。
