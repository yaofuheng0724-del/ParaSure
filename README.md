# ParaSure

ParaSure 是一个用于确认长亭产品参数是否满足客户招标参数的命令行 AI Agent。

它采用 Harness Engineering 思路实现：LLM 负责规划、工具选择、观察整合和复核结论；产品参数知识库、Web/API 只读验证、Excel 导出作为 Agent 工具运行；会话记忆保存工具轨迹和关键结论。

## 当前能力

- 导入长亭全产品招标参数 Excel，自动识别不同表头结构。
- 将产品参数保存到本地 SQLite 知识库。
- 通过 OpenAI 兼容 API 接入 LLM，支持自定义 `base_url`、`api_key`、`model`。
- `chat` 模式下像 Claude Code 一样对话，LLM 可调用工具完成参数核验任务。
- 输出符合性矩阵，包含结论、证据来源、证据摘要、证据位置、风险备注和建议应答口径。
- 提供只读 Web/API 验证工具层；Web 验证依赖可选的 `playwright`。
- 会话记忆持久化到 `.paramsure/sessions/*.jsonl`。

## 安装

```bash
cd /Users/yaofuheng/chaitin/Develop/Paramsure/ParaSure
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

配置 LLM：

```bash
paramsure config set api_key "<your-key>"
paramsure config set base_url "https://api.openai.com/v1"
paramsure config set model "gpt-4.1-mini"
```

如需 Web 验证：

```bash
pip install -e '.[web]'
playwright install chromium
```

## 快速开始

导入外层目录中的产品参数：

```bash
paramsure ingest /Users/yaofuheng/chaitin/Develop/Paramsure --reset
```

查看可用产品名：

```bash
paramsure products
```

直接运行确定性核验工具链：

```bash
paramsure check 客户招标参数.xlsx \
  --product "慧鉴-智能源代码审计产品" \
  --out result.xlsx
```

进入 Claude Code 风格 Agent 对话：

```bash
paramsure chat
```

交互模式下可使用斜杠命令：

```text
/ingest /Users/yaofuheng/chaitin/Develop/Paramsure --reset
/products
/check 客户招标参数.xlsx --product 慧鉴-智能源代码审计产品 --out result.xlsx
/exit
```

也可以直接自然语言驱动 Agent：

```text
帮我核验 ./客户参数.xlsx，产品选 慧鉴-智能源代码审计产品，输出到 ./result.xlsx
先列一下当前知识库里有哪些产品
```

## Agent 架构

- `LLM Runtime`: OpenAI 兼容 chat completions，负责 plan/act/observe/evaluate。
- `Memory`: 会话轨迹、工具观察、最终结论写入 `.paramsure/sessions/`。
- `Tools`: 产品列表、Excel 解析、参数检索、只读 Web/API 验证、Excel 导出。
- `Deterministic Pipeline`: 保留为 fallback 工具，适合一键批量跑矩阵。

## Web/API 验证

默认流程只使用产品参数库。若资料证据不足，可配置只读验证：

```bash
paramsure check 客户招标参数.xlsx \
  --product "雷池- Web应用防火墙" \
  --web-url "http://127.0.0.1:9443" \
  --out result.xlsx
```

复用本地已登录 Chrome：

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/paramsure-chrome

paramsure check 客户招标参数.xlsx \
  --product "雷池- Web应用防火墙" \
  --web-url "http://127.0.0.1:9443" \
  --cdp-url "http://127.0.0.1:9222" \
  --out result.xlsx
```

API Token 可选：

```bash
paramsure check 客户招标参数.xlsx \
  --product "万象-SOC安全运营平台" \
  --api-base-url "http://127.0.0.1:3000/api/v1/health" \
  --api-token "$TOKEN" \
  --out result.xlsx
```

## 设计边界

- 第一版只稳定支持 Excel 输入。
- 每次由用户指定产品，不自动跨全产品做最终判断。
- Web/API 工具默认只读，不执行新增、删除、修改配置。
- 当前知识记忆底座是 SQLite + 本地检索；后续可升级为向量索引或混合 RAG。
