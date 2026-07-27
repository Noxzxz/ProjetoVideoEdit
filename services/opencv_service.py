import logging
from pathlib import Path

import cv2
import numpy as np

from shared.exceptions import VideoNotFoundError

logger = logging.getLogger(__name__)


def extract_candidate_frames(
    video_path: Path,
    output_dir: Path,
    max_frames: int = 5,
    min_spacing_percent: float = 5.0,
) -> list[Path]:
    if not video_path.exists():
        raise VideoNotFoundError(f"Video nao encontrado: {video_path}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise VideoNotFoundError(f"Nao foi possivel abrir: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0
    spacing_seconds = (min_spacing_percent / 100) * duration

    frames_data: list[tuple[int, float, np.ndarray]] = []
    prev_hist: np.ndarray | None = None
    frame_idx = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % int(max(fps, 1)) == 0:
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
                cv2.normalize(hist, hist)

                scene_dist = 1.0
                if prev_hist is not None:
                    corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                    scene_dist = 1.0 - max(0.0, corr)

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
                if lap_var >= 50:
                    frames_data.append((frame_idx, scene_dist, frame.copy()))

                prev_hist = hist

            frame_idx += 1
    finally:
        cap.release()

    frames_data.sort(key=lambda x: x[1], reverse=True)

    selected: list[tuple[int, np.ndarray]] = []
    for idx, _dist, frame in frames_data:
        timestamp = idx / fps
        if all(abs(timestamp - (s[0] / fps)) >= spacing_seconds for s in selected):
            selected.append((idx, frame))
        if len(selected) >= max_frames:
            break

    selected.sort(key=lambda x: x[0])

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for _idx, (frame_idx, frame) in enumerate(selected):
        timestamp = int(frame_idx / fps)
        out_path = output_dir / f"frame_{timestamp:03d}.jpg"
        cv2.imwrite(str(out_path), frame)
        paths.append(out_path)

    logger.info(f"{len(paths)} frames candidatos extraidos em {output_dir}")
    return paths
