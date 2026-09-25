"""Help output for scripts/tts_gap_probe.py (argparse % escaping)."""

import importlib.util
from pathlib import Path


def _load_module():
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "tts_gap_probe.py"
    spec = importlib.util.spec_from_file_location("tts_gap_probe", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_parser_help_escapes_percent():
    module = _load_module()
    help_text = module.build_parser().format_help()
    assert "+2%" in help_text
