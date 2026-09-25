"""Real speech-onset detection, cue snapping and spoken-weight timing (task-N2)."""

import subprocess
from pathlib import Path

import pytest

from src.core.subtitle_gen import SubtitleGenerator, _spoken_weight
from src.core.tts.speech_runs import detect_speech_runs, snap_cues

FFMPEG_AVAILABLE = subprocess.run(
    ["ffmpeg", "-version"], capture_output=True
).returncode == 0

pytestmark = pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg not installed")


def _make_bursts(path: Path, pattern: list[tuple[str, float]]) -> None:
    """Build a mono 24k WAV of sine bursts and silences from ``pattern``."""
    inputs: list[str] = []
    labels: list[str] = []
    for index, (kind, seconds) in enumerate(pattern):
        if kind == "speech":
            source = f"sine=frequency=440:sample_rate=24000:duration={seconds}"
        else:
            source = f"anullsrc=channel_layout=mono:sample_rate=24000:duration={seconds}"
        inputs += ["-f", "lavfi", "-i", source]
        labels.append(f"[{index}:a]")
    filter_complex = "".join(labels) + f"concat=n={len(pattern)}:v=0:a=1[a]"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            *inputs,
            "-filter_complex",
            filter_complex,
            "-map",
            "[a]",
            "-ar",
            "24000",
            "-ac",
            "1",
            str(path),
        ],
        check=True,
    )


# --------------------------------------------------------------------------- #
# detect_speech_runs
# --------------------------------------------------------------------------- #


def test_detect_speech_runs_finds_bursts(tmp_path):
    audio = tmp_path / "bursts.wav"
    _make_bursts(
        audio,
        [("speech", 0.4), ("silence", 0.3), ("speech", 0.5)],
    )

    runs = detect_speech_runs(audio)

    assert len(runs) == 2
    assert abs(runs[0][0] - 0.0) <= 0.02
    assert abs(runs[0][1] - 0.4) <= 0.02
    assert abs(runs[1][0] - 0.7) <= 0.02
    assert abs(runs[1][1] - 1.2) <= 0.02


def test_detect_speech_runs_merges_short_gaps(tmp_path):
    audio = tmp_path / "gappy.wav"
    _make_bursts(
        audio,
        [("speech", 0.4), ("silence", 0.03), ("speech", 0.4)],
    )

    runs = detect_speech_runs(audio)

    assert len(runs) == 1
    assert abs(runs[0][0] - 0.0) <= 0.02
    assert abs(runs[0][1] - 0.83) <= 0.03


def test_detect_speech_runs_pure_silence_is_empty(tmp_path):
    audio = tmp_path / "silence.wav"
    _make_bursts(audio, [("silence", 1.0)])

    assert detect_speech_runs(audio) == []


def test_detect_speech_runs_failure_is_empty(tmp_path):
    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"not-audio")

    assert detect_speech_runs(broken) == []
    assert detect_speech_runs(tmp_path / "missing.mp3") == []


# --------------------------------------------------------------------------- #
# snap_cues
# --------------------------------------------------------------------------- #


def test_snap_cues_snaps_forward_and_back():
    forward = snap_cues([(1.0, 1.5)], [(1.2, 1.6)])
    assert forward[0][0] == pytest.approx(1.16)
    assert forward[0][1] == pytest.approx(1.7)

    backward = snap_cues([(1.3, 1.8)], [(1.0, 1.4)])
    assert backward[0][0] == pytest.approx(0.96)
    assert backward[0][1] == pytest.approx(1.5)


def test_snap_cues_window_miss_keeps_original_start():
    result = snap_cues([(3.0, 3.5)], [(1.0, 1.4)])
    assert result[0][0] == 3.0


def test_snap_cues_empty_inputs():
    assert snap_cues([], [(1.0, 2.0)]) == []
    assert snap_cues([(1.0, 2.0)], []) == [(1.0, 2.0)]


def test_snap_cues_keeps_order_and_min_length():
    result = snap_cues([(1.0, 1.5), (1.2, 1.7)], [(1.05, 1.3)])

    assert result[0][0] == pytest.approx(1.01)
    assert result[1][0] >= result[0][0] + 0.3 - 1e-9
    assert result[0][1] <= result[1][0] + 1e-9


def test_snap_cues_bridges_close_cues():
    result = snap_cues([(1.0, 1.2), (1.3, 2.0)], [(1.0, 1.2), (1.3, 1.9)])

    assert result[0] == pytest.approx((0.96, 1.26))
    assert result[1] == pytest.approx((1.26, 2.0))


def test_snap_cues_extends_to_speech_before_next_cue():
    result = snap_cues([(1.0, 1.2), (3.0, 3.5)], [(1.0, 1.9), (3.0, 3.4)])

    assert result[0][1] == pytest.approx(2.0)
    assert result[1][0] == pytest.approx(2.96)


# --------------------------------------------------------------------------- #
# _spoken_weight
# --------------------------------------------------------------------------- #


def test_spoken_weight_counts_numbers_longer_than_len():
    text = "6.5%和5.8%"
    assert _spoken_weight(text) > len(text)
    assert _spoken_weight(text) == 13


def test_spoken_weight_thousands_and_sign():
    assert _spoken_weight("260,436") == 7
    assert _spoken_weight("-27.4%") == 8
    assert _spoken_weight("−27.4%") == 8


def test_spoken_weight_cjk_and_punctuation():
    assert _spoken_weight("你好") == 2
    assert _spoken_weight("，。 ") == 0
    assert _spoken_weight("Hello") == 5


# --------------------------------------------------------------------------- #
# generate_for_segments with speech_runs
# --------------------------------------------------------------------------- #


def test_generate_for_segments_snaps_with_speech_runs():
    gen = SubtitleGenerator(max_chars_per_line=5)
    text = "一二三四五六七八九十"
    segments = [
        {
            "text": text,
            "duration": 10.0,
            "offset": 0.0,
            "boundaries": [{"offset": 0.0, "duration": 10.0, "text": text}],
            "speech_runs": [(0.0, 4.6), (5.2, 10.0)],
        }
    ]

    subtitles = gen.generate_for_segments(segments)

    assert len(subtitles) == 2
    assert subtitles[0].start_time == pytest.approx(0.0)
    assert subtitles[0].end_time == pytest.approx(4.7)
    assert subtitles[1].start_time == pytest.approx(5.16)
    assert subtitles[-1].end_time <= 10.0


def test_generate_for_segments_without_speech_runs_unchanged():
    gen = SubtitleGenerator(max_chars_per_line=5)
    text = "一二三四五六七八九十"
    segments = [
        {
            "text": text,
            "duration": 10.0,
            "offset": 0.0,
            "boundaries": [{"offset": 0.0, "duration": 10.0, "text": text}],
        }
    ]

    subtitles = gen.generate_for_segments(segments)

    assert (subtitles[0].start_time, subtitles[0].end_time) == (0.0, 5.0)
    assert (subtitles[1].start_time, subtitles[1].end_time) == (5.0, 10.0)


def test_generate_for_segments_clamps_snapped_end_to_segment():
    gen = SubtitleGenerator()
    segments = [
        {
            "text": "一句话。",
            "duration": 2.0,
            "offset": 3.0,
            "boundaries": [{"offset": 0.0, "duration": 2.0, "text": "一句话。"}],
            "speech_runs": [(0.0, 2.0)],
        }
    ]

    subtitles = gen.generate_for_segments(segments)

    assert subtitles[0].end_time <= 5.0
    assert subtitles[0].start_time >= 3.0
