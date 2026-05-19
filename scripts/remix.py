from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

from common import load_json, load_project, save_json, save_project


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--creative-brief", default="")
    parser.add_argument("--creative-brief-file", default=None)
    parser.add_argument("--character-mapping-file", default=None)
    parser.add_argument("--variant-count", type=int, default=3)
    parser.add_argument("--preserve-beat-skeleton", action="store_true")
    parser.add_argument("--target-aspect-ratio", default="9:16")
    parser.add_argument("--target-panel-count", type=int, default=0)
    parser.add_argument("--seed", type=int, default=7)
    return parser.parse_args()


def read_creative_brief(args: argparse.Namespace) -> str:
    if args.creative_brief_file:
        return Path(args.creative_brief_file).read_text(encoding="utf-8").strip()
    return args.creative_brief.strip() or "Remix the reference into a fresh but structurally coherent short-form storyboard."


def build_character_map(project: dict, mapping_path: str | None) -> dict[str, dict]:
    base = {char["character_id"]: {"source_role_name": char["source_role_name"]} for char in project["characters"]}
    if not mapping_path:
        return base
    payload = load_json(Path(mapping_path), {})
    for item in payload.get("characters", []):
        base[item["character_id"]] = {
            "source_role_name": item.get("source_role_name", item["character_id"]),
            "user_character_name": item.get("user_character_name"),
            "reference_image_paths": item.get("reference_image_paths", []),
            "identity_description": item.get("identity_description", ""),
            "must_keep_traits": item.get("must_keep_traits", []),
            "forbidden_traits": item.get("forbidden_traits", []),
        }
    return base


def eligible_shots(project: dict) -> list[dict]:
    shots = []
    for shot in project["shots"]:
        if shot.get("dependency_level") == "high":
            continue
        if shot.get("boundary_confidence", 0) < 0.7:
            continue
        shots.append(shot)
    return shots or project["shots"]


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def rewrite_subject(shot: dict, project: dict, char_map: dict[str, dict]) -> str:
    names = []
    for char_id in shot.get("character_ids", []):
        mapping = char_map.get(char_id, {})
        names.append(mapping.get("user_character_name") or mapping.get("source_role_name") or char_id)
    return ", ".join(names) if names else shot["main_subject"]


def build_panel(shot: dict, subject: str, beat_type: str, creative_brief: str) -> dict:
    prompt = (
        f"{shot['shot_size']}，{shot['camera_angle']}，{shot['camera_motion']}。"
        f"主体：{subject}。动作：{shot['action']}。情绪：{shot['emotion']}。"
        f"剧情：{shot.get('story_description', '')}。变化：{shot.get('change_description', '')}。"
        f"按这个创意方向改写：{creative_brief}"
    )
    return {
        "source_shot_id": shot["shot_id"],
        "duration_target_seconds": max(1, round(shot["duration_ms"] / 1000.0)),
        "shot_size": shot["shot_size"],
        "camera_angle": shot["camera_angle"],
        "camera_motion": shot["camera_motion"],
        "composition": shot["composition"],
        "lighting": shot["lighting"],
        "subject": subject,
        "action": shot["action"],
        "emotion": shot["emotion"],
        "beat": beat_type,
        "visual": f"{subject} in a {shot['shot_size']} with {shot['lighting']}.",
        "sound_note": shot.get("transcript_excerpt") or "Use score or SFX to bridge the beat.",
        "purpose": shot["story_function"],
        "prompt": prompt,
        "reframe_note_9x16": shot["reframe_note_9x16"],
        "seedance_motion_hint": f"{shot['camera_motion']} while keeping {subject} readable in frame.",
        "story_description": shot.get("story_description", ""),
        "change_description": shot.get("change_description", ""),
        "emotion_progression": shot.get("emotion_progression", ""),
        "transition_bridge": shot.get("transition_bridge", ""),
        "information_revealed": shot.get("information_revealed", ""),
        "information_withheld": shot.get("information_withheld", ""),
    }


def allocate_by_beats(project: dict, panel_count: int) -> list[str]:
    beat_ids = [beat["beat_id"] for beat in project["beats"]]
    if not beat_ids:
        return []
    allocation = []
    while len(allocation) < panel_count:
        for beat_id in beat_ids:
            allocation.append(beat_id)
            if len(allocation) >= panel_count:
                break
    return allocation


def build_variant(project: dict, source_shots: list[dict], char_map: dict[str, dict], creative_brief: str, index: int, preserve: bool, panel_count: int, target_aspect_ratio: str) -> dict:
    tone_shift = ["close to reference", "more dramatic", "twist-driven", "more playful"][index % 4]
    reinterpretation = round(index / max(panel_count - 1, 1), 2)
    structure_pres = 0.85 if preserve else max(0.25, 0.6 - index * 0.08)
    reorder_degree = round((index + 1) / 4, 2)
    char_strength = 1.0 if any(v.get("user_character_name") for v in char_map.values()) else 0.2
    diversity_vector = {
        "reinterpretation_angle": reinterpretation,
        "structure_preservation": structure_pres,
        "shot_reorder_degree": reorder_degree,
        "character_substitution_strength": char_strength,
        "dramatic_tone_shift": tone_shift,
    }

    ordered = list(source_shots)
    if preserve:
        beat_cycle = allocate_by_beats(project, min(panel_count, len(source_shots)))
        selected = []
        for beat_id in beat_cycle:
            candidate = next((shot for shot in ordered if shot["beat_id"] == beat_id and shot not in selected), None)
            if candidate is None:
                candidate = next((shot for shot in ordered if shot not in selected), None)
            if candidate:
                selected.append(candidate)
        ordered = selected
    else:
        rotate = index % max(len(ordered), 1)
        ordered = ordered[rotate:] + ordered[:rotate]
        if index % 2 == 1:
            ordered = list(reversed(ordered))
        ordered = ordered[: min(panel_count, len(ordered))]

    panels = []
    new_shot_ids = []
    reused = []
    replaced = []
    for shot in ordered[:panel_count]:
        subject = rewrite_subject(shot, project, char_map)
        if subject != shot["main_subject"]:
            replaced.append(shot["shot_id"])
        reused.append(shot["shot_id"])
        beat = next((beat for beat in project["beats"] if beat["beat_id"] == shot["beat_id"]), None)
        panels.append(build_panel(shot, subject, beat["beat_type"] if beat else "hook", f"{creative_brief} Tone shift: {tone_shift}."))

    while len(panels) < panel_count:
        anchor = panels[-1] if panels else {
            "shot_size": "medium shot",
            "camera_angle": "eye-level",
            "camera_motion": "gentle camera drift",
            "composition": "centered framing",
            "lighting": "balanced natural lighting",
            "emotion": "story-forward",
            "beat": "payoff",
        }
        new_id = f"new_{index + 1:02d}_{len(new_shot_ids) + 1:02d}"
        new_shot_ids.append(new_id)
        panels.append(
            {
                "source_shot_id": None,
                "duration_target_seconds": 2,
                "shot_size": anchor["shot_size"],
                "camera_angle": anchor["camera_angle"],
                "camera_motion": "designed insert",
                "composition": anchor["composition"],
                "lighting": anchor["lighting"],
                "subject": "newly introduced remix beat",
                "action": "invent a bridge image that supports the new idea",
                "emotion": anchor["emotion"],
                "beat": anchor["beat"],
                "visual": "New shot designed to satisfy the remix brief.",
                "sound_note": "Bridge with music or a concise caption.",
                "purpose": "new creative insert",
                "prompt": f"Invent a new shot that supports the remix brief: {creative_brief}",
                "reframe_note_9x16": "Keep the key subject in the center vertical safe area.",
                "seedance_motion_hint": "Short connective move to bridge adjacent shots.",
                "story_description": "这一镜补入新的剧情信息，用来服务新的创意方向。",
                "change_description": "相比上一镜，这里主动加入新的叙事变化点。",
                "emotion_progression": "情绪在这里被重新拨高或重新转向。",
                "transition_bridge": "这一镜把新创意自然送向下一镜。",
                "information_revealed": "补入新的叙事信息。",
                "information_withheld": "仍保留最终揭示不完全说破。",
            }
        )

    variant = {
        "variant_id": f"variant_{index + 1:02d}",
        "creative_constraints": creative_brief,
        "target_aspect_ratio": target_aspect_ratio,
        "target_panel_count": panel_count,
        "reused_shot_ids": reused,
        "replaced_shot_ids": replaced,
        "new_shot_ids": new_shot_ids,
        "beat_preservation_score": round(structure_pres, 2),
        "diversity_vector": diversity_vector,
        "selected": False,
        "panels": panels,
    }
    return variant


def enforce_diversity(variants: list[dict], source_shots: list[dict], project: dict, char_map: dict[str, dict], creative_brief: str, preserve: bool, panel_count: int, target_aspect_ratio: str) -> list[dict]:
    for _ in range(2):
        changed = False
        for i in range(len(variants)):
            for j in range(i + 1, len(variants)):
                score = jaccard(set(variants[i]["reused_shot_ids"]), set(variants[j]["reused_shot_ids"]))
                if score >= 0.7:
                    variants[j] = build_variant(project, list(reversed(source_shots)), char_map, creative_brief, j + 1, False, panel_count, target_aspect_ratio)
                    changed = True
        if not changed:
            break
    return variants


def main() -> None:
    args = parse_args()
    random.seed(args.seed)
    project_dir = Path(args.project_dir)
    project = load_project(project_dir)
    creative_brief = read_creative_brief(args)
    char_map = build_character_map(project, args.character_mapping_file)
    source_shots = eligible_shots(project)
    panel_count = args.target_panel_count if args.target_panel_count and args.target_panel_count > 0 else len(source_shots)
    panel_count = max(1, panel_count)
    variants = [
        build_variant(project, source_shots, char_map, creative_brief, index, args.preserve_beat_skeleton, panel_count, args.target_aspect_ratio)
        for index in range(args.variant_count)
    ]
    variants = enforce_diversity(variants, source_shots, project, char_map, creative_brief, args.preserve_beat_skeleton, panel_count, args.target_aspect_ratio)

    remix_job = {
        "remix_job_id": f"remix_{len(project['remix_jobs']) + 1:02d}",
        "requested_variant_count": args.variant_count,
        "creative_constraints": creative_brief,
        "preserve_beat_skeleton": args.preserve_beat_skeleton,
        "target_aspect_ratio": args.target_aspect_ratio,
        "target_panel_count": panel_count,
        "character_mapping": char_map,
        "allowed_source_shots": [shot["shot_id"] for shot in source_shots],
        "generated_variants": variants,
    }
    project["remix_jobs"].append(remix_job)
    save_project(project_dir, project)
    save_json(project_dir / "reports" / "remix_diversity_report.json", {"variants": variants})
    print(f"Generated {len(variants)} remix variants.")


if __name__ == "__main__":
    main()
