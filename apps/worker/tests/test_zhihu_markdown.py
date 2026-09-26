"""Unit tests for the Zhihu Markdown-to-editor conversion (pure, no browser)."""

from src.publishers.zhihu import count_text_blocks, load_payload, parse_inline, parse_zhihu_markdown


def test_parse_inline_bold():
    spans = parse_inline("胜率44.9%，**平均每笔亏0.18%**，组合年化")
    assert spans == [
        {"text": "胜率44.9%，", "bold": False},
        {"text": "平均每笔亏0.18%", "bold": True},
        {"text": "，组合年化", "bold": False},
    ]


def test_parse_inline_unmatched_stars_kept():
    spans = parse_inline("a ** b")
    assert "".join(s["text"] for s in spans) == "a ** b"


def test_parse_ep9_article_structure():
    md = (
        "# 5日线上穿20日线为什么不赚钱？19.6万笔回测告诉你真相\n"
        "\n"
        "我是躺平的老黄，先澄清一句。\n"
        "\n"
        "答案先放这里：**一共196,640笔，胜率44.9%**。\n"
        "\n"
        "![01_结论卡](images/01_conclusion_card.png)\n"
        "*图注：这就是19.6万笔的平均成绩单。*\n"
        "\n"
        "## 口径：规则写死了，才敢比\n"
        "\n"
        "> 回测口径：信号区间2010-01-01至2026-08-31。\n"
        "\n"
        "解释一下那个很扎眼的-34.5%。\n"
        "\n"
        "---\n"
        "\n"
        "【素材与授权】本文图表均为自研回测图表。\n"
    )
    parsed = parse_zhihu_markdown(md)
    assert parsed["title"] == "5日线上穿20日线为什么不赚钱？19.6万笔回测告诉你真相"
    kinds = [b["kind"] for b in parsed["blocks"]]
    assert kinds == ["paragraph", "paragraph", "image", "heading", "quote", "paragraph", "divider", "paragraph"]
    img = parsed["blocks"][2]
    assert img["src"] == "images/01_conclusion_card.png"
    assert img["caption"] == "图注：这就是19.6万笔的平均成绩单。"
    bold_para = parsed["blocks"][1]
    assert any(s["bold"] and "196,640" in s["text"] for s in bold_para["spans"])
    assert count_text_blocks(parsed["blocks"]) == 6


def test_load_real_ep9_payload(tmp_path=None):
    import os

    payload = os.path.expanduser("~/Projects/karios-series-output/zhihu/ep9_ma5_20_golden_cross/publish_payload.json")
    if not os.path.exists(payload):
        import pytest

        pytest.skip("ep9 payload not present on this machine")
    data = load_payload(payload)
    assert "5日线" in data["title"]
    assert len(data["blocks"]) >= 15
    assert sum(1 for b in data["blocks"] if b["kind"] == "image") == 7
    assert len(data["topics"]) >= 3
    assert data["cover_image"] and os.path.exists(data["cover_image"])
    for img in data["images_in_order"]:
        assert os.path.exists(img), img
