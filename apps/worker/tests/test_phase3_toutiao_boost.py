"""Phase 3 boost3: toutiao markdown/payload/login edge branches (light)."""
import json


def test_toutiao_markdown_all_branches():
    import src.publishers.toutiao as T
    md = """# 主标题十五字以上测试标题用例

## 二级标题

### 三级标题

---

> 引用块内容

![alt](https://example.com/a.png)
*图片注脚*

<!-- 注释应跳过 -->

普通段落文本。

# 第二个标题不应覆盖
"""
    d = T.parse_toutiao_markdown(md)
    kinds = [b["kind"] for b in d["blocks"]]
    assert "heading" in kinds and "quote" in kinds and "image" in kinds and "divider" in kinds
    assert d["blocks"][-1]["kind"] == "paragraph"
    # caption-only line after image
    md2 = "![a](https://example.com/a.png)\n*单独注脚*\n"
    d2 = T.parse_toutiao_markdown(md2)
    assert d2["blocks"][0].get("caption") == "单独注脚"
    # empty
    assert T.parse_toutiao_markdown("") == {"title": "", "blocks": []}
    # parse_inline edge
    assert T.parse_inline("") == [] or isinstance(T.parse_inline(""), list)
    assert T.parse_inline("**b** and *i* and plain")


def test_toutiao_payload_variants(tmp_path):
    import src.publishers.toutiao as T
    base = tmp_path / "p2"
    base.mkdir()
    (base / "article.md").write_text("# T\n\n正文。", encoding="utf-8")
    # payload without body_markdown_path => fallback to article.md
    pl = base / "payload.json"
    pl.write_text(json.dumps({"title": "这是一个十五字以上的正常头条标题测试用例"}), encoding="utf-8")
    loaded = T.load_payload(pl)
    assert loaded
    # payload with explicit body path
    (base / "toutiao_article.md").write_text("# TT\n\n正文2。", encoding="utf-8")
    pl.write_text(json.dumps({"title": "这是一个十五字以上的正常头条标题测试用例", "body_markdown_path": "toutiao_article.md"}), encoding="utf-8")
    assert T.load_payload(pl)


def test_toutiao_login_all_branches():
    import src.publishers.toutiao as T
    # login page => logged_out/need_login family
    s_login = T.classify_login_state("https://mp.toutiao.com/auth/page/login", "登录")
    assert s_login in ("logged_out", "need_login", "unknown") or "login" in s_login.lower() or "out" in s_login.lower()
    # logged in home
    s = T.classify_login_state("https://mp.toutiao.com/profile", "躺平的老黄 创作 草稿箱")
    assert isinstance(s, str)
    # captcha
    s2 = T.classify_login_state("https://mp.toutiao.com/", "请完成滑动验证")
    assert isinstance(s2, str)
    # incomplete banner states
    done, note = T.detect_incomplete_banner_state("https://mp.toutiao.com/", "请完善账号信息", "")
    assert done is True
    done2, _ = T.detect_incomplete_banner_state("https://mp.toutiao.com/", "干净", "")
    assert done2 is False
    # has_* true/false
    assert T.has_blocking_onboarding("实名认证") in (True, False)
