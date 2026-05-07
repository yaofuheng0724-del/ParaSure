from __future__ import annotations

import math
import re
from collections import Counter


STOPWORDS = {
    "支持",
    "具备",
    "提供",
    "产品",
    "系统",
    "功能",
    "能够",
    "可以",
    "进行",
    "实现",
    "包括",
    "不限于",
    "至少",
    "需要",
    "要求",
    "投标",
    "页面",
    "配置",
}


def normalize_text(text: object) -> str:
    if text is None:
        return ""
    value = str(text)
    value = value.replace("\u3000", " ").replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def clean_marker(text: str) -> str:
    return normalize_text(text).lstrip("★*#-•· ").strip()


def tokenize(text: str) -> list[str]:
    text = clean_marker(text).lower()
    ascii_tokens = re.findall(r"[a-z0-9_+#.-]{2,}", text)
    chinese = re.findall(r"[\u4e00-\u9fff]+", text)
    tokens: list[str] = []
    tokens.extend(ascii_tokens)
    for segment in chinese:
        if len(segment) <= 2:
            tokens.append(segment)
            continue
        for size in (2, 3, 4):
            tokens.extend(segment[i : i + size] for i in range(0, len(segment) - size + 1))
    return [token for token in tokens if token and token not in STOPWORDS]


def top_terms(text: str, limit: int = 12) -> tuple[str, ...]:
    counts = Counter(tokenize(text))
    return tuple(term for term, _ in counts.most_common(limit))


def text_score(query: str, document: str) -> tuple[float, tuple[str, ...]]:
    q_tokens = tokenize(query)
    d_tokens = tokenize(document)
    if not q_tokens or not d_tokens:
        return 0.0, ()

    q_counts = Counter(q_tokens)
    d_counts = Counter(d_tokens)
    shared = set(q_counts) & set(d_counts)
    if not shared:
        return 0.0, ()

    overlap = sum(min(q_counts[t], d_counts[t]) for t in shared)
    q_total = sum(q_counts.values())
    d_total = sum(d_counts.values())
    recall = overlap / max(q_total, 1)
    precision = overlap / max(d_total, 1)
    cosine = overlap / math.sqrt(max(q_total * d_total, 1))
    score = 0.55 * recall + 0.25 * cosine + 0.20 * precision

    exact_bonus = 0.0
    q_norm = clean_marker(query)
    d_norm = clean_marker(document)
    if q_norm and len(q_norm) >= 8 and q_norm in d_norm:
        exact_bonus = 0.25
    return min(score + exact_bonus, 1.0), tuple(sorted(shared, key=lambda t: (-q_counts[t], t))[:12])
