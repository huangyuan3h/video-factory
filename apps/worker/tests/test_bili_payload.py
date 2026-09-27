"""Pure-logic tests for the Bilibili publisher payload builder (no browser)."""

import json

from src.publishers.bili import (
    AI_SENTENCE_SHORT,
    BILI_TAG_LIMIT,
    BILI_TID,
    FINANCE_DISCLAIMER,
    PRESENTER_NAME,
    build_bili_description,
    build_bili_payload_from_yt,
    build_published_record,
    classify_login_state,
    contains_external_link,
    get_published_path,
    is_already_published,
    is_captcha_html,
    is_logged_in_state,
    is_risk_html,
    load_published_record,
    normalize_bili_tags,
    save_published_record,
    should_refuse_publish,
    strip_external_links,
    validate_bili_payload,
    validate_bili_title,
)
from src.publishers.bili_publish import build_parser, resolve_headless, resolve_mode


def test_strip_external_links():
    assert strip_external_links("看这里 https://example.com/a 更多") == "看这里  更多"
    assert contains_external_link("见 http://x.y/z") is True
    assert contains_external_link("纯中文描述，无链接") is False


def test_normalize_bili_tags_limit_and_dedupe():
    assert normalize_bili_tags([" MACD ", "MACD", "量化"]) == ["MACD", "量化"]
    many = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l"]
    assert normalize_bili_tags(many) == many[:BILI_TAG_LIMIT]
    assert normalize_bili_tags([]) == []
    assert normalize_bili_tags(["#MACD"]) == ["MACD"]


def test_validate_bili_title():
    assert validate_bili_title("MACD金叉，真的能赚钱吗？") == []
    assert validate_bili_title("") != []
    assert validate_bili_title("x" * 81) != []


def test_build_bili_description_has_disclaimer_ai_branding_no_links():
    desc = build_bili_description(
        "MACD金叉买、死叉卖，到底能不能赚钱？\n\n详见 https://www.youtube.com/watch?v=xxx\n\n主讲：躺平的老黄",
        ai_declared_on_panel=False,
    )
    assert FINANCE_DISCLAIMER in desc
    assert AI_SENTENCE_SHORT in desc
    assert PRESENTER_NAME in desc
    assert contains_external_link(desc) is False
    assert "youtube.com" not in desc


def test_build_bili_description_panel_on_still_has_ai():
    desc = build_bili_description("回测正文", ai_declared_on_panel=True)
    assert "AI" in desc
    assert FINANCE_DISCLAIMER in desc


def test_build_bili_payload_from_yt_ep1():
    yt = {
        "title": "MACD金叉，真的能赚钱吗？｜什么指标不赚钱 第1集",
        "description": "MACD金叉买、死叉卖，到底能不能赚钱？\n\n历史回测，不构成投资建议。\n\n主讲：躺平的老黄",
        "tags": ["MACD", "技术分析", "A股", "股票", "回测", "量化回测", "散户"],
    }
    payload = build_bili_payload_from_yt(
        yt,
        video_path="/tmp/output.mp4",
        cover_path="/tmp/cover_1920x1080.png",
    )
    assert payload["tid"] == BILI_TID == 207
    assert payload["copyright"] == 1
    assert payload["partition"] == "知识-财经商业"
    assert len(payload["title"]) <= 80
    assert len(payload["tags"]) <= BILI_TAG_LIMIT
    assert FINANCE_DISCLAIMER in payload["description"]
    assert AI_SENTENCE_SHORT in payload["description"]
    assert PRESENTER_NAME in payload["description"]
    assert contains_external_link(payload["description"]) is False
    assert validate_bili_payload(payload) == []


def test_validate_bili_payload_catches_links_and_missing():
    bad = {
        "title": "t",
        "description": "见 https://evil.example.com",
        "tags": [],
        "tid": 999,
        "copyright": 2,
        "video_path": "",
        "cover_path": "",
    }
    issues = validate_bili_payload(bad)
    assert any("external links" in i for i in issues)
    assert any("no tags" in i for i in issues)
    assert any("tid" in i for i in issues)
    assert any("copyright" in i for i in issues)


def test_is_captcha_and_risk():
    assert is_captcha_html("请完成验证码拖动滑块") is True
    assert is_captcha_html("正常投稿页面，填写标题") is False
    assert is_captcha_html("") is False
    assert is_risk_html("鉴权失败，请联系账号组 -663") is True
    assert is_risk_html("正常页面") is False


def test_classify_login_state():
    assert classify_login_state("https://passport.bilibili.com/login", "扫码登录") == "logged_out"
    html_in = '<div class="header-avatar"><img src="face.jpg"></div> <span class="user-name">躺平的老黄</span> <a>退出</a>'
    assert classify_login_state("https://member.bilibili.com/platform/home", html_in) == "logged_in"
    assert is_logged_in_state("https://member.bilibili.com/platform/home", html_in) is True
    # Bare 投稿 + avatar placeholder without username must NOT count as in.
    html_out = '<div class="header-avatar-unlogin-wrap">登录</div> <a>投稿</a>'
    assert classify_login_state("https://www.bilibili.com/", html_out) == "logged_out"
    assert is_logged_in_state("https://www.bilibili.com/", html_out) is False
    assert classify_login_state("https://member.bilibili.com/", "请完成验证码") == "verification"


def test_published_idempotency_missing(tmp_path):
    payload = tmp_path / "publish_payload.json"
    payload.write_text("{}", encoding="utf-8")
    assert get_published_path(payload) == tmp_path / "published.json"
    assert load_published_record(payload) is None
    already, _ = is_already_published(payload)
    assert already is False
    refuse, _ = should_refuse_publish(payload, force=False)
    assert refuse is False


def test_published_idempotency_roundtrip(tmp_path):
    payload = tmp_path / "publish_payload.json"
    payload.write_text("{}", encoding="utf-8")
    record = build_published_record(
        "https://www.bilibili.com/video/BV1Test1234",
        screenshots=["a.png"],
        title="t",
        bvid="BV1Test1234",
        status="审核中",
    )
    assert record["url"].startswith("http")
    assert record["bvid"].startswith("BV")
    assert "published_at" in record
    out = save_published_record(payload, record)
    assert out.exists()
    loaded = load_published_record(payload)
    assert loaded["bvid"] == "BV1Test1234"
    already, rec = is_already_published(payload)
    assert already is True
    refuse, _ = should_refuse_publish(payload, force=False)
    assert refuse is True
    refuse_forced, _ = should_refuse_publish(payload, force=True)
    assert refuse_forced is False


def test_cli_resolve_mode_and_headless():
    p = build_parser()
    a = p.parse_args(["--payload", "/tmp/x.json", "--draft-only"])
    assert resolve_mode(a) == "draft"
    a = p.parse_args(["--payload", "/tmp/x.json", "--mode", "publish"])
    assert resolve_mode(a) == "publish"
    a = p.parse_args(["--payload", "/tmp/x.json", "--mode", "publish", "--draft-only"])
    assert resolve_mode(a) == "draft"
    a = p.parse_args(["--payload", "/tmp/x.json"])
    assert resolve_headless(a) is True
    a = p.parse_args(["--payload", "/tmp/x.json", "--headed"])
    assert resolve_headless(a) is False
    a = p.parse_args(["--payload", "/tmp/x.json", "--headed", "--headless"])
    assert resolve_headless(a) is True


def test_cli_flags_exist():
    p = build_parser()
    a = p.parse_args(["--payload", "/tmp/x.json", "--no-open", "--force"])
    assert a.no_open is True and a.force is True
    # 10-minute default login timeout per smoke task.
    assert a.login_timeout_s == 600
