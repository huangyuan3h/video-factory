"""Sentence-pause insertion between TTS sentences (task-S).

Real short mp3s are generated with ffmpeg in ``tmp_path``; the pure planning
helpers are tested without audio and the codec failure path is mocked.
"""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.core.subtitle_gen import SubtitleGenerator
from src.core.task_logger import TaskLogger
from src.core.tts import pauses
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
