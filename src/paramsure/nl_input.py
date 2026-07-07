from __future__ import annotations

import re

from .models import NaturalLanguageRequirementSet, TenderRequirement


PRODUCT_ALIASES: dict[str, list[str]] = {
    "雷池- Web应用防火墙": ["雷池", "waf", "web应用防火墙", "web 应用防火墙"],
    "慧鉴-智能源代码审计产品": ["慧鉴", "源代码审计", "代码审计"],
    "万象-SOC安全运营平台": ["万象", "soc", "安全运营"],
    "牧云-主机安全产品": ["牧云", "主机安全"],
    "洞鉴-资产风险评估系统": ["洞鉴", "x-ray", "风险评估"],
    "无锋-自动化渗透测试平台": ["无锋", "xblade", "渗透测试"],
    "云图-互联网攻击面管理平台": ["云图", "攻击面"],
    "全悉-全流量威胁检测产品": ["全悉", "全流量"],
    "鉴微-漏洞管理平台": ["鉴微", "漏洞管理"],
    "长亭API安全网关产品": ["api安全网关", "api 安全网关"],
    "长亭终端统一管控与安全检测响应平台(DDR)": ["ddr", "终端统一管控", "终端安全"],
    "码力AISecCoding-智能开发安全一体化平台": ["码力", "aisecoding", "智能开发安全"],
}


def infer_product(text: str, available_products: list[str]) -> str:
    normalized = text.lower()
    for product in available_products:
        if product.lower() in normalized:
            return product
    for product, aliases in PRODUCT_ALIASES.items():
        if product in available_products and any(alias.lower() in normalized for alias in aliases):
            return product
    return ""


def parse_natural_language_requirements(text: str, available_products: list[str]) -> NaturalLanguageRequirementSet:
    product = infer_product(text, available_products)
    requirement_text = _strip_product_hint(text, product)
    parts = _split_requirements(requirement_text)
    requirements = [
        TenderRequirement(requirement_id=str(index), title="", description=part)
        for index, part in enumerate(parts, start=1)
        if part
    ]
    if not requirements and requirement_text.strip():
        requirements = [TenderRequirement(requirement_id="1", title="", description=requirement_text.strip())]
    return NaturalLanguageRequirementSet(product=product, requirements=requirements, source_text=text)


def _strip_product_hint(text: str, product: str) -> str:
    value = text
    if product:
        value = value.replace(product, "")
        for alias in PRODUCT_ALIASES.get(product, []):
            value = re.sub(re.escape(alias), "", value, flags=re.IGNORECASE)
    value = re.sub(r"(这条参数|这个参数|该参数).{0,12}(是否|时候)?支持", "", value)
    value = re.sub(r"(长亭的|长亭|产品|确认|核验|帮我|请)", "", value)
    return value.strip(" ，,。？?：:")


def _split_requirements(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    chunks = re.split(r"[；;\n]|(?:\d+[、.])", normalized)
    cleaned: list[str] = []
    for chunk in chunks:
        value = chunk.strip(" ，,。？?：:")
        if value:
            cleaned.append(value)
    return cleaned
