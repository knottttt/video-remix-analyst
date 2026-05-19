---
name: video-remix-analyst
description: Build a reusable shot-analysis and storyboard-remix workflow for reference videos. Use when Codex needs to ingest a local video or URL, segment shots, extract frames, analyze beats and characters in agent mode, generate remix variants, and compile Markdown/Excel reports plus a generation bundle for downstream gpt-image-2 and Seedance workflows.
---

# Video Remix Analyst

Run the local Python pipeline in stages. Keep the agent responsible for multimodal judgment and use the scripts for deterministic media processing, data persistence, and export.

## Workflow

1. Check dependencies: `python scripts/check_environment.py`
2. Ingest source media: `python scripts/ingest.py --input <video-or-url> --project-dir <project-dir>`
3. Segment shots: `python scripts/segment.py --project-dir <project-dir>`
4. Sample frames: `python scripts/sample_frames.py --project-dir <project-dir>`
5. Optional story synthesis:
   - Complete story: `python scripts/story_synthesis.py --project-dir <project-dir> --story-file <path>`
   - Idea fragments: `python scripts/story_synthesis.py --project-dir <project-dir> --ideas-file <path>`
6. Align transcript: `python scripts/transcript_align.py --project-dir <project-dir> [--transcript-file <path>]`
7. Optional audio beats: `python scripts/audio_beats.py --project-dir <project-dir>`
8. Analyze project: `python scripts/analyze.py --project-dir <project-dir>`
9. Confirm characters: `python scripts/confirm_characters.py --project-dir <project-dir> [--mapping-file <path>]`
10. Optional export analysis: `python scripts/export_reports.py --project-dir <project-dir> --mode analysis`
   - Skip unless analysis report is explicitly requested.
11. Generate remix variants: `python scripts/remix.py --project-dir <project-dir> --creative-brief-file <path> --variant-count 1`
12. Review generated prompts:
   - Storyboard pack: `python scripts/review_prompts.py --project-dir <project-dir> --variant-id <variant-id>`
   - Beat sheet document: `python scripts/review_prompts.py --project-dir <project-dir> --variant-id <variant-id> --mode beat_sheet_document`
13. Handle review result:
   - `PASS`: continue to compile
   - `REJECT`: revise constraints or brief, rerun step 11, then review again
   - `NEEDS_HUMAN`: stop automatic flow and ask the user to choose the tradeoff
14. Compile a selected variant:
   - Shot prompts only: `python scripts/compile_bundle.py --project-dir <project-dir> --variant-id <variant-id>` (outputs only `shot_prompts.md`)
   - Beat sheet document: `python scripts/compile_beat_sheet.py --project-dir <project-dir> --variant-id <variant-id> --style-profile pixar_3d`
15. Default stopping point: deliver the generated images and prompts first, then wait for explicit user approval before any video generation step
16. Video generation gate:
   - Only if the user explicitly asks to generate video, proceed to the downstream `dreamina CLI` step
   - Do not auto-run video generation just because Seedance prompts already exist

## Agent-mode analysis

`scripts/story_synthesis.py` is the story-first entrypoint. Use it when the user gives a full story draft or only fragmented ideas. It writes `story_core` and `story_outline`, and can create a synthetic project even when no reference video exists.

`scripts/analyze.py` produces a complete heuristic baseline and data contract. If richer multimodal judgment is needed, inspect the generated hero frames under `derived/frames/`, then rerun `analyze.py` with `--override-file <json>` to patch in higher-quality shot, beat, or character annotations without disturbing the rest of the project structure.

Before writing final GPT Image / Seedance prompts, explicitly check whether the user already has character sheets or reference images that should be attached. If they do, prefer image-first character consistency:

- ask the user whether character sheets / reference images are available
- if yes, attach them through `reference_image_paths` / `refs/` and avoid repeating long appearance descriptions in the final prompt
- if yes, use the original character-sheet image itself as the reference asset; do not restyle, repaint, recolor, or convert it to monochrome
- keep only the minimum character text needed for shot readability, action clarity, or role disambiguation
- if no reference images exist, fall back to concise text-only character description

## Downstream prompt writing: Image vs Video

When generating prompts for the bundle, the target tool determines the entire mental model. The same story moment requires completely different writing depending on the downstream platform.

**GPT Image 2 — think like a graphic designer arranging a poster**

- Organizing logic is **spatial**: left/right columns, title placement, stat bars, background treatment
- Describe **poses and compositions** — these are static freeze-frames, not motion
- Hero character portraits should be isolated on clean white background; scene context only appears in designated panel areas (e.g., a bottom strip)
- If the user already supplied character sheets, reference those images instead of re-describing the character's face, hair, or outfit in every shot
- Character-reference areas must show the original supplied character-sheet artwork; if the source sheet is in color, keep it in color
- Storyboard-image deliverables must be a single integrated storyboard sheet, not separate outputs
- The same canvas must contain the main storyboard panels plus the character-reference strip and the expression / pose reference strip
- Place the character-reference strip and the expression / pose reference strip below or beside the panels as part of one unified layout, never as standalone companion images
- Also include a separate expression / pose reference strip for the current copy, covering the key acting beats the downstream model must preserve
- Omit audio, camera motion, and timestamps entirely — they have no meaning in a static image
- All story moments coexist simultaneously on a single canvas; the reader's eye moves through space, not time

**Seedance — think like a film director writing a shooting script**

- Organizing logic is **temporal**: structure around explicit timestamps (`0:00–0:02`, `0:02–0:04`), each covering one beat
- Include a `SOUND:` directive per segment for shot-level sound effects and transition hits
- For this kind of Seedance prompt, do not write BGM / score / music-mood guidance; keep `SOUND:` focused on diegetic or impact SFX only
- Use cinematography language — `Medium shot`, `Wide tracking shot`, `Slow motion` — not "pose" or "expression"
- **Character consistency is fragile in video models**: anchor it at the top by referencing the character sheet, and repeat style constraints throughout (e.g., "full Pixar 3D render, no realistic humans or animals")
- **Track key props across the full timeline explicitly**: state when an object appears, changes hands, goes airborne, or disappears (e.g., "sandwich in Barry's hands until 0:10, launches upward, gone forever") — do not imply state continuity, declare it
- Maintain a single continuous environment; add guards like "maximum brightness throughout, no dark frames" to prevent scene drift between segments

**Core distinction**: An image prompt organizes space. A video prompt organizes time. When the same narrative moment appears in both outputs, the image version describes a freeze-frame composition; the video version describes the arc of motion, sound, and change leading to and away from that moment.

## Notes

- Prefer `PySceneDetect` first. Treat `TransNetV2` as a future enhancement path.
- Character tracking in v1 is descriptive and human-confirmed. Do not add face embedding logic in this skill.
- Exports are limited to Markdown, Excel, and the generation bundle. PDF is intentionally deferred.
- Keep a two-layer writing model:
  - Internal analysis stays explicit with fields such as `story_description`, `change_description`, `emotion_progression`, and `transition_bridge`.
  - Final user-facing `shot_prompts.md` must compress those fields into a natural storyboard paragraph per shot instead of exposing the field labels directly.
- When character sheets are available, do not bloat the output with repeated appearance prose; let the images carry identity consistency.
- Treat character-sheet fidelity as a hard requirement: preserve the original image content and original color mode in the integrated storyboard layout.
- For storyboard-image requests, treat the integrated sheet layout as a hard requirement, not a stylistic suggestion:
  - the storyboard panels, character reference, and key expression / pose references must appear inside one merged storyboard canvas
  - do not output `storyboard` and `reference sheet` as separate images
  - if the current copy implies a special acting beat, make sure that beat appears in the integrated reference strip explicitly
- Treat image generation and video generation as separate user approvals:
  - first output the images and the prompts
  - wait for the user to explicitly request video generation
  - only then use `dreamina CLI` for the downstream video step
- Prompt review must inspect the final rendered storyboard text, not raw panel fields.
- Semantic review must run in isolated context: pass only the rubric, rule flags, and rendered text, without project background.
- Ambiguous style tradeoffs must be escalated as `NEEDS_HUMAN`; do not auto-resolve them in script logic.
- For final storyboard writing, prioritize readable cinematic prose:
  - Start with shot type / angle / motion
  - Then describe what happens in the frame
  - Fold in emotional and informational function naturally
  - Avoid report-like bullets in the final deliverable unless the user explicitly asks for analysis format
