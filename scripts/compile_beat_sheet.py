from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from common import ensure_dir, load_json, load_project, save_project, skill_root, template_env
from storyboard_render import build_storyboard_panels


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--variant-id", required=True)
    parser.add_argument("--style-profile", default="pixar_3d")
    parser.add_argument("--panel-count", type=int, default=4)
    return parser.parse_args(argv)


def find_variant(project: dict[str, Any], variant_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for job in project["remix_jobs"]:
        for variant in job["generated_variants"]:
            if variant["variant_id"] == variant_id:
                return job, variant
    raise KeyError(f"Variant not found: {variant_id}")


def load_style_profile(profile_name: str) -> dict[str, Any]:
    path = skill_root() / "config" / "style_profiles" / f"{profile_name}.json"
    profile = load_json(path)
    if not profile:
        raise FileNotFoundError(f"Style profile not found: {path}")
    return profile


def build_prompt_characters(remix_job: dict[str, Any], refs_dir: Path | None) -> list[dict[str, Any]]:
    prompt_characters = []
    char_map = remix_job.get("character_mapping", {})
    for char_id, mapping in char_map.items():
        reference_images = []
        for src in mapping.get("reference_image_paths", []):
            src_path = Path(src)
            if src_path.exists() and refs_dir is not None:
                dest = refs_dir / src_path.name
                shutil.copy2(src_path, dest)
                reference_images.append(f"refs/{src_path.name}")
        prompt_characters.append(
            {
                "id": char_id,
                "label": mapping.get("user_character_name") or mapping.get("source_role_name") or char_id,
                "identity_description": mapping.get("identity_description") or "Keep the replacement role visually consistent throughout the document.",
                "must_keep_traits": mapping.get("must_keep_traits", []),
                "forbidden_traits": mapping.get("forbidden_traits", []),
                "reference_images": reference_images,
            }
        )
    return prompt_characters


def select_panels(panels: list[dict[str, Any]], panel_count: int) -> list[dict[str, Any]]:
    target = max(1, panel_count)
    selected = []
    seen_beats: set[str] = set()
    used_indices: set[int] = set()

    for panel in panels:
        beat = str(panel.get("beat") or "").strip()
        if beat and beat not in seen_beats:
            selected.append(panel)
            seen_beats.add(beat)
            used_indices.add(int(panel["index"]))
            if len(selected) >= target:
                return selected

    for panel in panels:
        panel_index = int(panel["index"])
        if panel_index in used_indices:
            continue
        selected.append(panel)
        used_indices.add(panel_index)
        if len(selected) >= target:
            break

    return selected


def title_case_beat(value: str) -> str:
    if not value:
        return "Beat"
    return value.replace("_", " ").replace("-", " ").title()


def dedupe_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def build_shot_range_label(selected_panels: list[dict[str, Any]]) -> str:
    indices = [int(panel["index"]) for panel in selected_panels]
    return f"Shots {min(indices):02d}-{max(indices):02d}"


def build_dramatic_function(selected_panels: list[dict[str, Any]]) -> str:
    beats = dedupe_preserve([title_case_beat(str(panel.get("beat", ""))) for panel in selected_panels])
    return " -> ".join(beats) if beats else "Scene progression"


def build_arc_summary(selected_panels: list[dict[str, Any]]) -> str:
    start = title_case_beat(str(selected_panels[0].get("beat", "")))
    end = title_case_beat(str(selected_panels[-1].get("beat", "")))
    if start == end:
        return start
    return f"{start} -> {end}"


def build_lighting_material_notes(selected_panels: list[dict[str, Any]]) -> list[str]:
    return dedupe_preserve([str(panel.get("lighting") or "") for panel in selected_panels])


def collect_subject_labels(selected_panels: list[dict[str, Any]], prompt_characters: list[dict[str, Any]]) -> list[str]:
    known = {char["id"]: char["label"] for char in prompt_characters}
    subjects: list[str] = []
    for panel in selected_panels:
        subject = str(panel.get("subject") or "")
        for raw_part in subject.split(","):
            part = raw_part.strip()
            if not part:
                continue
            subjects.append(known.get(part, part))
    return dedupe_preserve(subjects)


def build_camera_map_lines(selected_panels: list[dict[str, Any]], subject_labels: list[str]) -> list[str]:
    lines = ["[Left frame margin]  subject cluster  [Center action axis]  camera view line  [Right frame margin]"]
    if subject_labels:
        lines.append("Subjects: " + " | ".join(subject_labels[:4]))
    for panel in selected_panels[:4]:
        lines.append(
            f"Cam {int(panel['index']):02d}: toward {panel.get('subject', 'main subject')} | "
            f"{panel.get('camera_angle', 'neutral angle')} | {panel.get('camera_motion', 'static')}"
        )
    return lines


def build_camera_map_notes(selected_panels: list[dict[str, Any]]) -> list[str]:
    notes = []
    for panel in selected_panels[:4]:
        notes.append(
            f"Shot {int(panel['index']):02d} observes {panel.get('subject', 'the scene')} with "
            f"{panel.get('camera_motion', 'static framing')} and a {panel.get('camera_angle', 'neutral angle')} read."
        )
    return notes


def build_main_scene_reference(scene_summary: str, subject_labels: list[str], lighting_notes: list[str]) -> str:
    subject_text = ", ".join(subject_labels[:4]) if subject_labels else "the core cast"
    lighting_text = ", ".join(lighting_notes[:3]) if lighting_notes else "cinematic mixed lighting"
    return (
        f"Single wide hero reference image for the scene. Narrative brief: {scene_summary} "
        f"Stage the key subjects {subject_text} inside one coherent environment. "
        f"Lighting and materials should reflect {lighting_text} while keeping the emotional tension readable at a glance."
    )


def build_context(
    variant: dict[str, Any],
    prompt_characters: list[dict[str, Any]],
    selected_panels: list[dict[str, Any]],
    style_profile: dict[str, Any],
) -> dict[str, Any]:
    subject_labels = collect_subject_labels(selected_panels, prompt_characters)
    lighting_notes = build_lighting_material_notes(selected_panels)
    return {
        "output_mode": "beat_sheet_document",
        "layout_preset": style_profile.get("layout_preset", "single_page_film_beat_sheet"),
        "style_profile_name": style_profile.get("profile_name", "unknown"),
        "document_type": style_profile.get("document_type", "single-page production document"),
        "scene_summary": variant.get("creative_constraints", ""),
        "dramatic_function": build_dramatic_function(selected_panels),
        "arc_summary": build_arc_summary(selected_panels),
        "lighting_material_notes": lighting_notes,
        "shot_range_label": build_shot_range_label(selected_panels),
        "selected_panel_source_shot_ids": [panel["source_shot_id"] for panel in selected_panels],
        "main_scene_reference": build_main_scene_reference(
            variant.get("creative_constraints", ""),
            subject_labels,
            lighting_notes,
        ),
        "camera_map_lines": build_camera_map_lines(selected_panels, subject_labels),
        "camera_map_notes": build_camera_map_notes(selected_panels),
        "character_reference_title": "Character Reference",
        "storyboard_preview_title": "Storyboard Preview",
        "subject_labels": subject_labels,
        "selected_panels": selected_panels,
        "characters": prompt_characters,
        "style_profile": style_profile,
        "target_aspect_ratio": variant.get("target_aspect_ratio", "16:9"),
        "selected_panel_indices": [int(panel["index"]) for panel in selected_panels],
    }


def render_beat_sheet_prompt(
    variant: dict[str, Any],
    prompt_characters: list[dict[str, Any]],
    style_profile: dict[str, Any],
    panel_count: int,
) -> tuple[str, dict[str, Any]]:
    renderable_variant = dict(variant)
    panels, _ = build_storyboard_panels(renderable_variant)
    selected_panels = select_panels(panels, panel_count)
    context = build_context(renderable_variant, prompt_characters, selected_panels, style_profile)
    env = template_env(skill_root())
    prompt_md = env.get_template("beat_sheet_document_prompt.j2").render(doc=context)
    return prompt_md, context


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    project_dir = Path(args.project_dir)
    project = load_project(project_dir)
    remix_job, variant = find_variant(project, args.variant_id)
    style_profile = load_style_profile(args.style_profile)

    variant_dir = project_dir / "exports" / "storyboards" / variant["variant_id"]
    bundle_dir = variant_dir / "beat_sheet_bundle"
    refs_dir = bundle_dir / "refs"
    ensure_dir(refs_dir)

    prompt_characters = build_prompt_characters(remix_job, refs_dir)
    prompt_md, context = render_beat_sheet_prompt(variant, prompt_characters, style_profile, args.panel_count)

    prompt_path = bundle_dir / "prompt.md"
    ensure_dir(prompt_path.parent)
    prompt_path.write_text(prompt_md, encoding="utf-8")

    howto_md = template_env(skill_root()).get_template("beat_sheet_howto.j2").render()
    howto_path = bundle_dir / "HOWTO.md"
    howto_path.write_text(howto_md, encoding="utf-8")

    manifest = {
        "output_mode": "beat_sheet_document",
        "style_profile": args.style_profile,
        "layout_preset": context["layout_preset"],
        "prompt_file": "prompt.md",
        "howto_file": "HOWTO.md",
        "selected_panel_indices": context["selected_panel_indices"],
        "selected_panel_source_shot_ids": context["selected_panel_source_shot_ids"],
        "shot_range": context["shot_range_label"],
        "reference_images": [
            {"role": char["label"], "files": char["reference_images"]} for char in prompt_characters if char["reference_images"]
        ],
    }
    manifest_path = bundle_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    project["deliverables"]["beat_sheet_bundle_dir"] = str(bundle_dir.resolve())
    project["deliverables"]["beat_sheet_prompt_path"] = str(prompt_path.resolve())
    save_project(project_dir, project)
    print(bundle_dir.resolve())


if __name__ == "__main__":
    main()
