"""
会议纪要全流程 runner
- 抽音轨 → 切片 → 转录 → 生成修正 prompt → 生成说话人画像 prompt → 生成纪要 prompt
- 三个 prompt 直接复制粘贴到对话给 LLM 处理

CLI:
  uv run --with av --with requests python3 run_pipeline.py \\
      --input meeting.mp4 \\
      --meeting-type "产品评审会" \\
      --duration-estimate 60
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent

# 不支持视频输入（skill 设计上不处理视频）
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.webm', '.m4v', '.mpg', '.mpeg', '.3gp', '.ts', '.m2ts'}
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.flac', '.ogg', '.opus', '.aac', '.wma', '.amr', '.ac3', '.ape', '.mka'}


def run_batch(input_path: Path, workdir: Path, chunk_seconds: int, model: str) -> dict:
    """调用 batch 工具链"""
    transcript_path = workdir / "transcript.json"
    cmd = [
        "uv", "run", "--with", "av", "--with", "requests", "python3",
        str(SCRIPT_DIR / "meeting_transcribe_batch.py"),
        "--input", str(input_path),
        "--output", str(transcript_path),
        "--chunk-seconds", str(chunk_seconds),
        "--model", model,
        "--workdir", str(workdir / "audio"),
    ]
    print(f"\n>>> 执行: {' '.join(cmd)}\n")
    r = subprocess.run(cmd, check=False)
    if r.returncode != 0:
        print(f"ERROR: batch 工具链失败 (exit {r.returncode})")
        sys.exit(1)
    with open(transcript_path) as f:
        return json.load(f)


def load_prompt(name: str) -> str:
    return (SKILL_DIR / "prompts" / name).read_text(encoding="utf-8")


def render_prompt(template: str, **kwargs) -> str:
    for k, v in kwargs.items():
        template = template.replace("{{" + k + "}}", str(v))
    return template


def main():
    parser = argparse.ArgumentParser(description="会议纪要全流程 runner")
    parser.add_argument("--input", required=True, help="音频文件（不支持视频）")
    parser.add_argument("--meeting-type", default="通用会议")
    parser.add_argument("--duration-estimate", type=int, help="会议时长（分钟），用于 prompt 上下文")
    parser.add_argument("--chunk-seconds", type=int, default=600, help="切片秒数")
    parser.add_argument("--model", default="FunAudioLLM/SenseVoiceSmall",
                        choices=["FunAudioLLM/SenseVoiceSmall", "Paraformer-V2", "whisper-large-v3"])
    parser.add_argument("--workdir", default="/tmp/meeting_pipeline",
                        help="工作目录")
    parser.add_argument("--no-skip", action="store_true",
                        help="不跳过转录（默认会复用 transcript.json）")
    parser.add_argument("--language", default=None,
                        help="指定语言代码（默认自动检测）")
    args = parser.parse_args()

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    transcript_path = workdir / "transcript.json"

    # 0. 拒绝视频文件
    src = Path(args.input)
    if not src.exists():
        raise SystemExit(f"ERROR: 输入文件不存在: {src}")
    ext = src.suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        raise SystemExit(
            f"ERROR: 本 skill 不支持视频文件: {src.name}\n"
            f"      原因：skill 设计上不处理视频\n"
            f"      请先抽音轨：ffmpeg -i {src.name} -vn -ac 1 -ar 16000 audio.wav\n"
            f"      或用会议软件导出音频格式（m4a/mp3）"
        )
    if ext not in AUDIO_EXTENSIONS:
        raise SystemExit(
            f"ERROR: 不支持的文件格式: {ext}\n"
            f"      支持的格式: {', '.join(sorted(AUDIO_EXTENSIONS))}"
        )

    # 1. 跑转录
    if transcript_path.exists() and not args.no_skip:
        print(f"[i] 复用已有转录: {transcript_path}")
        with open(transcript_path) as f:
            transcript = json.load(f)
    else:
        transcript = run_batch(Path(args.input), workdir, args.chunk_seconds, args.model)

    full_text = transcript["full_text"]
    duration_min = transcript["duration_seconds"] / 60
    duration_str = f"{duration_min:.1f}" if args.duration_estimate is None else f"~{args.duration_estimate}"

    print(f"\n转录完成: {len(full_text)} 字符, {duration_min:.1f} 分钟")

    # 2. 渲染 prompt
    print(f"\n[生成 Prompt 模板]")

    fix_tpl = load_prompt("fix_transcript.txt")
    fix_rendered = render_prompt(
        fix_tpl,
        MODEL=transcript["model"],
        DURATION=f"{duration_min:.1f} 分钟",
        FULL_TEXT=full_text,
    )

    id_tpl = load_prompt("identify_speakers.txt")
    id_rendered = render_prompt(
        id_tpl,
        MEETING_TYPE=args.meeting_type,
        DURATION=duration_str,
        TRANSCRIPT=full_text[:6000],  # 防止 prompt 过长
    )

    min_tpl = load_prompt("generate_minutes.txt")
    min_rendered = render_prompt(
        min_tpl,
        MEETING_TYPE=args.meeting_type,
        DURATION=duration_str,
        SPEAKERS_SUMMARY="参见说话人画像",
        DATE=datetime.now().strftime("%Y-%m-%d"),
        TRANSCRIPT=full_text[:8000],
    )

    # 3. 输出三件套
    out_dir = workdir / "prompts"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "1_fix_transcript.md").write_text(fix_rendered, encoding="utf-8")
    (out_dir / "2_identify_speakers.md").write_text(id_rendered, encoding="utf-8")
    (out_dir / "3_generate_minutes.md").write_text(min_rendered, encoding="utf-8")

    # 4. 打印使用说明
    print(f"\n{'='*60}")
    print(f"✅ 全部完成！")
    print(f"{'='*60}")
    print(f"\n📁 输出目录: {workdir}")
    print(f"  ├─ transcript.json     # 原始转录数据")
    print(f"  ├─ audio/              # 抽出的音轨 + 切片")
    print(f"  └─ prompts/")
    print(f"     ├─ 1_fix_transcript.md     # 修正转录 prompt")
    print(f"     ├─ 2_identify_speakers.md  # 说话人画像 prompt")
    print(f"     └─ 3_generate_minutes.md   # 生成纪要 prompt")
    print(f"\n📋 接下来的操作：")
    print(f"  1. cat {out_dir}/1_fix_transcript.md | pbcopy   # 复制到对话")
    print(f"  2. 粘到对话 → 让 LLM输出修正后的文本")
    print(f"  3. cat {out_dir}/2_identify_speakers.md | pbcopy")
    print(f"  4. 把修正后文本 + 说话人画像 prompt 一起粘给我")
    print(f"  5. cat {out_dir}/3_generate_minutes.md | pbcopy")
    print(f"  6. 把修正后文本 + 纪要 prompt 粘给我 → 输出最终 Markdown 纪要")
    print()


if __name__ == "__main__":
    main()