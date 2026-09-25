"""Sentence-pause insertion between TTS sentences (task-S).

Real short mp3s are generated with ffmpeg in ``tmp_path``; the pure planning
helpers are tested without audio and the codec failure path is mocked.
"""

import array
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.core.subtitle_gen import SubtitleGenerator
from src.core.task_logger import TaskLogger
from src.core.tts import pauses
from src.core.tts.speech_runs import detect_speech_runs
from src.services import video_service as vs

FFMPEG_AVAILABLE = subprocess.run(
    ["ffmpeg", "-version"], capture_output=True
).returncode == 0


def _make_silence_mp3(path: Path, seconds: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=mono:sample_rate=24000",
            "-t",
            str(seconds),
            "-q:a",
            "9",
            str(path),
        ],
        check=True,
    )


def _make_tone_gap_mp3(path: Path, tone_s: float = 0.4, silence_s: float = 0.6) -> None:
    """tone - silence - tone mp3 (mono 24k) with a controlled natural gap."""
    inputs = [
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:sample_rate=24000:duration={tone_s}",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=channel_layout=mono:sample_rate=24000:duration={silence_s}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=660:sample_rate=24000:duration={tone_s}",
    ]
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            *inputs,
            "-filter_complex",
            "[0:a][1:a][2:a]concat=n=3:v=0:a=1[a]",
            "-map",
            "[a]",
            "-ar",
            "24000",
            "-ac",
            "1",
            "-q:a",
            "4",
            str(path),
        ],
        check=True,
    )


def _make_tones_mp3(path: Path, tone_s: float = 0.4) -> None:
    """Two back-to-back tones with no silence between them."""
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=24000:duration={tone_s}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=660:sample_rate=24000:duration={tone_s}",
            "-filter_complex",
            "[0:a][1:a]concat=n=2:v=0:a=1[a]",
            "-map",
            "[a]",
            "-ar",
            "24000",
            "-ac",
            "1",
            "-q:a",
            "4",
            str(path),
        ],
        check=True,
    )


def _measured_gap(path: Path) -> float:
    runs = detect_speech_runs(path)
    assert len(runs) == 2, runs
    return runs[1][0] - runs[0][1]


def _two_sentence_boundaries(speech_s: float = 0.4, silence_s: float = 0.6) -> list[dict]:
    total = speech_s + silence_s
    return [
        {"offset": 0.0, "duration": total, "text": "第一句。"},
        {"offset": total, "duration": speech_s, "text": "第二句。"},
    ]


def _duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


# --------------------------------------------------------------------------- #
# Pure planning helpers
# --------------------------------------------------------------------------- #


def test_plan_cuts_uses_gap_midpoint():
    boundaries = [
        {"offset": 0.0, "duration": 1.0},
        {"offset": 2.0, "duration": 1.0},
        {"offset": 4.0, "duration": 1.0},
    ]
    assert pauses.plan_cuts(boundaries, 0.4) == [1.5, 3.5]


def test_plan_cuts_overlap_uses_next_start():
    boundaries = [
        {"offset": 0.0, "duration": 1.0},
        {"offset": 0.5, "duration": 1.0},
    ]
    assert pauses.plan_cuts(boundaries, 0.4) == [0.5]


def test_plan_cuts_single_boundary_is_empty():
    assert pauses.plan_cuts([{"offset": 0.0, "duration": 1.0}], 0.4) == []


def test_shift_boundaries_advances_by_index_times_pause():
    boundaries = [
        {"offset": 0.0, "duration": 1.0, "text": "a"},
        {"offset": 1.0, "duration": 1.0, "text": "b"},
        {"offset": 2.0, "duration": 1.0, "text": "c"},
    ]
    shifted = pauses.shift_boundaries(boundaries, 0.4)
    assert [b["offset"] for b in shifted] == [0.0, 1.4, 2.8]
    assert [b["text"] for b in shifted] == ["a", "b", "c"]
    assert [b["duration"] for b in shifted] == [1.0, 1.0, 1.0]


# --------------------------------------------------------------------------- #
# apply_sentence_pauses
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg not installed")
def test_apply_sentence_pauses_grows_duration_and_shifts(tmp_path):
    audio = tmp_path / "seg.mp3"
    _make_silence_mp3(audio, 1.0)
    boundaries = [
        {"offset": 0.0, "duration": 0.5, "text": "第一句。"},
        {"offset": 0.5, "duration": 0.5, "text": "第二句。"},
    ]

    result = pauses.apply_sentence_pauses(audio, boundaries, 0.4)

    assert result is not None
    new_duration, shifted = result
    assert abs(new_duration - 1.4) < 0.15
    assert abs(_duration(audio) - 1.4) < 0.15
    assert [b["offset"] for b in shifted] == [0.0, 0.9]


def test_apply_sentence_pauses_noop_for_single_boundary(tmp_path):
    assert pauses.apply_sentence_pauses(tmp_path / "x.mp3", [{"offset": 0.0}], 0.4) is None
    assert pauses.apply_sentence_pauses(tmp_path / "x.mp3", [], 0.4) is None


def test_apply_sentence_pauses_failure_keeps_original(tmp_path):
    audio = tmp_path / "seg.mp3"
    audio.write_bytes(b"not-audio")
    boundaries = [
        {"offset": 0.0, "duration": 0.5},
        {"offset": 0.5, "duration": 0.5},
    ]

    with patch.object(pauses, "_decode_to_pcm", side_effect=RuntimeError("boom")):
        assert pauses.apply_sentence_pauses(audio, boundaries, 0.4) is None


# --------------------------------------------------------------------------- #
# Target-gap mode
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg not installed")
def test_target_gap_tops_up_short_natural_silence(tmp_path):
    audio = tmp_path / "topup.mp3"
    _make_tone_gap_mp3(audio, tone_s=0.4, silence_s=0.6)
    boundaries = _two_sentence_boundaries(0.4, 0.6)

    result = pauses.apply_sentence_pauses(audio, boundaries, 0.0, target_gap_seconds=0.75)

    assert result is not None
    new_duration, shifted = result
    assert abs(_measured_gap(audio) - 0.75) < 0.04
    assert abs(new_duration - 1.55) < 0.1
    assert shifted[0]["offset"] == 0.0
    assert abs(shifted[1]["offset"] - 1.15) < 0.03


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg not installed")
def test_target_gap_trims_long_natural_silence(tmp_path):
    audio = tmp_path / "trim.mp3"
    _make_tone_gap_mp3(audio, tone_s=0.4, silence_s=1.0)
    boundaries = _two_sentence_boundaries(0.4, 1.0)

    result = pauses.apply_sentence_pauses(audio, boundaries, 0.0, target_gap_seconds=0.75)

    assert result is not None
    new_duration, shifted = result
    assert abs(_measured_gap(audio) - 0.75) < 0.04
    assert abs(new_duration - 1.55) < 0.1
    assert abs(shifted[1]["offset"] - 1.15) < 0.03


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg not installed")
def test_target_gap_trims_long_silence_without_cutting_speech(tmp_path):
    audio = tmp_path / "trim-long.mp3"
    _make_tone_gap_mp3(audio, tone_s=0.5, silence_s=2.0)
    boundaries = _two_sentence_boundaries(0.5, 2.0)

    result = pauses.apply_sentence_pauses(audio, boundaries, 0.0, target_gap_seconds=0.75)

    assert result is not None
    _new_duration, shifted = result
    runs = detect_speech_runs(audio)
    assert len(runs) == 2, runs
    # Existing silence (2.0s) is trimmed to 0.75s, but |delta| (1.25s) exceeds
    # half the run (1.0s), so a naive middle-anchored cut would eat the tail tone.
    assert abs((runs[1][0] - runs[0][1]) - 0.75) < 0.04
    assert abs((runs[0][1] - runs[0][0]) - 0.5) < 0.04
    assert abs((runs[1][1] - runs[1][0]) - 0.5) < 0.04
    assert abs(shifted[1]["offset"] - 1.25) < 0.03


def test_apply_target_gaps_centred_trim_preserves_speech():
    sample_rate = pauses.DEFAULT_SAMPLE_RATE
    tone = int(round(0.5 * sample_rate))
    silence = int(round(2.0 * sample_rate))
    samples = array.array("h", [1000] * tone + [0] * silence + [-1000] * tone)
    pcm = samples.tobytes()
    nonzero_before = sum(1 for value in samples if value != 0)

    boundaries = [
        {"offset": 0.0, "duration": 2.5},
        {"offset": 2.5, "duration": 0.5},
    ]

    spliced, shifted = pauses._apply_target_gaps(pcm, boundaries, [1.5], sample_rate, 0.75)

    out = array.array("h")
    out.frombytes(spliced)
    assert sum(1 for value in out if value != 0) == nonzero_before
    assert len(out) == len(samples) - int(round(1.25 * sample_rate))
    assert shifted[1]["offset"] == pytest.approx(1.25, abs=1e-9)


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg not installed")
def test_target_gap_without_silent_run_leaves_cut(tmp_path):
    audio = tmp_path / "tones.mp3"
    _make_tones_mp3(audio, tone_s=0.4)
    boundaries = [
        {"offset": 0.0, "duration": 0.4, "text": "第一句。"},
        {"offset": 0.4, "duration": 0.4, "text": "第二句。"},
    ]

    result = pauses.apply_sentence_pauses(audio, boundaries, 0.0, target_gap_seconds=0.75)

    assert result is not None
    _new_duration, shifted = result
    assert [b["offset"] for b in shifted] == [0.0, 0.4]


def test_target_gap_noop_for_single_boundary(tmp_path):
    assert (
        pauses.apply_sentence_pauses(
            tmp_path / "x.mp3", [{"offset": 0.0}], 0.0, target_gap_seconds=0.75
        )
        is None
    )


def test_target_gap_failure_keeps_original(tmp_path):
    audio = tmp_path / "seg.mp3"
    audio.write_bytes(b"not-audio")
    boundaries = [
        {"offset": 0.0, "duration": 0.5},
        {"offset": 0.5, "duration": 0.5},
    ]

    with patch.object(pauses, "_decode_to_pcm", side_effect=RuntimeError("boom")):
        assert (
            pauses.apply_sentence_pauses(audio, boundaries, 0.0, target_gap_seconds=0.75)
            is None
        )


def test_sync_sentence_pauses_without_gap_uses_additive(tmp_path):
    audio = tmp_path / "seg.mp3"
    _make_silence_mp3(audio, 1.0)
    boundaries = [
        {"offset": 0.0, "duration": 0.5, "text": "第一句。"},
        {"offset": 0.5, "duration": 0.5, "text": "第二句。"},
    ]

    result = pauses.sync_sentence_pauses(audio, boundaries, pause_seconds=0.4)

    assert result is not None
    new_duration, shifted = result
    assert abs(new_duration - 1.4) < 0.15
    assert shifted[1]["offset"] == 0.9


# --------------------------------------------------------------------------- #
# Integration through _synthesize_audio
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg not installed")
@pytest.mark.asyncio
async def test_synthesize_audio_shifts_subtitle_for_second_sentence(tmp_path):
    tl = TaskLogger("pauses-integration", tmp_path)
    source = tmp_path / "source.mp3"
    _make_silence_mp3(source, 2.0)

    class _Provider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def synthesize(self, text, output_path=None, voice=None, boundaries=None):
            if boundaries is not None:
                boundaries.extend(
                    [
                        {"offset": 0.0, "duration": 1.0, "text": "第一句。"},
                        {"offset": 1.0, "duration": 1.0, "text": "第二句。"},
                    ]
                )
            Path(output_path).write_bytes(source.read_bytes())
            return output_path

        async def get_duration(self, audio_path):
            return 2.0

    request = SimpleNamespace(
        content_type="book",
        voice="zh-CN-XiaoxiaoNeural",
        voice_rate="+0%",
        language="zh",
    )
    script = SimpleNamespace(segments=[SimpleNamespace(text="第一句。第二句。")])

    with patch.object(vs, "EdgeTTSEngine", MagicMock(return_value=_Provider())), patch.object(
        vs, "_ensure_not_cancelled"
    ):
        segment_audios, total = await vs._synthesize_audio(script, request, tmp_path, tl)

    assert len(segment_audios) == 1
    segment = segment_audios[0]
    assert abs(segment["duration"] - 2.38) < 0.15
    assert abs(segment["boundaries"][1]["offset"] - 1.38) < 1e-6

    subtitles = SubtitleGenerator().generate_for_segments(segment_audios)
    second = [s for s in subtitles if "第二句" in s.text]
    assert second
    assert abs(second[0].start_time - 1.38) < 0.1


# --------------------------------------------------------------------------- #
# Gap mode through _synthesize_audio + probe CLI
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg not installed")
@pytest.mark.asyncio
async def test_synthesize_audio_uses_gap_mode_for_indicator(tmp_path):
    tl = TaskLogger("gap-indicator", tmp_path)
    source = tmp_path / "source.mp3"
    _make_tone_gap_mp3(source, tone_s=0.4, silence_s=0.6)

    class _Provider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def synthesize(self, text, output_path=None, voice=None, boundaries=None):
            if boundaries is not None:
                boundaries.extend(
                    [
                        {"offset": 0.0, "duration": 1.0, "text": "第一句。"},
                        {"offset": 1.0, "duration": 0.4, "text": "第二句。"},
                    ]
                )
            Path(output_path).write_bytes(source.read_bytes())
            return output_path

        async def get_duration(self, audio_path):
            return 1.4

    request = SimpleNamespace(
        content_type="indicator",
        voice=None,
        voice_rate=None,
        language="zh",
    )
    script = SimpleNamespace(segments=[SimpleNamespace(text="第一句。第二句。")])

    with patch.object(vs, "EdgeTTSEngine", MagicMock(return_value=_Provider())), patch.object(
        vs, "_ensure_not_cancelled"
    ):
        segment_audios, _total = await vs._synthesize_audio(script, request, tmp_path, tl)

    segment = segment_audios[0]
    # gap mode tops the 0.6s natural silence up to 0.75s.
    assert abs(segment["duration"] - 1.55) < 0.1
    assert abs(segment["boundaries"][1]["offset"] - 1.15) < 0.03


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg not installed")
def test_tts_gap_probe_measure_smoke(tmp_path, capsys):
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "tts_gap_probe.py"
    spec = importlib.util.spec_from_file_location("tts_gap_probe", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    audio = tmp_path / "clip.mp3"
    _make_tone_gap_mp3(audio, tone_s=0.4, silence_s=0.6)

    assert module.main(["--measure", str(audio)]) == 0
    out = capsys.readouterr().out
    assert "speech runs" in out
    assert "measured sentence gaps" in out
