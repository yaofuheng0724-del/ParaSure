from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from .agent import AgentRuntime
from .bootstrap import auto_index_product_params
from .config import AgentConfig, DEFAULT_CONFIG_PATH
from .excel_io import iter_excel_files, load_product_parameters
from .llm import OpenAICompatibleClient
from .memory import SessionMemory
from .models import Verdict, VerificationConfig
from .pipeline import ParaSurePipeline
from .store import ParameterStore
from .workflow import V2Workflow


DEFAULT_DB = Path(".paramsure/paramsure.db")
DEFAULT_ARTIFACTS = Path(".paramsure/artifacts")


def print_line(message: str = "") -> None:
    print(message, flush=True)


def read_prompt(prompt_text: str) -> str:
    try:
        from prompt_toolkit import prompt
    except Exception:
        return input(prompt_text)
    return prompt(prompt_text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paramsure",
        description="ParaSure - 长亭产品招标参数符合性核验 Agent",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="本地知识库路径")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Agent配置文件路径")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="导入长亭产品参数Excel到本地知识库")
    ingest.add_argument("path", type=Path, help="Excel文件或包含Excel的目录")
    ingest.add_argument("--reset", action="store_true", help="导入前清空旧知识库")

    products = sub.add_parser("products", help="列出知识库中的产品")
    products.set_defaults(func=products_command)

    check = sub.add_parser("check", help="核验客户招标参数Excel并导出符合性矩阵")
    check.add_argument("tender", type=Path, help="客户招标参数Excel")
    check.add_argument("--product", required=True, help="指定核验产品名，需与 products 输出一致")
    check.add_argument("--out", type=Path, default=Path("paramsure-result.xlsx"), help="输出Excel路径")
    check.add_argument("--material-threshold", type=float, default=0.24, help="资料直接满足阈值")
    check.add_argument("--uncertain-threshold", type=float, default=0.15, help="弱相关候选阈值")
    check.add_argument("--web-url", default="", help="产品Web演示环境地址，配置后启用Web验证")
    check.add_argument("--cdp-url", default="", help="本地已登录Chrome的CDP地址，例如 http://127.0.0.1:9222")
    check.add_argument("--browser-state", type=Path, default=None, help="Playwright storage_state JSON")
    check.add_argument("--api-base-url", default="", help="只读API基础地址")
    check.add_argument("--api-token", default="", help="只读API Token")

    chat = sub.add_parser("chat", help="进入Claude Code风格的LLM Agent交互")
    chat.add_argument("--session-id", default="", help="指定会话ID，默认自动生成")
    chat.add_argument("--no-llm", action="store_true", help="只进入命令模式，不连接LLM")

    config = sub.add_parser("config", help="查看或修改LLM配置")
    config.add_argument("action", choices=["show", "set"], help="配置动作")
    config.add_argument("key", nargs="?", help="配置项: base_url/api_key/model/temperature/max_tool_rounds/ssl.ca_file")
    config.add_argument("value", nargs="?", help="配置值")
    return parser


def ingest_command(args: argparse.Namespace) -> int:
    store = ParameterStore(args.db)
    if args.reset:
        store.reset()
        print_line("已清空旧知识库。")
    total = 0
    files = list(iter_excel_files(args.path))
    if not files:
        print_line(f"未找到可导入的 .xlsx 文件: {args.path}")
        return 1
    for file in files:
        parameters = load_product_parameters(file)
        count = store.add_parameters(parameters)
        total += count
        print_line(f"导入 {file.name}: {count} 条参数")
    print_line(f"完成导入，共 {total} 条参数。知识库: {args.db}")
    return 0


def _auto_index(store: ParameterStore, config: AgentConfig) -> None:
    status = auto_index_product_params(store, config.product_params_path())
    if status.get("missing"):
        print_line(f"内置参数目录不存在: {status['params_dir']}")
        return
    if status["indexed"] > 0:
        print_line(f"已自动索引参数目录: {status['indexed']} 个文件, {status['parameter_count']} 条参数")


def products_command(args: argparse.Namespace) -> int:
    config = AgentConfig.load(args.config)
    store = ParameterStore(args.db)
    _auto_index(store, config)
    rows = store.products()
    if not rows:
        print_line("知识库为空，请先运行 ingest。")
        return 1
    for product, count in rows:
        print_line(f"- {product}: {count} 条")
    return 0


def check_command(args: argparse.Namespace) -> int:
    config = AgentConfig.load(args.config)
    store = ParameterStore(args.db)
    _auto_index(store, config)
    verification = VerificationConfig(
        enabled=bool(args.web_url),
        cdp_url=args.cdp_url,
        browser_state=args.browser_state,
        base_url=args.web_url,
        api_base_url=args.api_base_url,
        api_token=args.api_token,
        playbook_dir=str(config.web_playbooks_path()),
    )
    agent = ParaSurePipeline(store, DEFAULT_ARTIFACTS)
    print_line("ParaSure 正在核验...")
    print_line(f"- 客户参数: {args.tender}")
    print_line(f"- 指定产品: {args.product}")
    print_line(f"- 输出文件: {args.out}")
    results = agent.evaluate_excel(
        args.tender,
        args.product,
        args.out,
        verification=verification,
        material_threshold=args.material_threshold,
        uncertain_threshold=args.uncertain_threshold,
    )
    counts = {verdict: 0 for verdict in Verdict}
    for result in results:
        counts[result.verdict] = counts.get(result.verdict, 0) + 1
    print_line("核验完成。")
    for verdict in Verdict:
        print_line(f"- {verdict.value}: {counts.get(verdict, 0)}")
    print_line(f"结果已写入: {args.out}")
    return 0


def chat_command(args: argparse.Namespace) -> int:
    print_line("ParaSureV2 Agent 交互模式")
    print_line("可用斜杠命令: /config show, /config set <key> <value>, /ingest <目录或Excel> [--reset], /products, /check <Excel> --product <产品名> --out <结果.xlsx>, /exit")
    print_line("自然语言示例: 用户登录支持对接SSO、至少支持CAS/OIDC之一，这条参数雷池是否支持")
    parser = build_parser()
    runtime: AgentRuntime | None = None
    config = AgentConfig.load(args.config)
    store = ParameterStore(args.db)
    _auto_index(store, config)
    workflow = V2Workflow(store, config, DEFAULT_ARTIFACTS)
    if not args.no_llm:
        try:
            llm = OpenAICompatibleClient(config)
            memory = SessionMemory(session_id=args.session_id) if args.session_id else SessionMemory()
            runtime = AgentRuntime(
                llm=llm,
                store=store,
                memory=memory,
                artifact_dir=DEFAULT_ARTIFACTS,
                config=config,
                max_tool_rounds=config.max_tool_rounds,
            )
            print_line(f"LLM已连接: model={config.model}, base_url={config.base_url}")
            print_line(f"会话记忆: {memory.path}")
        except Exception as exc:  # noqa: BLE001
            print_line(f"LLM Agent 未就绪: {exc}")
            print_line("你仍可使用斜杠命令；配置完成后重新进入 chat。")
    while True:
        try:
            raw = read_prompt("paramsure> ").strip()
        except (EOFError, KeyboardInterrupt):
            print_line()
            return 0
        if not raw:
            continue
        if raw in {"/exit", "exit", "quit"}:
            return 0
        if raw.startswith("/"):
            raw = raw[1:]
            try:
                nested = parser.parse_args(["--db", str(args.db), "--config", str(args.config), *shlex.split(raw)])
                rc = dispatch(nested)
                if rc:
                    print_line(f"命令返回非零状态: {rc}")
            except SystemExit:
                continue
            except Exception as exc:  # noqa: BLE001
                print_line(f"执行失败: {exc}")
            continue
        try:
            handled = _handle_v2_natural_language(raw, workflow)
            if handled:
                continue
            if runtime is None:
                print_line("LLM Agent 未连接。请先运行 /config set api_key <key>，必要时设置 /config set base_url <url>。")
                continue
            answer = runtime.run_turn(raw)
            print_line(answer)
        except Exception as exc:  # noqa: BLE001
            print_line(f"Agent执行失败: {exc}")


def _handle_v2_natural_language(raw: str, workflow: V2Workflow) -> bool:
    report = workflow.assess_natural_language(raw)
    if report.needs_clarification:
        return False
    if not report.decisions:
        return False
    print_line(workflow.render_assessment(report))
    prompt = workflow.prompt_for_verification(report)
    if not prompt:
        return True
    print_line(prompt)
    choice = read_prompt("paramsure verify> ").strip().lower()
    if choice not in {"y", "yes", "是", "确认"}:
        print_line("已跳过 Web/API 二次验证。")
        return True
    web_url = read_prompt("请输入本次产品演示环境 URL: ").strip()
    if not web_url:
        print_line("未输入演示环境 URL，已取消二次验证。")
        return True
    results = workflow.verify_pending(report, web_url)
    print_line("第二阶段 Web/API 验证结果：")
    for result in results:
        print_line(f"- [{result.initial_verdict.value}] {result.requirement.text} | {result.reason}")
    return True


def config_command(args: argparse.Namespace) -> int:
    config = AgentConfig.load(args.config)
    if args.action == "show":
        masked = "*" * 8 if config.api_key else ""
        print_line(f"base_url: {config.base_url}")
        print_line(f"api_key: {masked}")
        print_line(f"model: {config.model}")
        print_line(f"temperature: {config.temperature}")
        print_line(f"max_tool_rounds: {config.max_tool_rounds}")
        print_line(f"product_params_dir: {config.product_params_dir}")
        print_line(f"web_playbooks_dir: {config.web_playbooks_dir}")
        print_line(f"chrome.cdp_url: {config.cdp_url()}")
        print_line(f"ssl.ca_file: {config.ssl_ca_file()}")
        print_line(f"path: {args.config}")
        return 0
    if not args.key or args.value is None:
        print_line("用法: paramsure config set <key> <value>")
        return 1
    value: object = args.value
    if args.key == "temperature":
        value = float(args.value)
    if args.key == "max_tool_rounds":
        value = int(args.value)
    if "." in args.key:
        head, tail = args.key.split(".", 1)
        if head not in AgentConfig.__dataclass_fields__:
            print_line(f"未知配置项: {args.key}")
            return 1
        container = getattr(config, head)
        if not isinstance(container, dict):
            print_line(f"配置项不支持嵌套写入: {head}")
            return 1
        container[tail] = value
    else:
        if args.key not in AgentConfig.__dataclass_fields__:
            print_line(f"未知配置项: {args.key}")
            return 1
        setattr(config, args.key, value)
    config.save(args.config)
    print_line(f"已更新配置: {args.key}")
    return 0


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "ingest":
        return ingest_command(args)
    if args.command == "products":
        return products_command(args)
    if args.command == "check":
        return check_command(args)
    if args.command == "chat":
        return chat_command(args)
    if args.command == "config":
        return config_command(args)
    raise ValueError(f"未知命令: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args)
    except Exception as exc:  # noqa: BLE001
        print_line(f"错误: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
