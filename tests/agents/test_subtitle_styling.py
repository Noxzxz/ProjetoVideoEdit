from agents.subtitle_styling.agent import (
    SubtitleStylingAgent,
    split_into_caption_chunks,
    to_srt,
    to_vtt,
)
from schemas.transcript import TranscriptCleaned, TranscriptSegment


def test_split_into_caption_chunks_respects_max_words():
    segments = [
        TranscriptSegment(
            id=0, start=0.0, end=4.0,
            text="uma frase bem longa com varias palavras", confidence=0.9,
        ),
    ]
    chunks = split_into_caption_chunks(segments, max_words_per_line=3)
    for chunk in chunks:
        assert len(chunk.text.split()) <= 3


def test_split_empty_segments():
    chunks = split_into_caption_chunks([])
    assert chunks == []


def test_to_srt_format():
    chunks = [
        TranscriptSegment(id=0, start=1.0, end=2.5, text="Hello world", confidence=0.9),
    ]
    srt = to_srt(chunks)
    assert "1" in srt
    assert "-->" in srt
    assert "Hello world" in srt
    assert ",000" in srt  # SRT uses comma for milliseconds


def test_to_vtt_format():
    chunks = [
        TranscriptSegment(id=0, start=1.0, end=2.5, text="Hello world", confidence=0.9),
    ]
    vtt = to_vtt(chunks)
    assert "WEBVTT" in vtt
    assert "-->" in vtt
    assert "Hello world" in vtt
    assert ".000" in vtt  # VTT uses dot for milliseconds


def test_subtitle_styling_agent_run_returns_subtitle_result(tmp_path):
    agent = SubtitleStylingAgent()
    transcript = TranscriptCleaned(
        video_id="test-video",
        segments=[
            TranscriptSegment(id=0, start=0.0, end=1.0, text="Ola mundo", confidence=0.9),
        ],
        full_text_cleaned="Ola mundo",
    )
    config = type("Settings", (), {"outputs_dir": str(tmp_path), "max_words_per_line": 4})()
    result = agent.run("test-video", transcript, config)
    assert result.video_id == "test-video"
    assert result.srt_path.endswith(".srt")
    assert result.vtt_path.endswith(".vtt")
