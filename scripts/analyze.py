from __future__ import annotations

import argparse
import statistics
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from common import ensure_dir, infer_schema_variant, load_json, load_project, load_toml, save_json, save_project, skill_root


BEAT_TYPE_LABELS = {
    "hook": "钩子",
    "setup": "铺陈",
    "turn": "转折",
    "climax": "高潮",
    "resolution": "收束",
    "payoff": "落点",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--override-file", default=None, help="Optional JSON file to patch beats/shots/characters.")
    return parser.parse_args()


def choose_analysis_mode(duration_s: float, shot_count: int, shot_duration_s: float, short_threshold: float) -> tuple[str, list[str]]:
    if shot_duration_s < short_threshold:
        return "merged_context", []
    if duration_s <= 180 and shot_count <= 60:
        return "whole_video", []
    return "chunk_segment", []


def load_image(path: str | None) -> np.ndarray | None:
    if not path:
        return None
    frame = cv2.imread(path)
    if frame is None:
        return None
    return frame


def detect_faces(frame: np.ndarray | None) -> list[tuple[int, int, int, int]]:
    if frame is None:
        return []
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(32, 32))
    return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]


def composition_label(frame: np.ndarray | None) -> str:
    if frame is None:
        return "中心稳定构图"
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160)
    ys, xs = np.where(edges > 0)
    if len(xs) == 0:
        return "中心稳定构图"
    center = float(xs.mean()) / frame.shape[1]
    if center < 0.4:
        return "主体偏左构图"
    if center > 0.6:
        return "主体偏右构图"
    return "中心构图"


def lighting_label(frame: np.ndarray | None) -> str:
    if frame is None:
        return "均衡自然光"
    brightness = float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean()) / 255.0
    if brightness < 0.35:
        return "低调雾感光"
    if brightness > 0.7:
        return "高调明亮光"
    return "均衡自然光"


def shot_size_label(frame: np.ndarray | None, faces: list[tuple[int, int, int, int]]) -> str:
    if frame is None:
        return "中景"
    if faces:
        _, _, w, h = max(faces, key=lambda item: item[2] * item[3])
        area_ratio = (w * h) / (frame.shape[0] * frame.shape[1])
        if area_ratio > 0.12:
            return "特写"
        if area_ratio > 0.05:
            return "中景"
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160)
    density = float(np.count_nonzero(edges)) / edges.size
    return "中景" if density > 0.12 else "远景"


def camera_motion_label(first: np.ndarray | None, middle: np.ndarray | None, hero: np.ndarray | None) -> str:
    if first is None or middle is None or hero is None:
        return "缓慢推进"
    diffs = []
    for a, b in ((first, middle), (middle, hero)):
        ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
        gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
        diffs.append(float(cv2.absdiff(ga, gb).mean()))
    movement = statistics.mean(diffs)
    if movement < 8:
        return "静止"
    if movement < 18:
        return "缓慢推进"
    return "主动运动"


def infer_emotion(beat_type: str, motion: str, lighting: str) -> str:
    if beat_type == "hook":
        return "迅速建立悬念"
    if beat_type in {"climax", "payoff"} and motion != "静止":
        return "情绪抬升并逼近揭示"
    if "低调" in lighting:
        return "压低情绪并维持不安"
    return "稳住情绪并推进信息"


def infer_story_function(beat_type: str, shot_index: int, beat_shot_count: int) -> str:
    beat_label = BEAT_TYPE_LABELS.get(beat_type, beat_type)
    if shot_index == 0:
        return f"{beat_label}的进入镜头"
    if shot_index == beat_shot_count - 1:
        return f"{beat_label}的收束镜头"
    return f"{beat_label}的推进镜头"


def infer_pacing_role(duration_ms: int, median_duration: float) -> str:
    if duration_ms < median_duration * 0.75:
        return "加速节奏"
    if duration_ms > median_duration * 1.4:
        return "停顿蓄力"
    return "过渡承接"


def infer_reusability_tags(shot: dict[str, Any]) -> list[str]:
    tags = ["standalone"]
    if shot["camera_motion"] != "静止":
        tags.append("reskinnable")
    if "推进镜头" in shot["story_function"]:
        tags.append("beat_swappable")
    if shot["transcript_excerpt"]:
        tags.append("dialog_bound")
    if shot["analysis_mode"] == "merged_context":
        tags.append("sequence_bound")
    return sorted(set(tags))


def reframe_notes(composition: str) -> tuple[str, str]:
    if "偏左" in composition:
        return ("竖版裁切时向左保留主体。", "横版时补右侧留白平衡构图。")
    if "偏右" in composition:
        return ("竖版裁切时向右保留主体。", "横版时补左侧留白平衡构图。")
    return ("竖版保持主体在中心安全区。", "横版保持头顶空间和中心平衡。")


def summarize_revealed(text: str) -> str:
    if not text:
        return "这一镜主要提供氛围或位置关系。"
    text = text.strip().replace("\n", " ")
    for sep in ("。", "；", ".", "!", "？", "?"):
        if sep in text:
            return text.split(sep)[0].strip() + "。"
    return text[:60].strip() + ("。" if len(text) > 60 else "")


def summarize_withheld(beat_type: str) -> str:
    mapping = {
        "hook": "暂时不解释真正的危险或秘密来源。",
        "setup": "只展示线索，不立即说明它们之间的关系。",
        "turn": "保留最关键的动机或真相，等待下一步揭示。",
        "climax": "让观众先感受到结果，再补足完整解释。",
        "resolution": "不把所有余味说尽，给结尾留下回响。",
        "payoff": "先完成落点，再保留更深一层意味。",
    }
    return mapping.get(beat_type, "保留关键信息以维持悬念。")


def infer_story_input_mode(project: dict[str, Any]) -> str:
    story_outline = project.get("story_outline", {})
    mode = story_outline.get("input_mode")
    if mode:
        return mode
    return "reference_video"


def build_story_core(project: dict[str, Any]) -> dict[str, str]:
    if project.get("story_core"):
        return project["story_core"]
    story_outline = project.get("story_outline", {})
    title = story_outline.get("title") or project["source_video"]["video_id"]
    central_question = story_outline.get("central_question") or "这段影像真正想把观众带向什么真相？"
    theme_line = story_outline.get("theme_line") or "所有镜头都服务于一次逐步逼近的揭示。"
    reveal_or_twist = story_outline.get("reveal_or_twist") or "真正的意义在最后一段才被完整理解。"
    ending_state = story_outline.get("ending_state") or "角色和观众一起抵达更安静但更重的认知。"
    logline = story_outline.get("logline") or f"{title}通过一连串镜头把观众引向同一个秘密。"
    return {
        "logline": logline,
        "theme_line": theme_line,
        "central_question": central_question,
        "reveal_or_twist": reveal_or_twist,
        "ending_state": ending_state,
    }


def build_outline_defaults(project: dict[str, Any], beats: list[dict[str, Any]]) -> dict[str, Any]:
    outline = project.get("story_outline", {})
    if outline:
        return outline
    beat_summaries = []
    for beat in beats:
        beat_summaries.append(
            {
                "beat_id": beat["beat_id"],
                "beat_type": beat["beat_type"],
                "what_happens": f"{BEAT_TYPE_LABELS.get(beat['beat_type'], beat['beat_type'])}段落逐步向核心秘密靠近。",
                "story_purpose": f"用{BEAT_TYPE_LABELS.get(beat['beat_type'], beat['beat_type'])}来推进主命题。",
                "emotional_shift": "从观察进入更强的意识变化。",
                "transition_to_next": "通过信息递进把观众送到下一个段落。",
            }
        )
    return {
        "input_mode": infer_story_input_mode(project),
        "title": project["source_video"]["video_id"],
        "logline": f"{project['source_video']['video_id']}通过一段逐步汇聚的影像把观众引向最终揭示。",
        "theme_line": "表面上的线索最终汇聚成同一个真相。",
        "central_question": "这些镜头最终要揭开什么？",
        "reveal_or_twist": "真相在结尾才被完整理解。",
        "ending_state": "故事停在认知变化后的余味上。",
        "beats": beat_summaries,
        "shots": [],
    }


def build_beats(duration_ms: int, shots: list[dict[str, Any]], audio_beats: list[int], story_outline: dict[str, Any]) -> list[dict[str, Any]]:
    duration_s = duration_ms / 1000.0
    schema = infer_schema_variant(duration_s)
    if schema == "2_beat":
        beat_types = ["hook", "payoff"]
        ratios = [0.55, 0.45]
    elif schema == "3_beat":
        beat_types = ["hook", "setup", "payoff"]
        ratios = [0.34, 0.38, 0.28]
    else:
        beat_types = ["hook", "setup", "turn", "climax", "resolution"]
        ratios = [0.15, 0.25, 0.2, 0.25, 0.15]

    boundaries = [0]
    cursor = 0
    for ratio in ratios[:-1]:
        cursor += int(duration_ms * ratio)
        boundaries.append(cursor)
    boundaries.append(duration_ms)

    outline_beats = {item.get("beat_type"): item for item in story_outline.get("beats", [])}
    beats = []
    for idx, beat_type in enumerate(beat_types):
        start_ms = boundaries[idx]
        end_ms = boundaries[idx + 1]
        key_shots = [s["shot_id"] for s in shots if s["start_ms"] < end_ms and s["end_ms"] > start_ms]
        beat_beats = [b for b in audio_beats if start_ms <= b <= end_ms]
        outline = outline_beats.get(beat_type, {})
        beats.append(
            {
                "beat_id": f"beat_{idx + 1:02d}",
                "beat_type": beat_type,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "objective": {
                    "hook": "用最强的悬念或视觉钩子把观众拉进来。",
                    "setup": "建立人物关系、信息层级和故事方向。",
                    "turn": "抛出真正改变理解方式的转折点。",
                    "climax": "把情绪和信息推到最集中最有压迫感的位置。",
                    "resolution": "让观众在更安静的状态下理解最终落点。",
                    "payoff": "完成前面铺垫的情绪和信息回收。",
                }[beat_type],
                "emotional_direction": {
                    "hook": "迅速建立好奇和不安",
                    "setup": "把注意力从好奇推进到判断",
                    "turn": "让理解方式开始改变",
                    "climax": "把情绪推向最强峰值",
                    "resolution": "留下沉静但有余味的结束状态",
                    "payoff": "让前面的铺垫获得明确落点",
                }[beat_type],
                "pacing_note": "快节奏切换形成压迫感" if len(key_shots) >= 3 else "用少量镜头稳住注意力",
                "turning_point_note": f"{BEAT_TYPE_LABELS.get(beat_type, beat_type)}围绕 {key_shots[0] if key_shots else 'n/a'} 展开。",
                "schema_variant": schema,
                "audio_beat_aligned": bool(beat_beats),
                "key_shot_ids": key_shots[:3],
                "reusability_note": "这一段可作为重组时的结构锚点。" if key_shots else "缺少可复用镜头。",
                "what_happens": outline.get("what_happens") or f"{BEAT_TYPE_LABELS.get(beat_type, beat_type)}阶段逐步把观众推向同一个秘密。",
                "story_purpose": outline.get("story_purpose") or f"通过{BEAT_TYPE_LABELS.get(beat_type, beat_type)}承担结构推进。",
                "emotional_shift": outline.get("emotional_shift") or "情绪从观察进入更明确的判断。",
                "transition_to_next": outline.get("transition_to_next") or "让观众带着尚未说破的信息进入下一段。",
            }
        )
    return beats


def cluster_characters(project: dict[str, Any]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    next_id = 1
    for shot in project["shots"]:
        frame = load_image(shot.get("frame_hero_path"))
        faces = detect_faces(frame)
        shot["character_ids"] = shot.get("character_ids", [])
        if not faces:
            continue
        faces = sorted(faces, key=lambda item: item[2] * item[3], reverse=True)[:2]
        for face in faces:
            x, y, w, h = face
            crop = frame[y : y + h, x : x + w]
            if crop.size == 0:
                continue
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            hist = cv2.calcHist([gray], [0], None, [16], [0, 256]).flatten()
            hist = hist / max(hist.sum(), 1.0)
            matched = None
            for cluster in clusters:
                score = float(cv2.compareHist(hist.astype(np.float32), np.array(cluster["hist"], dtype=np.float32), cv2.HISTCMP_CORREL))
                if score > 0.88:
                    matched = cluster
                    break
            if matched is None:
                char_id = f"char_{next_id:02d}"
                next_id += 1
                matched = {
                    "character_id": char_id,
                    "source_role_name": char_id,
                    "narrative_function": "主角色候选",
                    "emotion_profile": [],
                    "beat_presence": [],
                    "evidence_frames": [],
                    "identity_description_tokens": [],
                    "human_confirmation_required": True,
                    "human_confirmed": False,
                    "replacement_status": "unmapped",
                    "replacement_target": None,
                    "hist": hist.tolist(),
                    "shot_ids": [],
                }
                clusters.append(matched)
            matched["evidence_frames"].append({"shot_id": shot["shot_id"], "frame_path": shot.get("frame_hero_path")})
            matched["shot_ids"].append(shot["shot_id"])
            matched["identity_description_tokens"] = sorted(set(matched["identity_description_tokens"]) | {"正脸", shot.get("shot_size", "中景")})
            shot["character_ids"].append(matched["character_id"])

    cleaned = []
    for cluster in clusters:
        cluster["narrative_function"] = "主角色候选" if len(cluster["shot_ids"]) >= 2 else "辅助角色候选"
        cluster.pop("hist", None)
        cluster["shot_ids"] = sorted(set(cluster["shot_ids"]))
        cluster["identity_description_tokens"] = sorted(set(cluster["identity_description_tokens"]))
        cleaned.append(cluster)
    return cleaned


def write_character_review(project_dir: Path, project: dict[str, Any]) -> str:
    path = project_dir / "derived" / "characters_to_confirm.md"
    lines = ["# Characters To Confirm", ""]
    if not project["characters"]:
        lines.append("未检测到明确的人脸候选角色。若后续要做角色替换，请手动补充角色。")
    for char in project["characters"]:
        lines.extend(
            [
                f"## {char['character_id']}",
                f"- Proposed name: `{char['source_role_name']}`",
                f"- Narrative function: {char['narrative_function']}",
                f"- Tokens: {', '.join(char['identity_description_tokens']) or 'n/a'}",
                f"- Evidence shots: {', '.join(item['shot_id'] for item in char['evidence_frames'][:5])}",
                "",
            ]
        )
    ensure_dir(path.parent)
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path.resolve())


def story_outline_shots(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item.get("shot_id"): item for item in project.get("story_outline", {}).get("shots", []) if item.get("shot_id")}


def derive_story_fields_for_shot(shot: dict[str, Any], beat: dict[str, Any] | None, previous_shot: dict[str, Any] | None, outline_shot: dict[str, Any] | None) -> dict[str, str]:
    if outline_shot:
        return {
            "story_description": outline_shot.get("story_description") or outline_shot.get("summary") or "这一镜承接当前剧情推进。",
            "change_description": outline_shot.get("change_description") or "这一镜在上一镜基础上推进信息。",
            "emotion_progression": outline_shot.get("emotion_progression") or "情绪继续向更明确的理解推进。",
            "transition_bridge": outline_shot.get("transition_bridge") or "这一镜把注意力引到下一镜。",
            "information_revealed": outline_shot.get("information_revealed") or summarize_revealed(outline_shot.get("story_description", "")),
            "information_withheld": outline_shot.get("information_withheld") or summarize_withheld(beat["beat_type"] if beat else "setup"),
        }

    subject = shot.get("main_subject", "主体")
    beat_label = BEAT_TYPE_LABELS.get(beat["beat_type"], beat["beat_type"]) if beat else "剧情"
    previous_subject = previous_shot.get("main_subject") if previous_shot else None
    change = (
        f"相比上一镜，视线从{previous_subject}转向{subject}，让信息重心发生移动。"
        if previous_subject and previous_subject != subject
        else "相比上一镜，镜头把同一信息继续向前推一步。"
    )
    story_description = (
        f"这一镜聚焦{subject}，通过{shot.get('shot_size', '中景')}和{shot.get('camera_motion', '缓慢推进')}把{beat_label}阶段的关键信息推到前景。"
    )
    return {
        "story_description": story_description,
        "change_description": change,
        "emotion_progression": f"这一镜让情绪从上一镜继续朝“{shot.get('emotion', '推进理解')}”方向累积。",
        "transition_bridge": f"镜头在结尾把观众注意力挂到下一镜，继续完成{beat_label}段落的推进。",
        "information_revealed": summarize_revealed(story_description),
        "information_withheld": summarize_withheld(beat["beat_type"] if beat else "setup"),
    }


def build_generated_characters_from_outline(project: dict[str, Any]) -> list[dict[str, Any]]:
    roles = project.get("story_outline", {}).get("characters", [])
    characters = []
    for index, role in enumerate(roles, start=1):
        characters.append(
            {
                "character_id": role.get("character_id") or f"char_{index:02d}",
                "source_role_name": role.get("source_role_name") or role.get("name") or f"char_{index:02d}",
                "narrative_function": role.get("narrative_function") or "故事角色",
                "emotion_profile": role.get("emotion_profile", []),
                "beat_presence": role.get("beat_presence", []),
                "evidence_frames": [],
                "identity_description_tokens": role.get("identity_description_tokens", []),
                "human_confirmation_required": True,
                "human_confirmed": False,
                "replacement_status": "unmapped",
                "replacement_target": None,
            }
        )
    return characters


def main() -> None:
    args = parse_args()
    project_dir = Path(args.project_dir)
    project = load_project(project_dir)
    config = load_toml(skill_root() / "config" / "default.toml")
    short_threshold = float(config["analysis"]["short_shot_merge_seconds"])
    duration_ms = int(project["source_video"]["duration_ms"])
    duration_s = duration_ms / 1000.0
    shot_count = len(project["shots"])
    audio_beats = project.get("audio_analysis", {}).get("beats_ms", [])

    preliminary_outline = build_outline_defaults(project, [])
    beats = build_beats(duration_ms, project["shots"], audio_beats, preliminary_outline)
    project["story_outline"] = build_outline_defaults(project, beats)
    project["story_core"] = build_story_core(project)
    beats = build_beats(duration_ms, project["shots"], audio_beats, project["story_outline"])
    project["beats"] = beats

    shot_to_beat: dict[str, str] = {}
    for beat in beats:
        for shot in project["shots"]:
            if shot["start_ms"] < beat["end_ms"] and shot["end_ms"] > beat["start_ms"]:
                shot_to_beat.setdefault(shot["shot_id"], beat["beat_id"])

    median_duration = statistics.median([shot["duration_ms"] for shot in project["shots"]]) if project["shots"] else 1000
    outline_shots = story_outline_shots(project)
    previous_shot = None
    for shot in project["shots"]:
        beat_id = shot_to_beat.get(shot["shot_id"])
        beat = next((b for b in beats if b["beat_id"] == beat_id), beats[0] if beats else None)
        shot["beat_id"] = beat_id
        mode, merged = choose_analysis_mode(duration_s, shot_count, shot["duration_ms"] / 1000.0, short_threshold)
        shot["analysis_mode"] = mode
        shot["merged_with"] = merged
        first = load_image(shot.get("frame_first_path"))
        middle = load_image(shot.get("frame_middle_path"))
        hero = load_image(shot.get("frame_hero_path"))
        faces = detect_faces(hero)
        shot["shot_size"] = shot.get("shot_size") or shot_size_label(hero, faces)
        shot["camera_angle"] = shot.get("camera_angle") or ("平视" if faces else "观察机位")
        shot["camera_motion"] = shot.get("camera_motion") or camera_motion_label(first, middle, hero)
        shot["composition"] = shot.get("composition") or composition_label(hero)
        shot["lighting"] = shot.get("lighting") or lighting_label(hero)
        shot["main_subject"] = shot.get("main_subject") or ("人物主体" if faces else "主要画面主体")
        shot["action"] = shot.get("action") or ("动作变化被推进" if shot["camera_motion"] != "静止" else "静止中积累信息")
        shot["emotion"] = shot.get("emotion") or (infer_emotion(beat["beat_type"], shot["camera_motion"], shot["lighting"]) if beat else "中性")
        beat_shots = [s for s in project["shots"] if s.get("beat_id") == beat_id]
        shot["story_function"] = shot.get("story_function") or (infer_story_function(beat["beat_type"], beat_shots.index(shot), len(beat_shots)) if beat else "辅助信息镜头")
        shot["pacing_role"] = shot.get("pacing_role") or infer_pacing_role(shot["duration_ms"], median_duration)
        shot["dependency_level"] = shot.get("dependency_level") or ("high" if mode == "merged_context" else ("medium" if shot.get("transcript_excerpt") else "low"))
        shot["reusability_tags"] = shot.get("reusability_tags") or infer_reusability_tags(shot)
        shot["reframe_note_9x16"], shot["reframe_note_16x9"] = shot.get("reframe_note_9x16"), shot.get("reframe_note_16x9")
        if not shot["reframe_note_9x16"] or not shot["reframe_note_16x9"]:
            shot["reframe_note_9x16"], shot["reframe_note_16x9"] = reframe_notes(shot["composition"])
        shot["context_summary"] = shot.get("context_summary") or (f"发生在{BEAT_TYPE_LABELS.get(beat['beat_type'], beat['beat_type'])}段落中，用来承接前后镜头。" if beat else "独立镜头上下文。")
        story_fields = derive_story_fields_for_shot(shot, beat, previous_shot, outline_shots.get(shot["shot_id"]))
        shot.update(story_fields)
        previous_shot = shot

    if any(shot.get("frame_hero_path") for shot in project["shots"]):
        project["characters"] = cluster_characters(project)
    elif project.get("story_outline", {}).get("characters"):
        project["characters"] = build_generated_characters_from_outline(project)
    else:
        project["characters"] = []

    for char in project["characters"]:
        char["beat_presence"] = sorted(
            {
                shot["beat_id"]
                for shot in project["shots"]
                if char["character_id"] in shot.get("character_ids", [])
            }
        ) or char.get("beat_presence", [])
        char["emotion_profile"] = sorted(
            {
                shot["emotion"]
                for shot in project["shots"]
                if char["character_id"] in shot.get("character_ids", [])
            }
        ) or char.get("emotion_profile", [])

    review_path = write_character_review(project_dir, project)
    project["deliverables"]["characters_to_confirm_path"] = review_path

    if args.override_file:
        override = load_json(Path(args.override_file), {})
        for key in ("story_core", "story_outline", "beats", "shots", "characters"):
            if key in override:
                project[key] = override[key]

    save_project(project_dir, project)
    save_json(project_dir / "derived" / "beats.json", project["beats"])
    save_json(project_dir / "derived" / "characters.json", project["characters"])
    save_json(project_dir / "derived" / "story_core.json", project["story_core"])
    save_json(project_dir / "derived" / "story_outline.json", project["story_outline"])
    print(f"Analyzed {len(project['shots'])} shots and {len(project['characters'])} character candidates.")


if __name__ == "__main__":
    main()
