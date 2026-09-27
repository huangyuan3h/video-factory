"""Pure-logic tests for the Bilibili publisher payload builder (no browser)."""

import json

from src.publishers.bili import (
    AI_SENTENCE_SHORT,
    BILI_PARTITION_NAME,
    BILI_TAG_LIMIT,
    BILI_TID,
    COVER_ACCEPT_HINTS,
    COVER_DONE_TEXTS,
    COVER_MODAL_TEXTS,
    DECL_AI_OPTION,
    DECL_SELF_OPTION,
    DESC_PLACEHOLDER,
    DESC_SELECTORS,
    FINANCE_DISCLAIMER,
    MORE_SETTINGS_TEXT,
    PARTITION_MAIN_WANT,
    PARTITION_SUB_WANT,
    PRESENTER_NAME,
    TAG_INPUT_SELECTORS,
    TITLE_SELECTORS,
    VIDEO_INPUT_SELECTORS,
    BiliPublisher,
    build_bili_description,
    build_bili_payload_from_yt,
    build_published_record,
    classify_login_state,
    contains_external_link,
    get_published_path,
    is_already_published,
    is_captcha_element,
    is_captcha_html,
    is_logged_in_state,
    is_risk_html,
    is_verification_url,
    load_published_record,
    normalize_bili_tags,
    save_published_record,
    should_refuse_publish,
    strip_external_links,
    validate_bili_payload,
    validate_bili_title,
    visible_text_has_captcha,
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


# --- verification false-positive fixes (2026-09-27 diag: logged-in upload
# pages BLOCKED as `verification` by bare "-663"/CSS-class substrings) ---


def test_false_positive_svg_663_coords_not_verification():
    # Real diag_upload1.html hit: <g transform="translate(-663.000000, ...)".
    svg_html = (
        '<html><body><svg><g id="x" transform="translate(-663.000000, -343.000000)">'
        "</g></svg><div>点击上传或将视频拖拽到此区域</div></body></html>"
    )
    assert is_captcha_html(svg_html) is False
    assert is_risk_html(svg_html) is False
    assert visible_text_has_captcha("translate(-663.000000, -343.000000)") is False


def test_false_positive_css_adapt_class_not_verification():
    # Real diag: <body class="risk-captcha-adapt-pc risk-captcha-adapt"> +
    # <style>.risk-captcha-adapt-pc>.geetest_panel{...}</style> on EVERY
    # normal member page, logged in or not.
    css_html = (
        "<html><head><style>"
        ".risk-captcha-adapt-pc>.geetest_panel>.geetest_panel_ghost{transform:scale(4)}"
        "</style></head>"
        '<body class="risk-captcha-adapt-pc risk-captcha-adapt">'
        '<div class="avatar"><img src="face.jpg"></div>'
        "<div>点击上传或将视频拖拽到此区域</div></body></html>"
    )
    assert is_captcha_html(css_html) is False
    assert is_risk_html(css_html) is False
    assert classify_login_state("https://member.bilibili.com/platform/home", css_html) == "logged_in"


def test_false_positive_body_adapt_element_not_captcha():
    # <body> itself matches [class*="captcha"]/[class*="risk"] and reports
    # is_visible=True with a full-viewport bbox on normal pages -> must not
    # count. Only non-root visible widgets count.
    assert is_captcha_element("BODY", True, {"x": 0, "y": 0, "width": 1280, "height": 860}) is False
    assert is_captcha_element("HTML", True, {"x": 0, "y": 0, "width": 1280, "height": 860}) is False
    assert is_captcha_element("DIV", True, {"x": 400, "y": 200, "width": 300, "height": 200}) is True
    assert is_captcha_element("IFRAME", True, {"x": 400, "y": 200, "width": 300, "height": 200}) is True
    assert is_captcha_element("DIV", False, {"x": 400, "y": 200, "width": 300, "height": 200}) is False
    assert is_captcha_element("DIV", True, None) is False
    assert is_captcha_element("DIV", True, {"x": 0, "y": 0, "width": 0, "height": 0}) is False


def test_finance_disclaimer_risk_word_not_captcha():
    # Our own description ("投资有风险，入市需谨慎") lands in innerText after
    # fill; generic "风险"/"滑动"/"异常" must not flag verify_form.
    assert visible_text_has_captcha(FINANCE_DISCLAIMER) is False
    assert visible_text_has_captcha("投资有风险，入市需谨慎。") is False
    assert visible_text_has_captcha("滑动查看更多") is False
    assert BiliPublisher.detect_captcha_sync_text(BiliPublisher, FINANCE_DISCLAIMER) is False


def test_real_verification_still_detected():
    assert is_captcha_html("请完成验证码拖动滑块") is True
    assert is_risk_html("鉴权失败，请联系账号组 -663") is True
    assert visible_text_has_captcha("安全验证，请拖动滑块完成验证") is True
    assert visible_text_has_captcha("风控拦截，请稍后再试") is True
    assert visible_text_has_captcha("-663 鉴权失败") is True
    assert classify_login_state("https://member.bilibili.com/", "请完成验证码") == "verification"
    assert is_verification_url("https://risk.bilibili.com/captcha?x=1") is True
    assert is_verification_url("https://member.bilibili.com/platform/upload/video/frame") is False
    assert is_verification_url("https://passport.bilibili.com/login") is False


def test_diag_saved_html_not_verification():
    """Regression from .opencode-runs/bili/diag_upload0.html (logged-in page
    wrongly classified as verification before the fix). Skips when the diag
    files are absent (e.g. CI without the profile)."""
    import pathlib

    smoke = pathlib.Path.home() / "Projects" / "video-factory" / ".opencode-runs" / "bili"
    candidates = [smoke / "diag_upload0.html", smoke / "diag_home.html"]
    found = [p for p in candidates if p.exists()]
    if not found:
        import pytest

        pytest.skip("diag html absent (needs local bili profile run)")
    for p in found:
        html = p.read_text(encoding="utf-8")
        assert is_captcha_html(html) is False, p.name
        assert is_risk_html(html) is False, p.name
        state = classify_login_state("https://member.bilibili.com/platform/home", html)
        assert state == "logged_in", (p.name, state)


# --- ep1 draft form fix (2026-09-27): cover P2 bug, Quill desc, tag clear,
# partition 知识/财经商业, 自制+AI, strict verify_form ---


def test_video_input_selectors_strict_no_generic():
    # The P2 bug: generic input[type=file] matched the video input first and
    # the cover PNG was set on it. Video selectors must be video-only.
    assert VIDEO_INPUT_SELECTORS, "video selectors missing"
    for sel in VIDEO_INPUT_SELECTORS:
        assert sel != 'input[type="file"]', "generic file input must not be a video selector"
        assert any(k in sel for k in (".mp4", "video", "flv")), sel


def test_cover_must_go_via_dialog_not_file_input():
    import src.publishers.bili as bili_mod

    # No generic cover file-input fallback may exist (it caused P2).
    assert not hasattr(bili_mod, "COVER_INPUT_SELECTORS"), "COVER_INPUT_SELECTORS must stay removed (cover via dialog only)"
    assert "image/png" in COVER_ACCEPT_HINTS
    assert "添加封面" in COVER_MODAL_TEXTS
    assert "上传封面" in COVER_MODAL_TEXTS
    assert "完成" in COVER_DONE_TEXTS


def test_desc_selectors_quill_first():
    assert DESC_SELECTORS[0].startswith(".ql-editor"), DESC_SELECTORS
    assert "填写更全面" in DESC_SELECTORS[0]
    assert DESC_PLACEHOLDER.startswith("填写更全面")


def test_title_and_tag_inputs_exact_placeholders():
    assert TITLE_SELECTORS[0] == 'input[placeholder="请输入稿件标题"]'
    assert TAG_INPUT_SELECTORS[0] == 'input[placeholder="按回车键Enter创建标签"]'


def test_partition_constants_knowledge_finance():
    assert BILI_TID == 207
    assert BILI_PARTITION_NAME == "知识-财经商业"
    assert PARTITION_MAIN_WANT == "知识"
    assert PARTITION_SUB_WANT == "财经商业"
    assert MORE_SETTINGS_TEXT == "更多设置"


def test_creation_declaration_constants():
    assert DECL_AI_OPTION == "含AI生成内容"
    assert "自制" in DECL_SELF_OPTION


def test_ep1_payload_tags_exact():
    want = ["MACD", "MACD金叉", "技术指标", "技术分析", "A股", "回测", "躺平的老黄", "金叉死叉", "股票入门", "量化"]
    assert normalize_bili_tags(want) == want


def test_verify_form_signature_strict():
    import inspect

    sig = inspect.signature(BiliPublisher.verify_form)
    params = set(sig.parameters)
    assert "expected_description" in params
    assert "expected_tags" in params
    assert "expected_cover" in params


def test_draft_flow_helpers_exist():
    for name in (
        "dismiss_unsubmitted_interstitial",
        "dismiss_batch_popup",
        "clear_tags",
        "read_tags",
        "read_description",
        "read_cover_state",
        "read_parts",
        "read_partition_main",
        "set_creation_declaration",
        "expand_more_settings",
    ):
        assert hasattr(BiliPublisher, name), name
