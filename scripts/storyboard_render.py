from __future__ import annotations

from copy import deepcopy

from common import skill_root, template_env


def format_seconds(seconds: float) -> str:
    return f"{seconds:.2f}s"


def build_script_line(panel: dict) -> str:
    story = (panel.get("story_description") or f"{panel['subject']}在画面中推进当前剧情。").strip()
    change = (panel.get("change_description") or "").strip()
    emotion = (panel.get("emotion_progression") or "").strip()
    transition = (panel.get("transition_bridge") or "").strip()
    sound_note = (panel.get("sound_note") or "").strip()

    sentences = [story]
    if change:
        sentences.append(change)
    if emotion:
        sentences.append(emotion)
    if transition:
        sentences.append(transition)
    if sound_note:
        sentences.append(f"声音上，{sound_note}")

    paragraph = " ".join(sentence.strip() for sentence in sentences if sentence.strip())
    return paragraph.replace("。。", "。")


def build_storyboard_panels(variant: dict) -> tuple[list[dict], float]:
    panels: list[dict] = []
    cursor_seconds = 0.0
    for idx, panel in enumerate(variant["panels"], start=1):
        row = deepcopy(panel)
        row["index"] = idx
        duration_seconds = float(panel["duration_target_seconds"])
        row["start_timecode"] = format_seconds(cursor_seconds)
        cursor_seconds += duration_seconds
        row["end_timecode"] = format_seconds(cursor_seconds)
        row["script_line"] = build_script_line(row)
        row["final_storyboard_paragraph"] = row["script_line"]
        panels.append(row)
    return panels, cursor_seconds


def build_intro_line(variant: dict, total_seconds: float) -> str:
    return (
        f"{max(0.01, total_seconds):.2f} 秒分镜短片，目标画幅 {variant['target_aspect_ratio']}。"
        f"创意方向：{variant['creative_constraints']}"
    )


def build_renderable_variant(variant: dict) -> dict:
    renderable = deepcopy(variant)
    panels, total_seconds = build_storyboard_panels(renderable)
    renderable["panels"] = panels
    renderable["intro_line"] = build_intro_line(renderable, total_seconds)
    return renderable


def render_shot_prompts(variant: dict) -> tuple[str, dict]:
    renderable = build_renderable_variant(variant)
    env = template_env(skill_root())
    return env.get_template("shot_prompts.j2").render(variant=renderable), renderable
