# video-remix-analyst

直接把下面这段话复制给你的 agent，它会自动完成部署：请将这个仓库安装为 Codex skill，仓库地址是 `https://github.com/knottttt/video-remix-analyst`。安装后检查 skill 是否成功出现在可用 skill 列表里；如果缺依赖，进入 skill 目录运行 `python -m pip install -r requirements.txt`，再运行 `python scripts/check_environment.py`；如果 skill 没有被自动枚举，就直接使用这个本地 skill 路径继续执行。

`video-remix-analyst` 是一个面向参考视频拆解、故事补全、分镜 remix 和下游生成提示词整理的 Codex skill。当前版本默认每次生成单个 variant，并将最终输出收敛为一个可直接喂给 GPT Image / Seedance 的 `shot_prompts.md`，同时保留 `refs/` 角色参考图目录用于角色一致性。

## Main Files

- [SKILL.md](./SKILL.md)
- `scripts/`
- `templates/`
- `config/`
- `tests/`

## Quick Start

1. 安装依赖：

```powershell
python -m pip install -r requirements.txt
```

2. 检查环境：

```powershell
python scripts/check_environment.py
```

3. 运行典型流程：

```powershell
python scripts/story_synthesis.py --project-dir "<project-dir>" --story-file "<story-file>" --duration-seconds 30
python scripts/analyze.py --project-dir "<project-dir>"
python scripts/remix.py --project-dir "<project-dir>" --creative-brief-file "<brief-file>" --variant-count 1
python scripts/compile_bundle.py --project-dir "<project-dir>" --variant-id variant_01
```

最终核心输出：

- `exports/variant_01/shot_prompts.md`
- `exports/variant_01/refs/`

## Notes

- 如果已有角色设定图，优先通过 `reference_image_paths` 或 `refs/` 提供，不要在最终 prompt 里重复写很长的人物外貌描述。
- 如果没有角色设定图，再用简短文字补角色识别特征。
- `export_reports.py` 现在是可选步骤，只有明确需要分析报告时再运行。
