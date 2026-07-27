from datetime import datetime
from pathlib import Path

from utils.file_utils import load_json, save_json
from utils.hash_utils import compute_video_hash, get_video_hash_from_id
from utils.slugify import generate_video_id


def test_same_file_same_hash(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    h1 = compute_video_hash(f)
    h2 = compute_video_hash(f)
    assert h1 == h2
    assert len(h1) == 16


def test_different_files_different_hash(tmp_path):
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("hello")
    f2.write_text("world")
    assert compute_video_hash(f1) != compute_video_hash(f2)


def test_save_and_load_json(tmp_path):
    path = tmp_path / "data.json"
    data = {"key": "value", "num": 42}
    save_json(path, data)
    loaded = load_json(path)
    assert loaded == data


def test_load_nonexistent_json_returns_none(tmp_path):
    assert load_json(tmp_path / "nonexistent.json") is None


def test_get_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "custom_cache"))
    from config.settings import Settings

    s = Settings()
    d = Path(s.cache_dir) / "abc123"
    assert str(tmp_path / "custom_cache" / "abc123") == str(d)


def test_hash_consistency_round_trip():
    """US-15.6: Regressao: get_video_hash_from_id(generate_video_id(...)) == hash original."""
    filename = "meu_video_massa.mp4"
    video_hash = "abc123def4567890"
    video_id = generate_video_id(filename, video_hash)
    extracted = get_video_hash_from_id(video_id)
    assert extracted == video_hash


def test_slugify_removes_extension():
    video_id = generate_video_id("video.mp4", "abcd1234efgh5678")
    assert video_id.startswith("video-")
    assert video_id.endswith("abcd1234efgh5678")


def test_state_round_trip(tmp_path):
    """US-15.5: Regressao: PipelineState salvo e recarregado mantem todos os campos."""
    from schemas.state import PipelineState, StageResult

    original = PipelineState(
        video_hash="abc123def4567890",
        video_path=Path("/fake/video.mp4"),
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        updated_at=datetime(2025, 1, 1, 12, 5, 0),
        stages=[
            StageResult(
                stage="VIDEO_PROCESSING",
                status="success",
                started_at=datetime(2025, 1, 1, 12, 0, 0),
                finished_at=datetime(2025, 1, 1, 12, 1, 0),
                duration_seconds=60.0,
            ),
        ],
        completed=True,
    )
    path = tmp_path / "state.json"
    save_json(path, original.model_dump(mode="json"))
    loaded = PipelineState(**load_json(path))
    assert loaded.video_hash == original.video_hash
    assert str(loaded.video_path) == str(original.video_path)
    assert len(loaded.stages) == 1
    assert loaded.stages[0].stage == "VIDEO_PROCESSING"
    assert loaded.completed is True
