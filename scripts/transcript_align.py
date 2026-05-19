from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import load_project, save_json, save_project


TIME_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2}[,\.]\d{3})",
    re.MULTILINE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--transcript-file", default=None)
    return parser.parse_args()


def parse_timestamp(value: str) -> int:
    hh, mm, tail = value.split(":")
    ss, ms = re.split(r"[,.]", tail)
    return ((int(hh) * 60 + int(mm)) * 60 + int(ss)) * 1000 + int(ms)


def parse_subtitle(text: str) -> list[dict]:
    events = []
    matches = list(TIME_RE.finditer(text))
    for i, match in enumerate(matches):
        start_ms = parse_timestamp(match.group("start"))
        end_ms = parse_timestamp(match.group("end"))
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        body = re.sub(r"^\d+\s*$", "", body, flags=re.MULTILINE).strip()
        if body:
            events.append({"start_ms": start_ms, "end_ms": end_ms, "text": " ".join(body.splitlines())})
    return events


def pick_transcript_file(project: dict, explicit: str | None) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    source = Path(project["source_video"]["local_path"])
    for ext in (".srt", ".vtt", ".txt"):
        candidate = source.with_suffix(ext)
        if candidate.exists():
            return candidate
    return None


def overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def main() -> None:
    args = parse_args()
    project_dir = Path(args.project_dir)
    project = load_project(project_dir)
    transcript_path = pick_transcript_file(project, args.transcript_file)
    transcript = {"backend": "sidecar", "events": []}
    if transcript_path and transcript_path.suffix.lower() in {".srt", ".vtt"}:
        transcript["events"] = parse_subtitle(transcript_path.read_text(encoding="utf-8"))
        transcript["source"] = str(transcript_path.resolve())
    elif transcript_path and transcript_path.suffix.lower() == ".txt":
        full_text = transcript_path.read_text(encoding="utf-8").strip()
        duration = project["source_video"]["duration_ms"]
        transcript["events"] = [{"start_ms": 0, "end_ms": duration, "text": full_text}] if full_text else []
        transcript["source"] = str(transcript_path.resolve())
    else:
        transcript["backend"] = "none"
        transcript["source"] = None

    aligned_excerpts = {}
    for shot in project["shots"]:
        best = []
        for event in transcript["events"]:
            if overlap(shot["start_ms"], shot["end_ms"], event["start_ms"], event["end_ms"]) > 0:
                best.append(event["text"])
        aligned_excerpts[shot["shot_id"]] = " ".join(best).strip()

    latest = load_project(project_dir)
    for shot in latest["shots"]:
        shot["transcript_excerpt"] = aligned_excerpts.get(shot["shot_id"], shot.get("transcript_excerpt", ""))
    latest["transcript"] = transcript
    save_project(project_dir, latest)
    save_json(project_dir / "derived" / "transcript.json", transcript)
    print(f"Aligned transcript events: {len(transcript['events'])}")


if __name__ == "__main__":
    main()
