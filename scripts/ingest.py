from __future__ import annotations

import argparse
from pathlib import Path

from common import aspect_ratio_label, copy_or_download, ensure_dir, ffprobe, save_json, save_project, slugify


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Local video path or direct URL.")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--project-name", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_dir = Path(args.project_dir)
    ensure_dir(project_dir / "source")
    ensure_dir(project_dir / "derived")
    ensure_dir(project_dir / "exports")
    ensure_dir(project_dir / "reports")

    source_name = Path(args.input).name or "source.mp4"
    local_name = source_name if "." in source_name else "source.mp4"
    source_path = project_dir / "source" / local_name
    copy_or_download(args.input, source_path)
    probe = ffprobe(source_path)

    video_stream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), {})
    audio_present = any(s.get("codec_type") == "audio" for s in probe.get("streams", []))
    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    duration_ms = int(float(probe.get("format", {}).get("duration", 0)) * 1000)
    project_name = args.project_name or slugify(source_path.stem)

    project = {
        "project_name": project_name,
        "source_video": {
            "video_id": project_name,
            "source_type": "url" if args.input.startswith(("http://", "https://")) else "local_file",
            "source_path_or_url": args.input,
            "local_path": str(source_path.resolve()),
            "duration_ms": duration_ms,
            "aspect_ratio": aspect_ratio_label(width, height),
            "width": width,
            "height": height,
            "language": "unknown",
            "audio_present": audio_present,
        },
        "beats": [],
        "shots": [],
        "characters": [],
        "remix_jobs": [],
        "deliverables": {},
        "analysis_notes": [],
    }
    save_project(project_dir, project)
    save_json(project_dir / "derived" / "probe.json", probe)
    print(project_dir.resolve())


if __name__ == "__main__":
    main()
