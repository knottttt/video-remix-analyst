from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import load_json, load_project, save_project, skill_root
from compile_beat_sheet import build_prompt_characters, load_style_profile, render_beat_sheet_prompt
from storyboard_render import render_shot_prompts

RUBRIC_FILES = {
    "storyboard_pack": "review_rubric_storyboard_pack.json",
    "beat_sheet_document": "review_rubric_beat_sheet_document.json",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--variant-id", required=True)
    parser.add_argument("--mode", choices=sorted(RUBRIC_FILES), default="storyboard_pack")
    parser.add_argument("--model", default="claude-haiku-4-5")
    return parser.parse_args(argv)


def find_variant(project: dict, variant_id: str) -> tuple[dict, dict]:
    for job in project["remix_jobs"]:
        for variant in job["generated_variants"]:
            if variant["variant_id"] == variant_id:
                return job, variant
    raise KeyError(f"Variant not found: {variant_id}")


def load_rubric(mode: str) -> dict[str, Any]:
    return load_json(skill_root() / "config" / RUBRIC_FILES[mode], {})


def render_reviewed_text(mode: str, remix_job: dict[str, Any], variant: dict[str, Any]) -> str:
    if mode == "storyboard_pack":
        reviewed_text, _ = render_shot_prompts(variant)
        return reviewed_text

    style_profile = load_style_profile("pixar_3d")
    prompt_characters = build_prompt_characters(remix_job, None)
    reviewed_text, _ = render_beat_sheet_prompt(variant, prompt_characters, style_profile, panel_count=4)
    return reviewed_text


def _match_pattern(text: str, pattern: str) -> bool:
    return pattern.lower() in text.lower()


def run_rule_checks(text: str, rubric: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    required_missing = []
    forbidden_hits = []
    manual_hits = []

    for item in rubric.get("required_patterns", []):
        if not _match_pattern(text, item["pattern"]):
            required_missing.append(item)
    for item in rubric.get("forbidden_patterns", []):
        if _match_pattern(text, item["pattern"]):
            forbidden_hits.append(item)
    for item in rubric.get("manual_review_triggers", []):
        if _match_pattern(text, item["pattern"]):
            manual_hits.append(item)

    return {
        "required_missing": required_missing,
        "forbidden_hits": forbidden_hits,
        "manual_review_hits": manual_hits,
    }


def build_system_prompt(rubric: dict[str, Any]) -> str:
    return (
        "You review storyboard prompt text in isolated context.\n"
        "Only use the rubric and the provided text.\n"
        "Do not infer any hidden project intent.\n"
        "Return strict JSON with keys: verdict, issues, suggestions, human_questions.\n"
        "Allowed verdict values: PASS, REJECT, NEEDS_HUMAN.\n"
        "NEEDS_HUMAN is required when the choice depends on taste, ambiguity, or conflicting signals.\n"
        f"Rubric:\n{json.dumps(rubric, ensure_ascii=False, indent=2)}"
    )


def build_user_payload(text: str, rule_flags: dict[str, Any]) -> str:
    return json.dumps(
        {
            "candidate_prompt_text": text,
            "rule_flags": rule_flags,
            "task": "Review this text against the rubric and return only JSON.",
        },
        ensure_ascii=False,
        indent=2,
    )


def call_anthropic_review(model: str, system_prompt: str, user_payload: str) -> dict[str, Any]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    body = json.dumps(
        {
            "model": model,
            "max_tokens": 600,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_payload}],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))

    text_chunks = []
    for item in payload.get("content", []):
        if item.get("type") == "text":
            text_chunks.append(item.get("text", ""))
    raw_text = "\n".join(text_chunks).strip()
    if not raw_text:
        raise RuntimeError("Anthropic response did not contain text content")
    return json.loads(raw_text)


def coerce_review_payload(payload: dict[str, Any]) -> dict[str, Any]:
    verdict = str(payload.get("verdict", "NEEDS_HUMAN")).upper()
    if verdict not in {"PASS", "REJECT", "NEEDS_HUMAN"}:
        verdict = "NEEDS_HUMAN"
    return {
        "verdict": verdict,
        "issues": [str(item) for item in payload.get("issues", [])],
        "suggestions": [str(item) for item in payload.get("suggestions", [])],
        "human_questions": [str(item) for item in payload.get("human_questions", [])],
    }


def summarize_followup(final_result: dict[str, Any]) -> str:
    parts = []
    if final_result["issues"]:
        parts.append("Issues: " + " | ".join(final_result["issues"]))
    if final_result["suggestions"]:
        parts.append("Suggestions: " + " | ".join(final_result["suggestions"]))
    if final_result["human_questions"]:
        parts.append("Human questions: " + " | ".join(final_result["human_questions"]))
    return "\n".join(parts).strip()


def merge_results(rule_flags: dict[str, Any], semantic_result: dict[str, Any] | None, semantic_error: str | None) -> dict[str, Any]:
    issues = []
    suggestions = []
    human_questions = []

    for item in rule_flags["required_missing"]:
        issues.append(f"Missing required pattern `{item['pattern']}`: {item['description']}")
    for item in rule_flags["forbidden_hits"]:
        issues.append(f"Forbidden pattern `{item['pattern']}` found: {item['description']}")
    for item in rule_flags["manual_review_hits"]:
        human_questions.append(item["review_question"])

    if semantic_result:
        issues.extend(semantic_result["issues"])
        suggestions.extend(semantic_result["suggestions"])
        human_questions.extend(semantic_result["human_questions"])

    if semantic_error:
        human_questions.append(f"Semantic review unavailable: {semantic_error}")

    hard_fail = bool(rule_flags["required_missing"] or rule_flags["forbidden_hits"])
    manual_needed = bool(rule_flags["manual_review_hits"] or semantic_error)
    semantic_verdict = semantic_result["verdict"] if semantic_result else "NEEDS_HUMAN"

    if hard_fail:
        verdict = "REJECT"
    elif manual_needed:
        verdict = "NEEDS_HUMAN"
    elif semantic_verdict == "REJECT":
        verdict = "REJECT"
    elif semantic_verdict == "NEEDS_HUMAN":
        verdict = "NEEDS_HUMAN"
    else:
        verdict = "PASS"

    return {
        "verdict": verdict,
        "rule_flags": rule_flags,
        "issues": issues,
        "suggestions": suggestions,
        "human_questions": human_questions,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project_dir = Path(args.project_dir)
    project = load_project(project_dir)
    remix_job, variant = find_variant(project, args.variant_id)
    reviewed_text = render_reviewed_text(args.mode, remix_job, variant)
    rubric = load_rubric(args.mode)
    rule_flags = run_rule_checks(reviewed_text, rubric)

    semantic_result = None
    semantic_error = None
    try:
        semantic_payload = call_anthropic_review(
            args.model,
            build_system_prompt(rubric),
            build_user_payload(reviewed_text, rule_flags),
        )
        semantic_result = coerce_review_payload(semantic_payload)
    except (RuntimeError, urllib.error.URLError, json.JSONDecodeError) as exc:
        semantic_error = str(exc)

    final_result = merge_results(rule_flags, semantic_result, semantic_error)
    final_result["model"] = args.model
    final_result["isolated_context"] = True
    final_result["mode"] = args.mode

    variant["review_result"] = final_result
    variant["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    variant["reviewed_text_snapshot"] = reviewed_text
    remix_job["review_followup_notes"] = summarize_followup(final_result)
    save_project(project_dir, project)

    if final_result["verdict"] == "PASS":
        return 0
    if final_result["verdict"] == "REJECT":
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
