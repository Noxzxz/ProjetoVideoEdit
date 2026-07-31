
import pytest

from agents.speech_recognition.agent import SpeechRecognitionAgent


def test_audio_not_found_raises_error():
    agent = SpeechRecognitionAgent()
    with pytest.raises(FileNotFoundError):
        agent.run("test-video", "/inexistente/audio.wav")


def test_returns_transcript_from_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.hash_utils.settings.cache_dir", str(tmp_path))

    agent = SpeechRecognitionAgent()
    from utils.hash_utils import get_cache_dir, get_video_hash_from_id

    video_id = "test-video-abc123def456"
    video_hash = get_video_hash_from_id(video_id)
    cache_dir = get_cache_dir(video_hash)
    cache_dir.mkdir(parents=True, exist_ok=True)

    import json
    fake_data = {
        "video_id": video_id,
        "language": "pt",
        "segments": [{"id": 0, "start": 0.0, "end": 1.0, "text": "teste", "confidence": 0.9}],
    }
    (cache_dir / "transcript.json").write_text(json.dumps(fake_data), encoding="utf-8")

    result = agent.run(video_id, "/inexistente/audio.wav")
    assert result.video_id == video_id
    assert len(result.segments) == 1
