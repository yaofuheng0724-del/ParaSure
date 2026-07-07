from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright


SUPPORTED_AUTH_CAPABILITIES = {
    "ldap": ("ldap", "LDAP", "LDAP 认证", "LDAP 登录"),
    "radius": ("radius", "RADIUS", "RADIUS 认证"),
    "certificate": ("cert", "certificate", "证书", "证书认证"),
    "password": ("password", "密码", "密码认证"),
    "tfa": ("tfa", "2fa", "双因子", "二次认证", "多因素"),
    "login_restriction": ("登录限制", "登录状态过期", "重复登录", "访问来源限制"),
}
FEDERATED_SSO_TERMS = ("oidc", "openid", "oauth", "cas", "saml", "sso", "单点登录")
GENERIC_AUTH_TERMS = ("认证", "登录", "第三方", "外部认证", "统一认证")
STATIC_EVIDENCE_MARKERS = {
    "LDAP 认证": ("LDAP 认证", "LDAP 登录", "/api/LDAPConfigAPI", "getLdapConfig"),
    "RADIUS 认证": ("RADIUS 认证", "/api/RADIUSConfigV2API", "RadiusAuth", "radiusManagement"),
    "证书认证": ("证书认证", "loginWithCert", "Certificate authentication"),
    "密码认证": ("密码认证", "loginWithPassword", "Password authentication"),
    "双因子认证": ("GlobalTFAConfigAPI", "UserTFAConfigAPI", "tfa_enabled"),
    "用户安全": ("systemUsersConfig", "用户安全", "Login restriction"),
    "第三方接入": ("systemUsersThirdParty", "third-party", "第三方接入"),
    "认证方式列表": ("认证方式是一个列表", "authentication_method", "authMethodRadio"),
}
AUTH_ROUTES = (
    "/system/users/config",
    "/system/users/third-party",
    "/system/users",
    "/profile",
)
SEARCH_SELECTORS = (
    "input[type='search']",
    "input[placeholder*='搜索']",
    "input[aria-label*='搜索']",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Leichi SSO/OIDC/CAS UI evidence read-only.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--cdp-url", default="")
    parser.add_argument("--requirement-id", required=True)
    parser.add_argument("--requirement-text", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--username", default="", help="Optional login username; password must come from env or stdin.")
    parser.add_argument("--password-stdin", action="store_true", help="Read one password line from stdin when env password is absent.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    screenshot = out_dir / "screenshot.png"
    evidence_path = out_dir / "evidence.json"
    excerpt_path = out_dir / "page_excerpt.txt"
    console_logs: list[str] = []
    network_events: list[str] = []
    steps: list[str] = []

    with sync_playwright() as p:
        browser, context = _open_browser_context(p, args, steps)
        page = context.new_page()
        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
        page.on("response", lambda resp: network_events.append(f"{resp.status} {resp.url}"))
        page.goto(args.base_url, wait_until="domcontentloaded", timeout=15000)
        steps.append(f"goto {args.base_url}")
        _wait_networkidle(page)
        steps.append("wait networkidle")
        page_text = page.locator("body").inner_text(timeout=8000)
        page_text = _login_if_needed(page, page_text, args, steps)
        query = _best_query(args.requirement_text)
        if query:
            _try_search(page, query, steps)
            _wait_networkidle(page)
        route_texts = _visit_auth_routes(page, args.base_url, steps)
        static_matches = _collect_static_auth_evidence(page, steps)
        page_text = "\n".join([page.locator("body").inner_text(timeout=8000), *route_texts, *static_matches])
        page.screenshot(path=str(screenshot), full_page=True)
        final_url = page.url
        browser.close()

    keyword_matches, dom_matches, failed_reason = _judge_capability_evidence(args.requirement_text, page_text)
    failed_reason = failed_reason or _login_failure_reason(page_text)
    excerpt_path.write_text(page_text[:2000], encoding="utf-8")
    if console_logs:
        (out_dir / "console.log").write_text("\n".join(console_logs), encoding="utf-8")
    if network_events:
        (out_dir / "network.log").write_text("\n".join(network_events), encoding="utf-8")
    evidence_path.write_text(
        json.dumps(
            {
                "product": "雷池- Web应用防火墙",
                "requirement_id": args.requirement_id,
                "requirement_text": args.requirement_text,
                "final_url": final_url,
                "screenshot_path": str(screenshot),
                "evidence_path": str(evidence_path),
                "page_excerpt": page_text[:1200],
                "keyword_matches": list(keyword_matches),
                "dom_matches": list(dom_matches),
                "failed_reason": failed_reason,
                "network_log_path": str(out_dir / "network.log") if network_events else "",
                "steps": steps,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


def _wait_networkidle(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        page.wait_for_timeout(1000)


def _open_browser_context(p, args: argparse.Namespace, steps: list[str]):
    if args.cdp_url:
        try:
            browser = p.chromium.connect_over_cdp(args.cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context(ignore_https_errors=True)
            steps.append(f"connect_over_cdp {args.cdp_url}")
            return browser, context
        except Exception as exc:  # noqa: BLE001
            steps.append(f"connect_over_cdp failed: {exc}")
    browser = p.chromium.launch(headless=True)
    steps.append("launch headless chromium")
    context = browser.new_context(ignore_https_errors=True, viewport={"width": 1920, "height": 1080})
    return browser, context


def _login_if_needed(page, page_text: str, args: argparse.Namespace, steps: list[str]) -> str:
    if not _login_failure_reason(page_text):
        return page_text
    username, password = _credentials(args)
    if not username or not password:
        steps.append("login skipped: runtime credentials not provided")
        return page_text
    try:
        page.locator("#username").fill(username)
        page.locator("#password").fill(password)
        page.get_by_role("button", name=re.compile("Log On|登录", re.IGNORECASE)).click(timeout=5000)
        steps.append("login with runtime credentials")
        _wait_networkidle(page)
        page.goto(_post_login_url(args.base_url), wait_until="domcontentloaded", timeout=15000)
        steps.append("reload after login")
        _wait_networkidle(page)
        return page.locator("body").inner_text(timeout=8000)
    except Exception as exc:  # noqa: BLE001
        steps.append(f"login failed: {exc}")
        return page_text


def _credentials(args: argparse.Namespace) -> tuple[str, str]:
    username = args.username or os.getenv("PARAMSURE_WEB_USERNAME", "")
    password = os.getenv("PARAMSURE_WEB_PASSWORD", "")
    if not password and args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    return username, password


def _post_login_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/statistic/overview"


def _visit_auth_routes(page, base_url: str, steps: list[str]) -> list[str]:
    route_texts: list[str] = []
    for route in AUTH_ROUTES:
        url = _absolute_url(base_url, route)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=12000)
            steps.append(f"goto readonly auth route {route}")
            _wait_networkidle(page)
            text = page.locator("body").inner_text(timeout=5000)
            if text and not _login_failure_reason(text):
                route_texts.append(f"[{route}]\n{text}")
        except Exception as exc:  # noqa: BLE001
            steps.append(f"auth route skipped {route}: {exc}")
    return route_texts


def _collect_static_auth_evidence(page, steps: list[str]) -> list[str]:
    try:
        script_urls = page.locator("script[src]").evaluate_all("els => els.map(e => e.src)")
    except Exception as exc:  # noqa: BLE001
        steps.append(f"static evidence skipped: {exc}")
        return []

    evidence: list[str] = []
    scanned = 0
    for script_url in script_urls:
        if "/static/js/" not in script_url:
            continue
        scanned += 1
        if scanned > 20:
            steps.append("static evidence stopped: js scan limit reached")
            break
        try:
            response = page.request.get(script_url, timeout=10000)
            if not response.ok:
                continue
            body = response.text()
        except Exception as exc:  # noqa: BLE001
            steps.append(f"static script skipped {script_url}: {exc}")
            continue
        for label, markers in STATIC_EVIDENCE_MARKERS.items():
            if any(marker in body for marker in markers):
                evidence.append(f"前端资源证据: {label}")
        if any(marker in body for markers in STATIC_EVIDENCE_MARKERS.values() for marker in markers):
            steps.append(f"collect static auth evidence {script_url.rsplit('/', 1)[-1]}")
    return list(dict.fromkeys(evidence))


def _absolute_url(base_url: str, route: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", route.lstrip("/"))


def _try_search(page, query: str, steps: list[str]) -> None:
    for selector in SEARCH_SELECTORS:
        try:
            locator = page.locator(selector).first()
            locator.fill(query)
            locator.press("Enter")
            steps.append(f"search {selector} {query}")
            return
        except Exception:
            continue
    steps.append("search skipped: no readonly search input found")


def _best_query(requirement_text: str) -> str:
    lowered = requirement_text.casefold()
    for terms in SUPPORTED_AUTH_CAPABILITIES.values():
        for term in terms:
            if term.casefold() in lowered:
                return term
    for term in FEDERATED_SSO_TERMS:
        if term.casefold() in lowered:
            return term
    if any(term.casefold() in lowered for term in GENERIC_AUTH_TERMS):
        return "认证"
    return ""


def _judge_capability_evidence(requirement_text: str, page_text: str) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    requested_supported = _requested_supported_capabilities(requirement_text)
    requested_federated = _requested_federated_terms(requirement_text)
    available = _available_supported_capabilities(page_text)
    generic_requested = _requests_generic_auth(requirement_text)

    if requested_federated:
        matches = tuple(term for term in requested_federated if term.casefold() in page_text.casefold())
        if not matches:
            return (
                (),
                (),
                "雷池已审计页面和前端资源仅发现密码、证书、LDAP、RADIUS、登录限制等认证能力，未发现 OIDC/CAS/SAML/SSO 的可审计页面证据。",
            )

    if requested_supported:
        matched_capabilities = tuple(capability for capability in requested_supported if capability in available)
    elif generic_requested:
        matched_capabilities = tuple(capability for capability in ("ldap", "radius", "certificate", "password") if capability in available)
    else:
        matched_capabilities = ()

    if not matched_capabilities:
        return (), (), "未定位到与该认证类需求直接对应的雷池只读页面证据。"

    keywords = _capability_keywords(matched_capabilities)
    keyword_matches = _matches(keywords, page_text)
    dom_matches = _context_lines(page_text, keyword_matches)
    if not dom_matches:
        return keyword_matches, (), "仅发现认证关键词，缺少可审计页面上下文。"
    return keyword_matches, dom_matches, ""


def _requested_supported_capabilities(text: str) -> tuple[str, ...]:
    lowered = text.casefold()
    matched: list[str] = []
    for capability, terms in SUPPORTED_AUTH_CAPABILITIES.items():
        if any(term.casefold() in lowered for term in terms):
            matched.append(capability)
    return tuple(dict.fromkeys(matched))


def _requested_federated_terms(text: str) -> tuple[str, ...]:
    lowered = text.casefold()
    return tuple(term for term in FEDERATED_SSO_TERMS if term.casefold() in lowered)


def _requests_generic_auth(text: str) -> bool:
    lowered = text.casefold()
    return any(term.casefold() in lowered for term in GENERIC_AUTH_TERMS)


def _available_supported_capabilities(page_text: str) -> tuple[str, ...]:
    lowered = page_text.casefold()
    matched: list[str] = []
    for capability, terms in SUPPORTED_AUTH_CAPABILITIES.items():
        if any(term.casefold() in lowered for term in terms):
            matched.append(capability)
    return tuple(dict.fromkeys(matched))


def _capability_keywords(capabilities: tuple[str, ...]) -> tuple[str, ...]:
    terms: list[str] = []
    for capability in capabilities:
        terms.extend(SUPPORTED_AUTH_CAPABILITIES[capability])
    return tuple(dict.fromkeys(terms))


def _keywords(text: str) -> tuple[str, ...]:
    terms = []
    terms.extend(re.findall(r"[A-Za-z0-9_+#.-]{2,}", text.casefold()))
    terms.extend(re.findall(r"[\u4e00-\u9fff]{2,}", text))
    return tuple(dict.fromkeys(terms))


def _matches(keywords: tuple[str, ...], page_text: str) -> tuple[str, ...]:
    lowered = page_text.casefold()
    return tuple(keyword for keyword in keywords if keyword and keyword.casefold() in lowered)


def _context_lines(page_text: str, needles: tuple[str, ...]) -> tuple[str, ...]:
    lowered_needles = [needle.casefold() for needle in needles if needle]
    rows: list[str] = []
    for line in page_text.splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        if not clean:
            continue
        lowered = clean.casefold()
        if any(needle in lowered for needle in lowered_needles):
            rows.append(clean[:220])
    return tuple(dict.fromkeys(rows[:8]))


def _login_failure_reason(page_text: str) -> str:
    login_markers = (
        "You are not logged on",
        "Log On",
        "Enter an account",
        "Enter a password",
        "Password",
        "Certificate",
    )
    if any(marker in page_text for marker in login_markers):
        return "当前浏览器未登录雷池控制台，请通过 Chrome CDP 复用已登录会话后重试。"
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
