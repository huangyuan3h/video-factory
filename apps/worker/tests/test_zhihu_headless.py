"""Pure-logic tests for the headless-by-default Zhihu publisher (no browser)."""

import json

from src.publishers.zhihu import (
    build_published_record,
    classify_login_state,
    get_published_path,
    is_already_published,
    is_captcha_html,
    is_headless_blocked_state,
    is_logged_in_state,
    load_payload,
    load_published_record,
    save_published_record,
    should_refuse_publish,
)
from src.publishers.zhihu_publish import build_parser, resolve_headless, resolve_mode


def test_is_captcha_html():
    assert is_captcha_html("请完成验证码拖动滑块") is True
    assert is_captcha_html("安全验证，请在浏览器里手动完成") is True
    assert is_captcha_html("<div>正常文章内容，欢迎阅读</div>") is False
    assert is_captcha_html("") is False


def test_classify_login_state_logged_in():
    html = '<img class="Avatar" src="x"> <a href="/people/foo">me</a> 提问'
    assert classify_login_state("https://www.zhihu.com/", html) == "logged_in"
    assert is_logged_in_state("https://www.zhihu.com/creator", html) is True


def test_classify_login_state_logged_out():
    assert classify_login_state("https://www.zhihu.com/signin", "<div>登录</div>") == "logged_out"
    html = '<div class="SignFlow">登录</div>'
    assert classify_login_state("https://www.zhihu.com/", html) == "logged_out"


def test_classify_login_state_verification():
    html = "请完成安全验证拖动滑块"
    assert classify_login_state("https://www.zhihu.com/", html) == "verification"
    assert is_logged_in_state("https://www.zhihu.com/", html) is False


def test_classify_login_state_unknown():
    assert classify_login_state("https://www.zhihu.com/", "<div>hello</div>") == "unknown"


def test_is_headless_blocked_blank_and_403():
    assert is_headless_blocked_state("https://www.zhihu.com/", "", "") is True
    assert is_headless_blocked_state("https://www.zhihu.com/", "x" * 10, "") is True
    blocked_html = '{"code":40362,"message":"您当前请求存在异常，暂时限制本次访问"}' + "x" * 400
    assert is_headless_blocked_state("https://zhuanlan.zhihu.com/p/1", blocked_html, "t") is True
    assert (
        is_headless_blocked_state("https://www.zhihu.com/", "请完成验证码" + "x" * 400, "t") is True
    )


def test_is_headless_blocked_normal_page_not_blocked():
    html = '<img class="Avatar">' + "正常内容" * 200
    assert is_headless_blocked_state("https://www.zhihu.com/creator", html, "创作中心") is False


def test_published_idempotency_missing(tmp_path):
    payload = tmp_path / "publish_payload.json"
    payload.write_text("{}", encoding="utf-8")
    assert get_published_path(payload) == tmp_path / "published.json"
    assert load_published_record(payload) is None
    already, rec = is_already_published(payload)
    assert already is False
    refuse, _ = should_refuse_publish(payload, force=False)
    assert refuse is False


def test_published_idempotency_roundtrip(tmp_path):
    payload = tmp_path / "publish_payload.json"
    payload.write_text("{}", encoding="utf-8")
    record = build_published_record(
        "https://zhuanlan.zhihu.com/p/123",
        screenshots=["a.png"],
        title="t",
        draft_url="https://zhuanlan.zhihu.com/p/123/edit",
    )
    assert record["url"].startswith("http")
    assert "published_at" in record
    out = save_published_record(payload, record)
    assert out.exists()
    loaded = load_published_record(payload)
    assert loaded["url"] == "https://zhuanlan.zhihu.com/p/123"
    already, rec = is_already_published(payload)
    assert already is True and rec["url"].endswith("/p/123")
    refuse, _ = should_refuse_publish(payload, force=False)
    assert refuse is True
    refuse_forced, _ = should_refuse_publish(payload, force=True)
    assert refuse_forced is False


def test_published_idempotency_bad_url_not_published(tmp_path):
    payload = tmp_path / "publish_payload.json"
    payload.write_text("{}", encoding="utf-8")
    save_published_record(payload, {"url": "", "published_at": "x"})
    already, _ = is_already_published(payload)
    assert already is False


def test_load_payload_tmp(tmp_path):
    (tmp_path / "article.md").write_text(
        "# 标题T\n\n正文段落一。\n\n## 小节\n\n> 引用一句\n", encoding="utf-8"
    )
    payload = tmp_path / "publish_payload.json"
    payload.write_text(
        json.dumps(
            {
                "title": "标题T",
                "body_markdown_path": "article.md",
                "images_in_order": [],
                "topics": ["均线"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    data = load_payload(payload)
    assert data["title"] == "标题T"
    assert len(data["blocks"]) >= 3
    assert data["topics"] == ["均线"]


def test_cli_resolve_mode_and_headless():
    p = build_parser()
    a = p.parse_args(["--payload", "/tmp/x.json", "--draft-only"])
    assert resolve_mode(a) == "draft"
    a = p.parse_args(["--payload", "/tmp/x.json", "--mode", "publish"])
    assert resolve_mode(a) == "publish"
    # --draft-only overrides --mode publish
    a = p.parse_args(["--payload", "/tmp/x.json", "--mode", "publish", "--draft-only"])
    assert resolve_mode(a) == "draft"

    a = p.parse_args(["--payload", "/tmp/x.json"])
    assert resolve_headless(a) is True  # headless by default
    a = p.parse_args(["--payload", "/tmp/x.json", "--headed"])
    assert resolve_headless(a) is False
    a = p.parse_args(["--payload", "/tmp/x.json", "--headed", "--headless"])
    assert resolve_headless(a) is True


def test_cli_flags_exist():
    p = build_parser()
    a = p.parse_args(["--payload", "/tmp/x.json", "--no-open", "--force"])
    assert a.no_open is True and a.force is True
