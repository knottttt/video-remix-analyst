from __future__ import annotations

import argparse
from pathlib import Path

from scenedetect import AdaptiveDetector, ContentDetector, SceneManager, open_video

from common import load_project, load_toml, save_json, save_project, skill_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--threshold", type=float, default=None)
    return parser.parse_args()


def detect_shots(video_path: Path, threshold: float, min_scene_len_frames: int) -> list[tuple[int, int]]:
    video = open_video(str(video_path))
    manager = SceneManager()
    manager.add_detector(ContentDetector(threshold=threshold, min_scene_len=min_scene_len_frames))
    manager.add_detector(AdaptiveDetector(adaptive_threshold=3.0, min_scene_len=min_scene_len_frames))
    manager.detect_scenes(video)
    scenes = manager.get_scene_list()
    shots: list[tuple[int, int]] = []
    if not scenes:
        duration_ms = int((video.duration.get_seconds() or 0) * 1000)
        return [(0, duration_ms)]
    for start, end in scenes:
        shots.append((int(start.get_seconds() * 1000), int(end.get_seconds() * 1000)))
    return shots


def main() -> None:
    args = parse_args()
    project_dir = Path(args.project_dir)
    project = load_project(project_dir)
    config = load_toml(skill_root() / "config" / "default.toml")
    threshold = args.threshold or config["segmentation"]["scene_threshold"]
    min_scene_len_frames = config["segmentation"]["min_scene_len_frames"]
    video_path = Path(project["source_video"]["local_path"])
    shots_raw = detect_shots(video_path, threshold, min_scene_len_frames)
    total_duration = max(project["source_video"]["duration_ms"], 1)

    shots = []
    for index, (start_ms, end_ms) in enumerate(shots_raw, start=1):
        duration_ms = max(1, end_ms - start_ms)
        relative = duration_ms / total_duration
        confidence = min(0.95, max(0.55, 0.55 + relative * 2.0))
        shots.append(
            {
                "shot_id": f"shot_{index:03d}",
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": duration_ms,
                "beat_id": None,
                "boundary_confidence": round(confidence, 3),
                "transcript_excerpt": "",
                "analysis_mode": "",
                "merged_with": [],
                "context_summary": "",
                "character_ids": [],
            }
        )

    project["shots"] = shots
    save_project(project_dir, project)
    save_json(project_dir / "derived" / "shots.json", shots)
    print(f"Detected {len(shots)} shots.")


if __name__ == "__main__":
    main()
