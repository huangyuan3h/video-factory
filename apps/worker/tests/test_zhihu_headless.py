"""Pure-logic tests for the headless-by-default Zhihu publisher (no browser)."""

import json

from src.publishers.zhihu import (
    SELF_MADE_ENDING,
    ai_after_reload_blocks_publish,
    build_disclaimer_ending,
    build_published_record,
    classify_login_state,
    get_published_path,
    is_already_published,
    is_captcha_html,
    is_final_image_src,
    is_headless_blocked_state,
    is_logged_in_state,
    is_upload_done_src,
    load_payload,
    load_published_record,
    normalize_topics,
    save_published_record,
    select_cover_image,
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


def test_self_made_ending_matches_owner_text():
    assert SELF_MADE_ENDING == (
        "本文图表均为自研回测结果，历史数据仅供参考；文案由 AI 辅助生成。"
        "本内容为投资者教育，不构成投资建议，过往业绩不代表未来表现。"
        "投资有风险，入市需谨慎。"
    )
    assert build_disclaimer_ending() == SELF_MADE_ENDING
    assert build_disclaimer_ending(has_video=False, has_third_party=False) == SELF_MADE_ENDING


def test_disclaimer_video_only_when_attached():
    no_video = build_disclaimer_ending(has_video=False)
    assert "视频" not in no_video
    with_video = build_disclaimer_ending(has_video=True)
    assert "视频" in with_video
    assert "不构成投资建议" in with_video


def test_disclaimer_third_party_only_when_used():
    plain = build_disclaimer_ending(has_third_party=False)
    assert "素材与授权" not in plain
    third = build_disclaimer_ending(has_third_party=True, third_party_note="Pexels 图已获授权")
    assert "素材与授权" in third and "Pexels" in third
    # Merged AI: only one AI mention sentence, no duplicate headers.
    assert third.count("AI 辅助生成") == 1
    assert plain.count("AI 辅助生成") == 1


def test_normalize_topics_limit_and_dedupe():
    assert normalize_topics([" 均线 ", "均线", "量化交易"]) == ["均线", "量化交易"]
    many = ["a", "b", "c", "d", "e"]
    assert normalize_topics(many) == ["a", "b", "c"]
    assert normalize_topics([]) == []


def test_is_final_image_src():
    assert is_final_image_src("https://pic1.zhimg.com/v2-abc_1440w.jpg") is True
    assert is_final_image_src("https://picx.zhimg.com/80/v2-abc_720w.png?source=x") is True
    # pic-private is upload-done (safe to save) but NOT final (pre-reload).
    assert is_final_image_src("https://pic-private.zhihu.com/v2-abc.png?source=x") is False
    assert is_final_image_src("blob:https://zhuanlan.zhihu.com/abc") is False
    assert is_final_image_src("data:image/png;base64,xxx") is False
    assert is_final_image_src("") is False


def test_is_upload_done_src():
    assert is_upload_done_src("https://pic-private.zhihu.com/v2-abc.png?source=x") is True
    assert is_upload_done_src("https://pic1.zhimg.com/v2-abc_1440w.jpg") is True
    assert is_upload_done_src("blob:https://zhuanlan.zhihu.com/abc") is False
    assert is_upload_done_src("") is False


def test_select_cover_image_prefers_payload():
    assert select_cover_image(["a.png", "b.png"], "cover.png") == "cover.png"
    assert select_cover_image(["a.png", "b.png"], None) == "a.png"
    assert select_cover_image([], None) is None


def test_ai_after_reload_blocks_publish_quirk():
    # Set before save but lost on reload -> advisory, must NOT block (fix2 ep9 proof).
    assert ai_after_reload_blocks_publish("无声明", True) is False
    assert ai_after_reload_blocks_publish("", True) is False
    # Never set -> must block.
    assert ai_after_reload_blocks_publish("无声明", False) is True
    assert ai_after_reload_blocks_publish("", False) is True
    # Badge present -> never blocks.
    assert ai_after_reload_blocks_publish("包含 AI 辅助创作", True) is False
    assert ai_after_reload_blocks_publish("包含 AI 辅助创作", False) is False
