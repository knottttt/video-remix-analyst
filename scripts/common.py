from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader


def skill_root() -> Path:
    return Path(__file__).resolve().parent.parent


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    value = re.sub(r"-+", "-", value)
    return value.strip("-") or "project"


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def ffprobe(path: Path) -> dict[str, Any]:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=index,codec_type,width,height",
            "-of",
            "json",
            str(path),
        ]
    )
    return json.loads(result.stdout)


def aspect_ratio_label(width: int, height: int) -> str:
    if not width or not height:
        return "unknown"
    g = math.gcd(width, height)
    return f"{width // g}:{height // g}"


def project_json(project_dir: Path) -> Path:
    return project_dir / "derived" / "project.json"


def load_project(project_dir: Path) -> dict[str, Any]:
    path = project_json(project_dir)
    if not path.exists():
        raise FileNotFoundError(f"Project file not found: {path}")
    return load_json(path, {})


def save_project(project_dir: Path, project: dict[str, Any]) -> None:
    save_json(project_json(project_dir), project)


def relpath(path: Path, base: Path) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def copy_or_download(source: str, dest: Path) -> Path:
    ensure_dir(dest.parent)
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in {"http", "https"}:
        urllib.request.urlretrieve(source, dest)
    else:
        shutil.copy2(Path(source), dest)
    return dest


def template_env(root: Path | None = None) -> Environment:
    base = root or skill_root()
    env = Environment(loader=FileSystemLoader(str(base / "templates")), trim_blocks=True, lstrip_blocks=True)
    env.filters["tojson"] = json.dumps
    return env


def infer_schema_variant(duration_seconds: float) -> str:
    if duration_seconds < 15:
        return "2_beat"
    if duration_seconds <= 45:
        return "3_beat"
    return "5_beat"


def ms_to_timestamp(ms: int) -> str:
    total_seconds = max(ms, 0) // 1000
    hh = total_seconds // 3600
    mm = (total_seconds % 3600) // 60
    ss = total_seconds % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def load_toml(path: Path) -> dict[str, Any]:
    import tomllib

    return tomllib.loads(path.read_text(encoding="utf-8"))
