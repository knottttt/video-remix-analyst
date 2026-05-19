from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import librosa
import numpy as np

from common import ensure_dir, load_project, save_json, save_project


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    return parser.parse_args()


def extract_audio(video_path: Path, wav_path: Path) -> None:
    ensure_dir(wav_path.parent)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "22050",
            str(wav_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> None:
    args = parse_args()
    project_dir = Path(args.project_dir)
    project = load_project(project_dir)
    if not project["source_video"].get("audio_present"):
        project["audio_analysis"] = {"available": False, "reason": "no_audio_stream"}
        save_project(project_dir, project)
        return

    wav_path = project_dir / "derived" / "audio" / "audio.wav"
    extract_audio(Path(project["source_video"]["local_path"]), wav_path)
    y, sr = librosa.load(str(wav_path), sr=None, mono=True)
    onset_frames = librosa.onset.onset_detect(y=y, sr=sr)
    beat_tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    onsets_ms = [int(t * 1000) for t in librosa.frames_to_time(onset_frames, sr=sr)]
    beats_ms = [int(t * 1000) for t in librosa.frames_to_time(beat_frames, sr=sr)]
    payload = {
        "available": True,
        "tempo": float(np.asarray(beat_tempo).squeeze()),
        "onsets_ms": onsets_ms,
        "beats_ms": beats_ms,
        "audio_path": str(wav_path.resolve()),
    }
    latest = load_project(project_dir)
    latest["audio_analysis"] = payload
    save_project(project_dir, latest)
    save_json(project_dir / "derived" / "audio" / "onsets.json", onsets_ms)
    save_json(project_dir / "derived" / "audio" / "beats.json", beats_ms)
    print(f"Detected {len(beats_ms)} beats and {len(onsets_ms)} onsets.")


if __name__ == "__main__":
    main()
