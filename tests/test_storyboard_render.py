from __future__ import annotations

import copy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common import load_project, save_project  # noqa: E402
import compile_beat_sheet  # noqa: E402
import review_prompts  # noqa: E402
import storyboard_render  # noqa: E402


DEMO_PROJECT_DIR = ROOT.parent / "demo-project"
VARIANT_ID = "variant_01"


def legacy_format_seconds(seconds: float) -> str:
    return f"{seconds:.2f}s"


def legacy_build_script_line(panel: dict) -> str:
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


def legacy_build_panels(variant: dict) -> tuple[list[dict], float]:
    panels = []
    cursor_seconds = 0.0
    for idx, panel in enumerate(variant["panels"], start=1):
        row = dict(panel)
        row["index"] = idx
        duration_seconds = float(panel["duration_target_seconds"])
        row["start_timecode"] = legacy_format_seconds(cursor_seconds)
        cursor_seconds += duration_seconds
        row["end_timecode"] = legacy_format_seconds(cursor_seconds)
        row["script_line"] = legacy_build_script_line(row)
        row["final_storyboard_paragraph"] = row["script_line"]
        panels.append(row)
    return panels, cursor_seconds


def legacy_build_intro_line(variant: dict, total_seconds: float) -> str:
    return (
        f"{max(0.01, total_seconds):.2f} 秒分镜短片，目标画幅 {variant['target_aspect_ratio']}。"
        f"创意方向：{variant['creative_constraints']}"
    )


def legacy_render_shot_prompts(variant: dict) -> tuple[str, list[dict], str]:
    panels, total_seconds = legacy_build_panels(copy.deepcopy(variant))
    intro_line = legacy_build_intro_line(variant, total_seconds)
    lines = ["# 分镜稿", "", intro_line, ""]
    for index, panel in enumerate(panels, start=1):
        lines.append(
            f"SHOT {index} ({panel['start_timecode']}–{panel['end_timecode']}) – "
            f"{panel['shot_size']}，{panel['camera_angle']}，{panel['camera_motion']}："
        )
        lines.append(panel["final_storyboard_paragraph"])
        lines.append("")
    return "\n".join(lines) + "\n", panels, intro_line


def find_variant(project: dict, variant_id: str = VARIANT_ID) -> tuple[dict, dict]:
    for job in project["remix_jobs"]:
        for variant in job["generated_variants"]:
            if variant["variant_id"] == variant_id:
                return job, variant
    raise KeyError(variant_id)


class VideoRemixAnalystTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="video-remix-analyst-tests-"))
        self.project_dir = self.temp_dir / "demo-project"
        shutil.copytree(DEMO_PROJECT_DIR, self.project_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def load_project(self) -> dict:
        return load_project(self.project_dir)

    def save_project(self, project: dict) -> None:
        save_project(self.project_dir, project)

    def mutate_first_panel_story(self, text: str) -> None:
        project = self.load_project()
        _, variant = find_variant(project)
        variant["panels"][0]["story_description"] = text
        variant["panels"][0]["change_description"] = ""
        variant["panels"][0]["emotion_progression"] = ""
        variant["panels"][0]["transition_bridge"] = ""
        variant["panels"][0]["sound_note"] = ""
        self.save_project(project)

    def render_selected_panels(self, panel_count: int = 4) -> tuple[str, dict]:
        project = self.load_project()
        remix_job, variant = find_variant(project)
        style_profile = compile_beat_sheet.load_style_profile("pixar_3d")
        prompt_characters = compile_beat_sheet.build_prompt_characters(remix_job, None)
        return compile_beat_sheet.render_beat_sheet_prompt(variant, prompt_characters, style_profile, panel_count)

    def test_storyboard_render_matches_legacy_output(self) -> None:
        project = self.load_project()
        _, variant = find_variant(project)

        expected_text, _, _ = legacy_render_shot_prompts(copy.deepcopy(variant))
        actual_text, _ = storyboard_render.render_shot_prompts(copy.deepcopy(variant))

        self.assertEqual(actual_text, expected_text)

    def test_storyboard_render_matches_legacy_panels(self) -> None:
        project = self.load_project()
        _, variant = find_variant(project)

        expected_panels, _ = legacy_build_panels(copy.deepcopy(variant))
        actual_panels, _ = storyboard_render.build_storyboard_panels(copy.deepcopy(variant))

        self.assertEqual(actual_panels, expected_panels)

    def test_storyboard_render_matches_legacy_intro_line(self) -> None:
        project = self.load_project()
        _, variant = find_variant(project)

        _, expected_total_seconds = legacy_build_panels(copy.deepcopy(variant))
        _, actual_total_seconds = storyboard_render.build_storyboard_panels(copy.deepcopy(variant))

        expected_intro_line = legacy_build_intro_line(copy.deepcopy(variant), expected_total_seconds)
        actual_intro_line = storyboard_render.build_intro_line(copy.deepcopy(variant), actual_total_seconds)

        self.assertEqual(actual_intro_line, expected_intro_line)

    def test_review_prompts_rejects_forbidden_patterns(self) -> None:
        self.mutate_first_panel_story("hatching no soft gradients no airbrush 柔和")

        with mock.patch.object(review_prompts, "call_anthropic_review", return_value={"verdict": "PASS", "issues": [], "suggestions": [], "human_questions": []}):
            exit_code = review_prompts.main(["--project-dir", str(self.project_dir), "--variant-id", VARIANT_ID])

        self.assertEqual(exit_code, 1)
        project = self.load_project()
        _, variant = find_variant(project)
        self.assertEqual(variant["review_result"]["verdict"], "REJECT")

    def test_review_prompts_marks_manual_review_for_ambiguous_patterns(self) -> None:
        self.mutate_first_panel_story("hatching no soft gradients no airbrush grayscale")

        with mock.patch.object(review_prompts, "call_anthropic_review", return_value={"verdict": "PASS", "issues": [], "suggestions": [], "human_questions": []}):
            exit_code = review_prompts.main(["--project-dir", str(self.project_dir), "--variant-id", VARIANT_ID])

        self.assertEqual(exit_code, 2)
        project = self.load_project()
        _, variant = find_variant(project)
        self.assertEqual(variant["review_result"]["verdict"], "NEEDS_HUMAN")
        self.assertTrue(variant["review_result"]["human_questions"])

    def test_review_prompts_passes_clean_case(self) -> None:
        self.mutate_first_panel_story("hatching no soft gradients no airbrush")

        with mock.patch.object(review_prompts, "call_anthropic_review", return_value={"verdict": "PASS", "issues": [], "suggestions": ["Looks aligned."], "human_questions": []}):
            exit_code = review_prompts.main(["--project-dir", str(self.project_dir), "--variant-id", VARIANT_ID])

        self.assertEqual(exit_code, 0)
        project = self.load_project()
        _, variant = find_variant(project)
        self.assertEqual(variant["review_result"]["verdict"], "PASS")

    def test_review_prompts_falls_back_to_needs_human_on_api_failure(self) -> None:
        self.mutate_first_panel_story("hatching no soft gradients no airbrush")

        with mock.patch.object(review_prompts, "call_anthropic_review", side_effect=RuntimeError("network down")):
            exit_code = review_prompts.main(["--project-dir", str(self.project_dir), "--variant-id", VARIANT_ID])

        self.assertEqual(exit_code, 2)
        project = self.load_project()
        _, variant = find_variant(project)
        self.assertEqual(variant["review_result"]["verdict"], "NEEDS_HUMAN")

    def test_compile_beat_sheet_selects_unique_beats_first(self) -> None:
        project = self.load_project()
        _, variant = find_variant(project)
        panels, _ = storyboard_render.build_storyboard_panels(variant)

        selected = compile_beat_sheet.select_panels(panels, panel_count=4)

        self.assertEqual([panel["beat"] for panel in selected[:3]], ["hook", "setup", "payoff"])
        self.assertEqual(len(selected), 4)

    def test_compile_beat_sheet_renders_prompt_and_context(self) -> None:
        prompt_text, context = self.render_selected_panels(panel_count=4)

        self.assertIn("single-page production document", prompt_text)
        self.assertEqual(context["scene_summary"], "Turn the reference into a more mystery-driven island teaser with sharper reveals and a stronger female lead.")
        self.assertEqual(context["dramatic_function"], "Hook -> Setup -> Payoff")
        self.assertEqual(context["arc_summary"], "Hook")
        self.assertEqual(context["selected_panel_indices"], [1, 2, 3, 4])

    def test_compile_beat_sheet_main_writes_bundle(self) -> None:
        compile_beat_sheet.main(
            [
                "--project-dir",
                str(self.project_dir),
                "--variant-id",
                VARIANT_ID,
                "--style-profile",
                "pixar_3d",
            ]
        )

        bundle_dir = self.project_dir / "exports" / "storyboards" / VARIANT_ID / "beat_sheet_bundle"
        self.assertTrue((bundle_dir / "prompt.md").exists())
        self.assertTrue((bundle_dir / "manifest.json").exists())
        self.assertTrue((bundle_dir / "HOWTO.md").exists())

    def test_review_prompts_beat_sheet_document_uses_mode_specific_rubric(self) -> None:
        with mock.patch.object(review_prompts, "call_anthropic_review", return_value={"verdict": "PASS", "issues": [], "suggestions": [], "human_questions": []}):
            exit_code = review_prompts.main(
                [
                    "--project-dir",
                    str(self.project_dir),
                    "--variant-id",
                    VARIANT_ID,
                    "--mode",
                    "beat_sheet_document",
                ]
            )

        self.assertEqual(exit_code, 0)
        project = self.load_project()
        _, variant = find_variant(project)
        self.assertEqual(variant["review_result"]["mode"], "beat_sheet_document")


if __name__ == "__main__":
    unittest.main()
