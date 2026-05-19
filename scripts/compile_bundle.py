from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from common import ensure_dir, load_project, save_project
from storyboard_render import render_shot_prompts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--variant-id", required=True)
    return parser.parse_args()


def find_variant(project: dict, variant_id: str) -> tuple[dict, dict]:
    for job in project["remix_jobs"]:
        for variant in job["generated_variants"]:
            if variant["variant_id"] == variant_id:
                return job, variant
    raise KeyError(f"Variant not found: {variant_id}")


def main() -> None:
    args = parse_args()
    project_dir = Path(args.project_dir)
    project = load_project(project_dir)
    remix_job, variant = find_variant(project, args.variant_id)
    variant["selected"] = True
    variant_dir = project_dir / "exports" / variant["variant_id"]
    refs_dir = variant_dir / "refs"
    ensure_dir(refs_dir)
    char_map = remix_job["character_mapping"]
    for mapping in char_map.values():
        for src in mapping.get("reference_image_paths", []):
            src_path = Path(src)
            if src_path.exists():
                dest = refs_dir / src_path.name
                shutil.copy2(src_path, dest)

    shot_prompts_md, _ = render_shot_prompts(variant)
    shot_prompts_path = variant_dir / "shot_prompts.md"
    ensure_dir(shot_prompts_path.parent)
    shot_prompts_path.write_text(shot_prompts_md, encoding="utf-8")
    project["deliverables"]["shot_prompts_markdown_path"] = str(shot_prompts_path.resolve())
    save_project(project_dir, project)
    print(shot_prompts_path.resolve())


if __name__ == "__main__":
    main()
