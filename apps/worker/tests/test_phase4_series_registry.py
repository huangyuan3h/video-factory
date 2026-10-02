"""Phase 4 extensibility: series registry + dummy series/publisher end-to-end (dry-run only)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.publishers import PUBLISHER_REGISTRY, BasePublisher, get_publisher, register_publisher
from src.services import series_registry as reg


class DummyPublisher(BasePublisher):
    platform_name = "dummy"
    login_url = "https://example.invalid/login"
    upload_url = "https://example.invalid/upload"

    @staticmethod
    def parse_dummy_markdown(text):
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        title = lines[0].lstrip("# ").strip() if lines else ""
        return {"title": title, "body": "\n".join(lines[1:])}

    @staticmethod
    def build_dummy_payload(parsed):
        return {"title": parsed["title"], "body": parsed["body"], "draft": True}

    @staticmethod
    def is_already_published(ep):
        return False

    @staticmethod
    def should_refuse_publish(ep):
        return False, ""

    async def check_login(self):
        return True

    async def upload(self, video_path, title, description=None, tags=None, **kwargs):
        raise NotImplementedError("dummy publisher never uploads (dry-run only)")


@pytest.fixture
def dummy_platform():
    register_publisher("dummy", DummyPublisher)
    reg.register_series(reg.SeriesSpec(name="dummy", content_type="dummy", description="Test-only dummy series"))
    yield
    PUBLISHER_REGISTRY.pop("dummy", None)
    reg._SERIES_REGISTRY.pop("dummy", None)


def _vf():
    import importlib.util
    from importlib.machinery import SourceFileLoader

    path = Path(__file__).resolve().parents[3] / "scripts" / "vf"
    loader = SourceFileLoader("vf_phase4reg", str(path))
    spec = importlib.util.spec_from_loader("vf_phase4reg", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _args(**kw):
    base = dict(ep=None, dir=None, json=True, resume=False, check_drift=False,
                n=None, topic=None, type="indicator", list_types=False,
                manifest=None, approved_script=None, script_only=False,
                resolution="2560x1440", out_dir=None, to=None, privacy="unlisted",
                draft_only=True, force=False, force_reason=None, execute=False,
                dry_run=False, check_funnel=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_builtin_series_registered():
    assert set(reg.list_series()) == {"indicator", "general", "book", "news", "daily_news"}
    assert reg.steps_for("indicator")[0] == "research"
    assert reg.steps_for("indicator")[-1] == "publish"


def test_unknown_series_hint_lists_available():
    with pytest.raises(KeyError, match="Available"):
        reg.get_series("nope-no-such-series")


def test_register_rejects_unknown_steps():
    with pytest.raises(ValueError, match="unknown steps"):
        reg.register_series(reg.SeriesSpec(name="bad", content_type="bad", steps=("research", "teleport")))


def test_series_decorator_registers_builder():
    @reg.series("deco-series", content_type="general", description="decorator test")
    def _builder(args):
        return object(), "deco"

    try:
        assert "deco-series" in reg.list_series()
        assert callable(reg.get_series("deco-series").builder)
    finally:
        reg._SERIES_REGISTRY.pop("deco-series", None)


def test_load_series_configs(tmp_path):
    cfg = tmp_path / "series.d"
    cfg.mkdir()
    (cfg / "novel.json").write_text(json.dumps({"name": "novel", "content_type": "novel", "description": "Future novel series"}), encoding="utf-8")
    n = reg.load_series_configs(cfg)
    try:
        assert n == 1
        assert reg.get_series("novel").content_type == "novel"
    finally:
        reg._SERIES_REGISTRY.pop("novel", None)
    (cfg / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="broken.json"):
        reg.load_series_configs(cfg)
    assert reg.load_series_configs(tmp_path / "does-not-exist") == 0


def test_register_publisher_validates():
    with pytest.raises(ValueError, match="subclass BasePublisher"):
        register_publisher("not-a-publisher", object)
    with pytest.raises(ValueError, match="must not be empty"):
        register_publisher("  ", DummyPublisher)


def test_register_publisher_with_aliases():
    register_publisher("dummy2", DummyPublisher, aliases=("d2",))
    try:
        assert get_publisher("d2").platform_name == "dummy"
        assert "d2" in PUBLISHER_REGISTRY
    finally:
        PUBLISHER_REGISTRY.pop("dummy2", None)
        PUBLISHER_REGISTRY.pop("d2", None)


def test_dummy_series_and_publisher_end_to_end_dry_run(tmp_path, capsys, dummy_platform):
    vf = _vf()
    assert get_publisher("dummy").platform_name == "dummy"
    parsed = DummyPublisher.parse_dummy_markdown("# T\n\n正文。")
    assert parsed["title"] == "T"
    assert DummyPublisher.build_dummy_payload(parsed)["draft"] is True
    # 1. new-ep script-only (writes deterministic task, no network/LLM/TTS).
    out = tmp_path / "dummy90"
    rc = vf.cmd_new_ep(_args(n=90, topic="Dummy dry-run topic", type="dummy", script_only=True, out_dir=out))
    assert rc == 0
    assert (out / "script.json").is_file()
    capsys.readouterr()
    # 2. qa on the fresh task dir must PASS.
    rc = vf.cmd_qa(_args(dir=str(out)))
    assert rc == 0
    capsys.readouterr()
    # 3. publish dry-run to the dummy platform (never executes: execute=False).
    rc = vf.cmd_publish(_args(ep="ep90", to="dummy"))
    assert rc == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    d = json.loads(last)
    assert d["to"] == "dummy" and d["dry_run"] is True
