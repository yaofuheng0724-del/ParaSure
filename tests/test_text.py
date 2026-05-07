from paramsure.text import text_score, tokenize


def test_tokenize_extracts_chinese_ngrams() -> None:
    tokens = tokenize("支持SQL注入、跨站脚本XSS检测")
    assert "sql" in tokens
    assert "xss" in tokens
    assert "注入" in tokens


def test_text_score_prefers_related_content() -> None:
    good, terms = text_score("支持SQL注入检测", "Java常见漏洞检测支持SQL注入和XSS")
    bad, _ = text_score("支持SQL注入检测", "支持资产统计大屏和趋势图")
    assert good > bad
    assert terms
