from __future__ import annotations

import argparse
from pathlib import Path

from common import load_json, load_project, save_json, save_project


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--mapping-file", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_dir = Path(args.project_dir)
    project = load_project(project_dir)
    if not args.mapping_file:
        print(project["deliverables"].get("characters_to_confirm_path", "No review file generated yet."))
        return

    mapping = load_json(Path(args.mapping_file), {})
    updates = {item["character_id"]: item for item in mapping.get("characters", [])}
    aliases = mapping.get("merge_into", {})
    merged = []
    for char in project["characters"]:
        target = aliases.get(char["character_id"])
        if target:
            continue
        update = updates.get(char["character_id"], {})
        char["source_role_name"] = update.get("source_role_name", char["source_role_name"])
        char["identity_description_tokens"] = update.get("identity_description_tokens", char["identity_description_tokens"])
        char["human_confirmed"] = update.get("human_confirmed", True)
        merged.append(char)

    for shot in project["shots"]:
        shot["character_ids"] = [aliases.get(char_id, char_id) for char_id in shot.get("character_ids", []) if aliases.get(char_id, char_id) in {c["character_id"] for c in merged}]

    project["characters"] = merged
    save_project(project_dir, project)
    save_json(project_dir / "derived" / "characters.json", merged)
    print(f"Confirmed {len(merged)} characters.")


if __name__ == "__main__":
    main()
