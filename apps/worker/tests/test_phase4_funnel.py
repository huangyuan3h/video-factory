"""Phase 4 funnel template + checker (pure, no network)."""
from src.services.funnel import (
    DEFAULT_FUNNEL_URL,
    DISCLAIMER,
    PLAYLIST_ID,
    PRESENTER,
    build_description,
    check_description,
    funnel_url,
)


def test_build_description_has_all_parts(monkeypatch):
    monkeypatch.setenv("VF_FUNNEL_URL", "https://example.invalid/karios")
    desc = build_description("测试标题？｜什么指标不赚钱 第26集", "什么指标不赚钱 第26集")
    assert "https://example.invalid/karios" in desc
    assert PLAYLIST_ID in desc
    assert "不构成投资建议" in desc
    assert PRESENTER in desc
    verdict = check_description(desc)
    assert verdict["ok"] is True
    assert verdict["missing"] == []


def test_missing_funnel_url_fails_closed_with_fix(monkeypatch):
    # Tentative default (owner-approved 2026-10-02): env empty still yields default URL.
    monkeypatch.delenv("VF_FUNNEL_URL", raising=False)
    assert funnel_url() == DEFAULT_FUNNEL_URL
    assert DEFAULT_FUNNEL_URL == "https://zhibiao.it-t.xyz/request"
    desc = build_description("T", "什么指标不赚钱 第26集")
    assert DEFAULT_FUNNEL_URL in desc
    verdict = check_description(desc)
    assert verdict["ok"] is True
    assert verdict["missing"] == []


def test_broken_description_lists_all_missing(monkeypatch):
    monkeypatch.delenv("VF_FUNNEL_URL", raising=False)
    verdict = check_description("hello world")
    assert verdict["ok"] is False
    assert set(verdict["missing"]) == {"funnel-link", "playlist", "disclaimer", "presenter"}


def test_disclaimer_constant_matches_publishers():
    assert "不构成投资建议" in DISCLAIMER


def test_funnel_url_prefers_explicit_over_env(monkeypatch):
    monkeypatch.setenv("VF_FUNNEL_URL", "https://env.invalid/funnel")
    assert funnel_url() == "https://env.invalid/funnel"
    assert funnel_url("  https://explicit.invalid/x  ") == "https://explicit.invalid/x"
    monkeypatch.delenv("VF_FUNNEL_URL", raising=False)
    assert funnel_url() == DEFAULT_FUNNEL_URL
