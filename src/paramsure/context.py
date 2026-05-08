from __future__ import annotations

from collections import Counter

from .models import ProductContext, ProductParameter


def build_product_context(product: str, parameters: list[ProductParameter], sample_limit: int = 30) -> ProductContext:
    modules = [param.module for param in parameters if param.module]
    features = [param.feature or param.description[:50] for param in parameters if param.feature or param.description]
    module_counts = Counter(modules)
    top_modules = [name for name, _ in module_counts.most_common(20)]
    sample_features = list(dict.fromkeys(features))[:sample_limit]
    summary = (
        f"{product} 当前知识库包含 {len(parameters)} 条参数；"
        f"主要模块包括：{', '.join(top_modules[:12]) or '未识别模块'}。"
    )
    return ProductContext(
        product=product,
        parameter_count=len(parameters),
        modules=top_modules,
        sample_features=sample_features,
        summary=summary,
    )
