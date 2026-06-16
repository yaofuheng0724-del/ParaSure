from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover read-only DOM evidence from Leichi Web UI.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--cdp-url", default="")
    parser.add_argument("--requirement-id", default="discovery")
    parser.add_argument("--requirement-text", default="DOM discovery")
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    console_logs: list[str] = []
    screenshot = out_dir / "screenshot.png"
    discovery_path = out_dir / "dom_discovery.json"
    excerpt_path = out_dir / "page_excerpt.txt"
    evidence_path = out_dir / "evidence.json"

    with sync_playwright() as p:
        if args.cdp_url:
            browser = p.chromium.connect_over_cdp(args.cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
        else:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(ignore_https_errors=True, viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
        page.goto(args.base_url, wait_until="domcontentloaded", timeout=15000)
        _wait_networkidle(page)
        body_text = page.locator("body").inner_text(timeout=8000)
        page.screenshot(path=str(screenshot), full_page=True)
        discovery = {
            "url": page.url,
            "buttons": _collect_elements(page, "button"),
            "links": _collect_elements(page, "a[href]"),
            "inputs": _collect_inputs(page),
            "console": console_logs,
        }
        discovery_path.write_text(json.dumps(discovery, ensure_ascii=False, indent=2), encoding="utf-8")
        excerpt_path.write_text(body_text[:2000], encoding="utf-8")
        evidence_path.write_text(
            json.dumps(
                {
                    "product": "雷池- Web应用防火墙",
                    "requirement_id": args.requirement_id,
                    "requirement_text": args.requirement_text,
                    "final_url": page.url,
                    "screenshot_path": str(screenshot),
                    "evidence_path": str(evidence_path),
                    "page_excerpt": body_text[:1200],
                    "keyword_matches": [],
                    "dom_matches": [],
                    "steps": [f"goto {args.base_url}", "wait networkidle", "capture dom discovery"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()
    if console_logs:
        (out_dir / "console.log").write_text("\n".join(console_logs), encoding="utf-8")
    return 0


def _wait_networkidle(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        page.wait_for_timeout(1000)


def _collect_elements(page, selector: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for element in page.locator(selector).all()[:80]:
        try:
            if not element.is_visible():
                continue
            rows.append(
                {
                    "text": element.inner_text(timeout=1000).strip()[:160],
                    "href": element.get_attribute("href") or "",
                    "aria_label": element.get_attribute("aria-label") or "",
                }
            )
        except Exception:
            continue
    return rows


def _collect_inputs(page) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for element in page.locator("input, textarea, select").all()[:80]:
        try:
            rows.append(
                {
                    "name": element.get_attribute("name") or "",
                    "id": element.get_attribute("id") or "",
                    "type": element.get_attribute("type") or "",
                    "placeholder": element.get_attribute("placeholder") or "",
                    "aria_label": element.get_attribute("aria-label") or "",
                }
            )
        except Exception:
            continue
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
