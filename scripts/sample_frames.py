from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
import yaml

from common import ensure_dir, load_project, save_project, skill_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    return parser.parse_args()


def score_frame(frame: np.ndarray, weights: dict[str, float]) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    clarity = min(float(lap.var()) / 500.0, 1.0)
    brightness = float(gray.mean()) / 255.0
    exposure = max(0.0, 1.0 - abs(brightness - 0.5) * 2.0)
    edges = cv2.Canny(gray, 60, 160)
    ys, xs = np.where(edges > 0)
    if len(xs) == 0:
        center_bias = 0.5
        saliency = 0.1
    else:
        cx = float(xs.mean()) / gray.shape[1]
        cy = float(ys.mean()) / gray.shape[0]
        distance = ((cx - 0.5) ** 2 + (cy - 0.5) ** 2) ** 0.5
        center_bias = max(0.0, 1.0 - min(distance / 0.71, 1.0))
        saliency = min(float(len(xs)) / (gray.shape[0] * gray.shape[1] * 0.08), 1.0)
    return (
        clarity * weights["clarity"]
        + exposure * weights["exposure"]
        + center_bias * weights["center_bias"]
        + saliency * weights["saliency"]
    )


def read_frame(cap: cv2.VideoCapture, frame_index: int) -> np.ndarray:
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(frame_index, 0))
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError(f"Failed to read frame {frame_index}")
    return frame


def save_frame(path: Path, frame: np.ndarray) -> None:
    ensure_dir(path.parent)
    cv2.imwrite(str(path), frame)


def main() -> None:
    args = parse_args()
    project_dir = Path(args.project_dir)
    project = load_project(project_dir)
    video_path = Path(project["source_video"]["local_path"])
    config = yaml.safe_load((skill_root() / "config" / "hero_frame.yaml").read_text(encoding="utf-8"))
    weights = config["weights"]
    candidate_count = int(config["sampling"]["candidates_per_shot"])
    frames_dir = ensure_dir(project_dir / "derived" / "frames")

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    for shot in project["shots"]:
        start_frame = min(total_frames - 1, int((shot["start_ms"] / 1000.0) * fps))
        end_frame = min(total_frames - 1, max(start_frame + 1, int((shot["end_ms"] / 1000.0) * fps) - 1))
        middle_frame = (start_frame + end_frame) // 2
        candidates = np.linspace(start_frame, end_frame, num=min(candidate_count, max(end_frame - start_frame + 1, 1)), dtype=int)

        first = read_frame(cap, start_frame)
        middle = read_frame(cap, middle_frame)
        best_score = -1.0
        best_index = middle_frame
        best_frame = middle
        for idx in candidates:
            frame = read_frame(cap, int(idx))
            score = score_frame(frame, weights)
            if score > best_score:
                best_score = score
                best_index = int(idx)
                best_frame = frame

        first_path = frames_dir / f"{shot['shot_id']}_first.jpg"
        middle_path = frames_dir / f"{shot['shot_id']}_middle.jpg"
        hero_path = frames_dir / f"{shot['shot_id']}_hero.jpg"
        save_frame(first_path, first)
        save_frame(middle_path, middle)
        save_frame(hero_path, best_frame)

        shot["frame_first_path"] = str(first_path.resolve())
        shot["frame_middle_path"] = str(middle_path.resolve())
        shot["frame_hero_path"] = str(hero_path.resolve())
        shot["hero_frame_index"] = best_index
        shot["hero_frame_score"] = round(best_score, 4)

    cap.release()
    save_project(project_dir, project)
    print(f"Sampled frames for {len(project['shots'])} shots.")


if __name__ == "__main__":
    main()
