"""Leakfix tests: internal writing notes must never reach published Zhihu body.

Covers 2026-09-27 ep1/ep2 live leaks (备选标题 blockquote, ## 开头： heading)
plus queued ep8/ep11 patterns. All pure, no browser.
"""

import json

import pytest

from src.publishers.zhihu import (
    assert_no_zhihu_meta_leaks,
    extract_zhihu_article_id,
    find_zhihu_meta_leaks,
    is_published_article_html,
    is_published_article_url,
    load_payload,
    parse_zhihu_markdown,
    sanitize_zhihu_markdown,
)


def test_find_ep2_alt_titles_blockquote():
    md = (
        "# KDJ超卖抄底为什么不赚钱？19.9万笔回测告诉你真相\n\n"
        "> 备选标题（发布只用主标题，其余留档）：\n"
        "> 1. J小于0就该抄底吗？\n"
        "> 2. 低位金叉更稳吗？\n\n"
        "正文开始。\n"
    )
    hits = find_zhihu_meta_leaks(md)
    assert len(hits) >= 3
    assert any("备选标题" in h for h in hits)


def test_find_ep1_heading_label():
    md = "# MACD金叉为什么不赚钱？\n\n## 开头：先把“MACD是什么”讲清\n\n正文。\n"
    hits = find_zhihu_meta_leaks(md)
    assert len(hits) == 1
    assert "开头" in hits[0]


def test_find_ep11_working_header_and_video_placeholder():
    md = (
        "# 专栏文章 · ep11 红三兵\n\n"
        "标题（发布用）：红三兵三连阳为什么不赚钱？\n\n"
        "备选标题（保留2个）：\n"
        "1. 三连阳稳步上攻是真的吗？\n"
        "2. 看到三连阳就追进去？\n\n"
        "---\n\n"
        "## 开头：三根阳线摆在面前，你会追吗\n\n"
        "> 【发布时在此嵌入本集视频（由本人手动上传至知乎，放在开头之后）：《第11集》】\n\n"
        "正文。\n"
    )
    hits = find_zhihu_meta_leaks(md)
    assert len(hits) >= 6
    joined = " ".join(hits)
    assert "专栏文章" in joined
    assert "发布用" in joined
    assert "备选标题" in joined


def test_find_todo_shengao_beizhu_brackets():
    assert find_zhihu_meta_leaks("TODO: 重写这段\n\n正文。\n")
    assert find_zhihu_meta_leaks("审稿：数字待核对\n\n正文。\n")
    assert find_zhihu_meta_leaks("备注：配图待补\n\n正文。\n")
    assert find_zhihu_meta_leaks("> 【发布时在此嵌入视频】\n\n正文。\n")
    assert find_zhihu_meta_leaks("## 结尾：总结一下\n\n正文。\n")
    assert find_zhihu_meta_leaks("标题：一个工作标题\n\n正文。\n")


def test_clean_article_has_no_leaks():
    md = (
        "# 5日线上穿20日线为什么不赚钱？\n\n"
        "我是躺平的老黄，先澄清一句。\n\n"
        "## 口径：规则写死了，才敢比\n\n"
        "> 回测口径：信号区间2010-01-01至2026-08-31。\n\n"
        "*图注：这就是成绩单。*\n"
    )
    assert find_zhihu_meta_leaks(md) == []
    assert_no_zhihu_meta_leaks(md) is None


def test_sanitize_ep2_removes_blockquote():
    md = (
        "# T\n\n"
        "> 备选标题（发布只用主标题，其余留档）：\n"
        "> 1. alt1\n"
        "> 2. alt2\n\n"
        "先把成绩单摆在前面。\n"
    )
    cleaned, removed = sanitize_zhihu_markdown(md)
    assert len(removed) == 3
    assert "备选标题" not in cleaned
    assert "先把成绩单摆在前面" in cleaned
    assert find_zhihu_meta_leaks(cleaned) == []


def test_sanitize_ep1_heading_prefix():
    md = "# T\n\n## 开头：先把“MACD是什么”讲清\n\n正文。\n"
    cleaned, removed = sanitize_zhihu_markdown(md)
    assert "## 先把“MACD是什么”讲清" in cleaned
    assert "开头：" not in cleaned
    assert find_zhihu_meta_leaks(cleaned) == []


def test_sanitize_ep11_header_block():
    md = (
        "# 专栏文章 · ep11 红三兵\n\n"
        "标题（发布用）：红三兵三连阳为什么不赚钱？\n\n"
        "备选标题（保留2个）：\n"
        "1. alt1\n"
        "2. alt2\n\n"
        "---\n\n"
        "## 开头：三根阳线摆在面前，你会追吗\n\n"
        "> 【发布时在此嵌入本集视频（由本人手动上传至知乎，放在开头之后）：《第11集》】\n\n"
        "正文开始。\n"
    )
    cleaned, removed = sanitize_zhihu_markdown(md)
    assert "专栏文章" not in cleaned
    assert "发布用" not in cleaned
    assert "备选标题" not in cleaned
    assert "【发布时" not in cleaned
    assert "## 三根阳线摆在面前，你会追吗" in cleaned
    assert "正文开始" in cleaned
    assert find_zhihu_meta_leaks(cleaned) == []


def test_parse_never_emits_meta_blocks():
    md = (
        "# KDJ超卖抄底为什么不赚钱？\n\n"
        "> 备选标题（发布只用主标题，其余留档）：\n"
        "> 1. alt1\n\n"
        "## 开头：一个标签标题\n\n"
        "正文段落。\n"
    )
    parsed = parse_zhihu_markdown(md)
    texts = [str(b.get("text", "")) for b in parsed["blocks"]]
    joined = "\n".join(texts)
    assert "备选标题" not in joined
    assert "开头：" not in joined
    # Fixable heading keeps real text.
    assert any("一个标签标题" in t for t in texts)


def test_gate_raises_on_leaks_tmp(tmp_path):
    (tmp_path / "article.md").write_text(
        "# T\n\n> 备选标题（发布只用主标题，其余留档）：\n> 1. alt\n\n正文。\n",
        encoding="utf-8",
    )
    payload = tmp_path / "publish_payload.json"
    payload.write_text(
        json.dumps({"title": "T", "body_markdown_path": "article.md"}, ensure_ascii=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="meta leaks"):
        load_payload(payload)


def test_gate_passes_on_clean_tmp(tmp_path):
    (tmp_path / "article.md").write_text("# T\n\n正文段落。\n\n## 小节\n\n更多。\n", encoding="utf-8")
    payload = tmp_path / "publish_payload.json"
    payload.write_text(
        json.dumps({"title": "T", "body_markdown_path": "article.md"}, ensure_ascii=False),
        encoding="utf-8",
    )
    data = load_payload(payload)
    assert data["title"] == "T"
    assert len(data["blocks"]) >= 2


def test_published_url_detection():
    assert is_published_article_url("https://zhuanlan.zhihu.com/p/2087634656309015659") is True
    assert is_published_article_url("https://zhuanlan.zhihu.com/p/2087634656309015659/edit") is False
    assert is_published_article_url("https://zhuanlan.zhihu.com/write") is False
    assert is_published_article_url("https://zhuanlan.zhihu.com/p/2087354235574867228/edit") is False
    assert extract_zhihu_article_id("https://zhuanlan.zhihu.com/p/2087634656309015659/edit") == "2087634656309015659"
    assert extract_zhihu_article_id("https://zhuanlan.zhihu.com/write") is None


def test_published_html_detection():
    published = '<div class="Post-Main"><h1 class="Post-Title">t</h1><div>编辑于 2026-09-27</div></div>'
    assert is_published_article_html(published) is True
    editor = '<div class="ProseMirror" contenteditable="true"><p>草稿</p></div><button>保存草稿</button>'
    assert is_published_article_html(editor) is False
    assert is_published_article_html("") is False
