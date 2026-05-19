from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from common import ensure_dir, save_json, save_project, slugify


SHOT_RE = re.compile(r"(?:\*\*)?(?:镜头|SHOT)\s*(\d+)[（(]?([\d\.:s\-– ]+)?[）)]?", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--story-file", default=None)
    parser.add_argument("--ideas-file", default=None)
    parser.add_argument("--story-text", default=None)
    parser.add_argument("--ideas-text", default=None)
    parser.add_argument("--mode", choices=["auto", "complete_story", "idea_fragments"], default="auto")
    parser.add_argument("--duration-seconds", type=float, default=30.0)
    parser.add_argument("--title", default=None)
    return parser.parse_args()


def read_input(args: argparse.Namespace) -> tuple[str, str]:
    if args.story_file:
        return Path(args.story_file).read_text(encoding="utf-8"), "complete_story"
    if args.ideas_file:
        return Path(args.ideas_file).read_text(encoding="utf-8"), "idea_fragments"
    if args.story_text:
        return args.story_text, "complete_story"
    if args.ideas_text:
        return args.ideas_text, "idea_fragments"
    raise ValueError("Provide --story-file/--story-text or --ideas-file/--ideas-text.")


def detect_mode(text: str, requested_mode: str, inferred_kind: str) -> str:
    if requested_mode != "auto":
        return requested_mode
    if inferred_kind != "complete_story":
        return inferred_kind
    if "镜头1" in text or "镜头 1" in text or "SHOT 1" in text.upper():
        return "complete_story"
    return "idea_fragments"


def extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            return line.lstrip("#").strip()
        if line.startswith("##"):
            return line.lstrip("#").strip()
    return fallback


def parse_time_range(raw: str | None, default_start: float, default_end: float) -> tuple[float, float]:
    if not raw:
        return default_start, default_end
    cleaned = raw.replace("–", "-").replace("—", "-").replace("s", "").replace("S", "")
    parts = [p.strip() for p in cleaned.split("-") if p.strip()]
    if len(parts) != 2:
        return default_start, default_end
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return default_start, default_end


def complete_story_outline(text: str, duration_seconds: float, title: str) -> dict[str, Any]:
    lines = [line.rstrip() for line in text.splitlines()]
    shot_blocks = []
    current = None
    for line in lines:
        match = SHOT_RE.search(line)
        if match:
            if current:
                shot_blocks.append(current)
            current = {
                "header": line.strip("* ").strip(),
                "index": int(match.group(1)),
                "time_raw": match.group(2),
                "body_lines": [],
            }
        elif current is not None:
            if line.strip() or current["body_lines"]:
                current["body_lines"].append(line.strip())
    if current:
        shot_blocks.append(current)

    if not shot_blocks:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        shot_count = min(10, max(6, len(paragraphs)))
        per = duration_seconds / shot_count
        shot_blocks = [
            {
                "header": f"镜头{i+1}",
                "index": i + 1,
                "time_raw": None,
                "body_lines": [paragraphs[min(i, len(paragraphs) - 1)] if paragraphs else "故事推进到下一步。"],
            }
            for i in range(shot_count)
        ]

    shots = []
    default_per = duration_seconds / len(shot_blocks)
    for i, block in enumerate(shot_blocks):
        start, end = parse_time_range(block["time_raw"], i * default_per, (i + 1) * default_per)
        body = " ".join(part for part in block["body_lines"] if part).strip()
        body = body or "故事在这一镜继续推进。"
        shots.append(
            {
                "shot_id": f"shot_{i + 1:03d}",
                "index": i + 1,
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
                "summary": body,
                "story_description": body,
                "change_description": "这一镜把上一镜建立的悬念或信息继续往前推进。",
                "emotion_progression": "情绪继续逼近更明确的理解或揭示。",
                "transition_bridge": "镜头结尾把注意力自然送到下一镜。",
                "information_revealed": body.split("。")[0] + ("。" if "。" in body else ""),
                "information_withheld": "仍保留最关键的解释或关系不完全说破。",
            }
        )

    theme_match = re.search(r"[\"“](.+?)[\"”]", text)
    question_match = re.findall(r"[^。！？!?]*[？?]", text)
    ending_state = shots[-1]["summary"] if shots else "故事停在一个有余味的结束状态。"

    return {
        "input_mode": "complete_story",
        "title": title,
        "logline": f"{title}通过一串逐步汇聚的镜头，把观众引向同一个真相。",
        "theme_line": theme_match.group(1) if theme_match else "每一条线索最终都指向同一个核心命题。",
        "central_question": question_match[-1].strip() if question_match else "这些线索最终揭示的真相是什么？",
        "reveal_or_twist": shots[-2]["summary"] if len(shots) > 1 else ending_state,
        "ending_state": ending_state,
        "beats": [],
        "shots": shots,
        "characters": [],
    }


def idea_fragments_outline(text: str, duration_seconds: float, title: str) -> dict[str, Any]:
    fragments = []
    for line in text.splitlines():
        stripped = line.strip(" -*\t")
        if stripped:
            fragments.append(stripped)
    if not fragments:
        fragments = ["神秘地点", "关键遗物", "被隐藏的真相", "最后的交付"]

    shots = []
    shot_count = 10
    per = duration_seconds / shot_count
    templates = [
        ("hook", f"先用地点或异样物件建立悬疑：{fragments[0]}."),
        ("hook", f"让人物带着未说破的意图进入场景：{fragments[min(1, len(fragments)-1)]}."),
        ("setup", "通过细节特写让线索开始出现，但不立即解释意义。"),
        ("setup", f"把另一个人物或物件推进来，形成新的关系张力：{fragments[min(2, len(fragments)-1)]}."),
        ("setup", "让多个线索开始汇聚，观众意识到它们可能有关联。"),
        ("turn", f"抛出真正改变理解方式的信息：{fragments[min(3, len(fragments)-1)]}."),
        ("climax", "把所有人或所有关键物件汇聚到同一个空间。"),
        ("climax", "让主角在沉默或极少对白中完成情绪认知变化。"),
        ("resolution", "拉远或静止，让观众看到关系已经被重新定义。"),
        ("resolution", "用一句主题句或最终图像收束全片。"),
    ]
    for i, (beat_type, summary) in enumerate(templates, start=1):
        shots.append(
            {
                "shot_id": f"shot_{i:03d}",
                "index": i,
                "start_seconds": round((i - 1) * per, 2),
                "end_seconds": round(i * per, 2),
                "summary": summary,
                "target_beat_type": beat_type,
                "story_description": summary,
                "change_description": "这一镜把前面的信息重新组织成新的理解方向。",
                "emotion_progression": "情绪从疑问逐步逼近更明确的揭示。",
                "transition_bridge": "在镜头结尾保留一个问题，把观众送到下一镜。",
                "information_revealed": summary,
                "information_withheld": "关键动机和最终真相仍留到后面。",
            }
        )

    return {
        "input_mode": "idea_fragments",
        "title": title,
        "logline": f"{title}把零散片段整理成一段完整的悬疑短故事。",
        "theme_line": "碎片化线索最终汇聚成同一个故事落点。",
        "central_question": "这些片段最终会拼成怎样的真相？",
        "reveal_or_twist": templates[5][1],
        "ending_state": templates[-1][1],
        "beats": [],
        "shots": shots,
        "characters": [],
    }


def build_beats_from_shots(outline: dict[str, Any], duration_seconds: float) -> list[dict[str, Any]]:
    mode = outline["input_mode"]
    if mode == "idea_fragments":
        beat_types = ["hook", "setup", "turn", "climax", "resolution"]
    else:
        if duration_seconds < 15:
            beat_types = ["hook", "payoff"]
        elif duration_seconds <= 45:
            beat_types = ["hook", "setup", "payoff"]
        else:
            beat_types = ["hook", "setup", "turn", "climax", "resolution"]
    shots = outline["shots"]
    chunk = max(1, len(shots) // len(beat_types))
    beats = []
    cursor = 0
    for idx, beat_type in enumerate(beat_types, start=1):
        if idx == len(beat_types):
            beat_shots = shots[cursor:]
        else:
            beat_shots = shots[cursor : cursor + chunk]
        cursor += len(beat_shots)
        start = beat_shots[0]["start_seconds"] if beat_shots else 0.0
        end = beat_shots[-1]["end_seconds"] if beat_shots else duration_seconds
        summary = " ".join(shot["summary"] for shot in beat_shots[:2]).strip()
        beats.append(
            {
                "beat_id": f"beat_{idx:02d}",
                "beat_type": beat_type,
                "what_happens": summary or "这一段继续推进故事。",
                "story_purpose": f"承担{beat_type}段落的叙事任务。",
                "emotional_shift": "情绪在这一段继续抬升并收紧注意力。",
                "transition_to_next": "用尚未说破的信息把观众送往下一段。",
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
            }
        )
    return beats


def ensure_project(project_dir: Path, title: str, duration_seconds: float) -> dict[str, Any]:
    project_path = project_dir / "derived" / "project.json"
    if project_path.exists():
        import json

        return json.loads(project_path.read_text(encoding="utf-8"))
    ensure_dir(project_dir / "derived")
    ensure_dir(project_dir / "exports")
    ensure_dir(project_dir / "reports")
    return {
        "project_name": slugify(title),
        "source_video": {
            "video_id": slugify(title),
            "source_type": "story_only",
            "source_path_or_url": None,
            "local_path": None,
            "duration_ms": int(duration_seconds * 1000),
            "aspect_ratio": "9:16",
            "width": None,
            "height": None,
            "language": "zh",
            "audio_present": False,
        },
        "beats": [],
        "shots": [],
        "characters": [],
        "remix_jobs": [],
        "deliverables": {},
        "analysis_notes": [],
    }


def populate_synthetic_shots(project: dict[str, Any], outline: dict[str, Any], beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    beat_by_type = {beat["beat_type"]: beat["beat_id"] for beat in beats}
    shots = []
    for shot in outline["shots"]:
        beat_type = shot.get("target_beat_type")
        if not beat_type:
            for beat in beats:
                if beat["start_seconds"] <= shot["start_seconds"] < beat["end_seconds"] + 0.001:
                    beat_type = beat["beat_type"]
                    break
        beat_id = beat_by_type.get(beat_type, beats[min(len(beats) - 1, max(0, shot["index"] - 1))]["beat_id"])
        shots.append(
            {
                "shot_id": shot["shot_id"],
                "start_ms": int(shot["start_seconds"] * 1000),
                "end_ms": int(shot["end_seconds"] * 1000),
                "duration_ms": int((shot["end_seconds"] - shot["start_seconds"]) * 1000),
                "beat_id": beat_id,
                "boundary_confidence": 1.0,
                "transcript_excerpt": "",
                "analysis_mode": "story_outline",
                "merged_with": [],
                "context_summary": "来自故事补全过程的合成镜头。",
                "character_ids": [],
                "shot_size": "中景",
                "camera_angle": "平视",
                "camera_motion": "缓慢推进",
                "composition": "中心构图",
                "lighting": "电影感雾光",
                "main_subject": "当前叙事主体",
                "action": "把当前剧情信息推到前景",
                "emotion": "稳步推进悬念",
                "story_function": "故事推进镜头",
                "pacing_role": "过渡承接",
                "dependency_level": "medium",
                "reusability_tags": ["standalone", "reskinnable", "beat_swappable"],
                "reframe_note_9x16": "竖版保持主体在中心安全区。",
                "reframe_note_16x9": "横版补足环境空间强化场面关系。",
                "story_description": shot["story_description"],
                "change_description": shot["change_description"],
                "emotion_progression": shot["emotion_progression"],
                "transition_bridge": shot["transition_bridge"],
                "information_revealed": shot["information_revealed"],
                "information_withheld": shot["information_withheld"],
            }
        )
    return shots


def main() -> None:
    args = parse_args()
    raw_text, inferred_kind = read_input(args)
    fallback_title = args.title or "story-project"
    title = extract_title(raw_text, fallback_title)
    mode = detect_mode(raw_text, args.mode, inferred_kind)
    project_dir = Path(args.project_dir)
    duration_seconds = float(args.duration_seconds)

    if mode == "complete_story":
        outline = complete_story_outline(raw_text, duration_seconds, title)
    else:
        outline = idea_fragments_outline(raw_text, duration_seconds, title)
    beats = build_beats_from_shots(outline, duration_seconds)
    outline["beats"] = beats

    project = ensure_project(project_dir, title, duration_seconds)
    project["story_outline"] = outline
    project["story_core"] = {
        "logline": outline["logline"],
        "theme_line": outline["theme_line"],
        "central_question": outline["central_question"],
        "reveal_or_twist": outline["reveal_or_twist"],
        "ending_state": outline["ending_state"],
    }
    if not project.get("shots"):
        project["shots"] = populate_synthetic_shots(project, outline, beats)
    if not project.get("beats"):
        project["beats"] = [
            {
                "beat_id": beat["beat_id"],
                "beat_type": beat["beat_type"],
                "start_ms": int(beat["start_seconds"] * 1000),
                "end_ms": int(beat["end_seconds"] * 1000),
                "objective": beat["story_purpose"],
                "emotional_direction": beat["emotional_shift"],
                "pacing_note": "故事补全过程生成的默认节奏。",
                "turning_point_note": beat["what_happens"],
                "schema_variant": "story_only",
                "audio_beat_aligned": False,
                "key_shot_ids": [],
                "reusability_note": "可作为后续镜头重组的结构骨架。",
                "what_happens": beat["what_happens"],
                "story_purpose": beat["story_purpose"],
                "emotional_shift": beat["emotional_shift"],
                "transition_to_next": beat["transition_to_next"],
            }
            for beat in beats
        ]

    save_project(project_dir, project)
    save_json(project_dir / "derived" / "story_outline.json", outline)
    save_json(project_dir / "derived" / "story_core.json", project["story_core"])
    print(project_dir.resolve())


if __name__ == "__main__":
    main()
