"""
会议纪要全流程 runner v2.0
参考 meetily 设计，集成 VAD 切片、响度归一化、自动摘要

流程：
  输入音频 → 归一化(可选) → VAD切片 → ASR转录 → 生成纪要Prompt → 保存历史

CLI:
  uv run --with av --with requests python3 run_pipeline.py \
      --input meeting.m4a \
      --meeting-type "产品评审会" \
      --duration-estimate 60

  # 面试专用模板
  uv run --with av --with requests python3 run_pipeline.py \
      --input interview.mp3 \
      --meeting-type "技术面试" \
      --template interview

  # 跳过归一化（音频质量好时）
  uv run --with av --with requests python3 run_pipeline.py \
      --input meeting.wav \
      --no-normalize
"""
import argparse
import json
import os
import subprocess
import sys
import shutil
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.webm', '.m4v', '.mpg', '.mpeg', '.3gp', '.ts', '.m2ts'}
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.flac', '.ogg', '.opus', '.aac', '.wma', '.amr', '.ac3', '.ape', '.mka'}

# 模板映射
TEMPLATES = {
    'interview': 'template_interview.txt',
    'weekly': 'template_weekly.txt',
    'product_review': 'template_product_review.txt',
    'generic': 'generate_minutes.txt',
}

def find_ffmpeg():
    """查找 ffmpeg 路径"""
    for p in ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', shutil.which('ffmpeg') or '']:
        if p and Path(p).exists():
            return p
    return None


def extract_audio_from_video(src_path: Path, workdir: Path) -> Path:
    """从视频中抽取音轨（16kHz mono WAV）"""
    dst = workdir / "extracted_audio.wav"
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        cmd = [ffmpeg, '-i', str(src_path), '-vn', '-ac', '1', '-ar', '16000',
               '-c:a', 'pcm_s16le', '-y', str(dst)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise SystemExit(f"ERROR: ffmpeg 抽音轨失败:\n{r.stderr[:500]}")
        return dst

    # fallback: 用 PyAV
    try:
        import av
        import wave
        container = av.open(str(src_path))
        audio_streams = [s for s in container.streams if s.type == 'audio']
        if not audio_streams:
            container.close()
            raise SystemExit("ERROR: 视频中没有音轨")
        stream = audio_streams[0]
        resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
        dst.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(dst), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            for frame in container.decode(stream):
                for r in resampler.resample(frame):
                    wf.writeframes(bytes(r.planes[0]))
        container.close()
        return dst
    except ImportError:
        raise SystemExit("ERROR: 需要 ffmpeg 或 PyAV 来处理视频文件\n"
                         "      brew install ffmpeg  或  uv pip install av")


def normalize_audio(src: Path, dst: Path, target_lufs: int = -16) -> bool:
    """响度归一化，返回是否做了处理"""
    # 调用 normalize_audio.py
    cmd = [sys.executable, str(SCRIPT_DIR / "normalize_audio.py"),
           "--input", str(src), "--output", str(dst),
           "--target-lufs", str(target_lufs)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        print(f"[WARN] 归一化失败，使用原始音频: {r.stderr[:200]}", file=sys.stderr)
        return False
    print(r.stderr, file=sys.stderr)  # 归一化信息输出到 stderr
    return dst.exists()


def vad_chunk(wav_path: Path, workdir: Path, **kwargs) -> dict:
    """VAD 静音检测切片"""
    chunks_dir = workdir / "vad_chunks"
    cmd = [sys.executable, str(SCRIPT_DIR / "vad_chunk.py"),
           "--input", str(wav_path),
           "--output-dir", str(chunks_dir)]
    for k, v in kwargs.items():
        cmd.extend([f"--{k.replace('_', '-')}", str(v)])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(f"[WARN] VAD 切片失败: {r.stderr[:200]}", file=sys.stderr)
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def fallback_fixed_chunks(wav_path: Path, workdir: Path, chunk_seconds: int = 600) -> dict:
    """固定时间切片（VAD 失败时的 fallback）"""
    import wave
    chunks_dir = workdir / "fixed_chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    with wave.open(str(wav_path), 'rb') as src:
        sr = src.getframerate()
        nch = src.getnchannels()
        sw = src.getsampwidth()
        total_frames = src.getnframes()
        frames_per_chunk = sr * chunk_seconds

        chunks = []
        idx = 0
        for start in range(0, total_frames, frames_per_chunk):
            idx += 1
            end = min(start + frames_per_chunk, total_frames)
            data = src.readframes(end - start)
            chunk_path = chunks_dir / f"chunk_{idx:03d}.wav"
            with wave.open(str(chunk_path), 'wb') as dst:
                dst.setnchannels(nch)
                dst.setsampwidth(sw)
                dst.setframerate(sr)
                dst.writeframes(data)
            chunks.append({
                "path": str(chunk_path),
                "index": idx,
                "start_time": start / sr,
                "end_time": end / sr,
                "duration": (end - start) / sr,
            })

    return {"chunks": chunks, "total_chunks": len(chunks), "method": "fixed"}


def transcribe_chunk(wav_path: str, api_key: str, model: str) -> dict:
    """单段转录（SiliconFlow API）"""
    import requests
    url = "https://api.siliconflow.cn/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}
    p = Path(wav_path)
    with open(p, 'rb') as f:
        resp = requests.post(
            url, headers=headers,
            files={"file": (p.name, f, "audio/wav")},
            data={"model": model, "response_format": "json"},
            timeout=300,
        )
    if resp.status_code != 200:
        return {"text": f"[ERROR HTTP {resp.status_code}] {resp.text[:200]}"}
    return resp.json()


def merge_speaker_tags(text: str) -> list:
    """解析说话人标签"""
    import re
    pattern = r'(说话人\s*\d+|S\d+|Speaker\s*\d+|話者\d+)[:：]\s*'
    parts = re.split(pattern, text)
    result = []
    i = 1
    while i < len(parts) - 1:
        speaker = parts[i].strip()
        content = parts[i + 1].strip()
        if content:
            result.append((speaker, content))
        i += 2
    if not result and text.strip():
        result = [("S1", text.strip())]
    return result


def read_api_key():
    """读取 SiliconFlow API Key"""
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        raise SystemExit("ERROR: 找不到 ~/.hermes/.env")
    with open(env_path) as f:
        for line in f:
            if "SILICONFLOW_API_KEY" in line and "=" in line:
                return line.strip().split("=", 1)[1]
    raise SystemExit("ERROR: 找不到 SILICONFLOW_API_KEY in ~/.hermes/.env")


def load_prompt(name: str) -> str:
    return (SKILL_DIR / "prompts" / name).read_text(encoding="utf-8")


def render_prompt(template: str, **kwargs) -> str:
    for k, v in kwargs.items():
        template = template.replace("{{" + k + "}}", str(v))
    return template


def main():
    parser = argparse.ArgumentParser(description="会议纪要全流程 runner v2.0")
    parser.add_argument("--input", required=True, help="输入文件（音频或视频）")
    parser.add_argument("--meeting-type", default="通用会议", help="会议类型")
    parser.add_argument("--template", default="generic",
                        choices=list(TEMPLATES.keys()),
                        help="摘要模板：interview/weekly/product_review/generic")
    parser.add_argument("--duration-estimate", type=int, help="会议时长（分钟），覆盖自动检测")
    parser.add_argument("--chunk-seconds", type=int, default=600, help="固定切片秒数（fallback）")
    parser.add_argument("--model", default="FunAudioLLM/SenseVoiceSmall",
                        choices=["FunAudioLLM/SenseVoiceSmall", "Paraformer-V2"],
                        help="转录模型")
    parser.add_argument("--workdir", default="/tmp/meeting_pipeline", help="工作目录")
    parser.add_argument("--no-normalize", action="store_true", help="跳过响度归一化")
    parser.add_argument("--no-vad", action="store_true", help="跳过 VAD，用固定切片")
    parser.add_argument("--language", default=None, help="指定语言代码")
    parser.add_argument("--title", default=None, help="会议标题（用于存储）")
    parser.add_argument("--no-store", action="store_true", help="不保存到 SQLite")
    args = parser.parse_args()

    src = Path(args.input)
    if not src.exists():
        raise SystemExit(f"ERROR: 输入文件不存在: {src}")

    ext = src.suffix.lower()
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    # === Step 0: 音频准备 ===
    print(f"\n{'='*60}")
    print(f"📋 会议纪要生成 v2.0")
    print(f"{'='*60}")
    print(f"输入: {src.name}")
    print(f"会议类型: {args.meeting_type}")
    print(f"模板: {args.template}")
    print(f"转录模型: {args.model}")

    audio_src = src
    if ext in VIDEO_EXTENSIONS:
        print(f"\n[0/5] 检测到视频文件，抽取音轨...")
        audio_src = extract_audio_from_video(src, workdir)
        print(f"      ✓ 音轨已抽取: {audio_src.name}")
    elif ext not in AUDIO_EXTENSIONS:
        raise SystemExit(f"ERROR: 不支持的文件格式: {ext}\n"
                         f"      支持: {', '.join(sorted(AUDIO_EXTENSIONS | VIDEO_EXTENSIONS))}")

    # === Step 1: 响度归一化 ===
    if args.no_normalize:
        normalized_path = audio_src
        print(f"\n[1/5] 跳过响度归一化")
    else:
        print(f"\n[1/5] 响度归一化...")
        normalized_path = workdir / "normalized.wav"
        if normalize_audio(audio_src, normalized_path):
            print(f"      ✓ 归一化完成")
        else:
            normalized_path = audio_src
            print(f"      ⚠ 使用原始音频")

    # === Step 2: 抽音轨到 16kHz mono WAV ===
    print(f"\n[2/5] 抽音轨到 16kHz mono WAV...")
    wav_path = workdir / "audio.wav"
    if normalized_path.suffix == '.wav':
        # 检查是否已经是 16kHz mono
        import wave
        try:
            with wave.open(str(normalized_path), 'rb') as wf:
                if wf.getframerate() == 16000 and wf.getnchannels() == 1:
                    shutil.copy2(normalized_path, wav_path)
                    print(f"      ✓ 已是 16kHz mono，直接复制")
                else:
                    # 需要重采样：用 ffmpeg
                    ffmpeg = find_ffmpeg()
                    if ffmpeg:
                        cmd = [ffmpeg, '-i', str(normalized_path), '-vn', '-ac', '1', '-ar', '16000',
                               '-c:a', 'pcm_s16le', '-y', str(wav_path)]
                        subprocess.run(cmd, capture_output=True, check=True, timeout=300)
                        print(f"      ✓ 重采样完成 (ffmpeg)")
                    else:
                        shutil.copy2(normalized_path, wav_path)
                        print(f"      ⚠ ffmpeg 不可用，复制原始文件")
        except Exception:
            shutil.copy2(normalized_path, wav_path)
            print(f"      ✓ 复制完成")
    else:
        # 非 WAV 格式，用 PyAV 提取
        try:
            import av
            container = av.open(str(normalized_path))
            audio_streams = [s for s in container.streams if s.type == 'audio']
            if not audio_streams:
                container.close()
                raise SystemExit("ERROR: 文件中没有音轨")
            stream = audio_streams[0]
            resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
            with wave.open(str(wav_path), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                for frame in container.decode(stream):
                    for r in resampler.resample(frame):
                        wf.writeframes(bytes(r.planes[0]))
            container.close()
            print(f"      ✓ 音轨抽取完成")
        except ImportError:
            ffmpeg = find_ffmpeg()
            if ffmpeg:
                cmd = [ffmpeg, '-i', str(normalized_path), '-vn', '-ac', '1', '-ar', '16000',
                       '-c:a', 'pcm_s16le', '-y', str(wav_path)]
                subprocess.run(cmd, capture_output=True, check=True, timeout=300)
                print(f"      ✓ 音轨抽取完成 (ffmpeg)")
            else:
                raise SystemExit("ERROR: 需要 ffmpeg 或 PyAV")

    # 获取音频时长
    with wave.open(str(wav_path), 'rb') as wf:
        duration_seconds = wf.getnframes() / wf.getframerate()
    duration_min = duration_seconds / 60
    duration_str = f"{duration_min:.1f}" if args.duration_estimate is None else f"~{args.duration_estimate}"
    print(f"      时长: {duration_min:.1f} 分钟")

    # === Step 3: 切片 ===
    if args.no_vad:
        print(f"\n[3/5] 固定时间切片（每段 {args.chunk_seconds}s）...")
        chunk_result = fallback_fixed_chunks(wav_path, workdir, args.chunk_seconds)
    else:
        print(f"\n[3/5] VAD 静音检测切片...")
        chunk_result = vad_chunk(wav_path, workdir)
        if chunk_result is None:
            print(f"      ⚠ VAD 失败，fallback 到固定切片")
            chunk_result = fallback_fixed_chunks(wav_path, workdir, args.chunk_seconds)

    chunks = chunk_result["chunks"]
    method = chunk_result.get("method", "unknown")
    print(f"      方法: {method} | 段数: {len(chunks)}")
    for c in chunks:
        print(f"        [{c['index']}] {c['start_time']:.0f}s - {c['end_time']:.0f}s")

    # === Step 4: 转录 ===
    print(f"\n[4/5] ASR 转录（{args.model}）...")
    api_key = read_api_key()
    import time

    transcript_chunks = []
    for i, c in enumerate(chunks, 1):
        chunk_path = c["path"]
        print(f"      [{i}/{len(chunks)}] 转录中...")
        r = transcribe_chunk(chunk_path, api_key, args.model)
        text = r.get("text", "")
        speakers = merge_speaker_tags(text)
        chunk_data = {
            "index": c["index"],
            "start_time": c["start_time"],
            "end_time": c["end_time"],
            "raw_text": text,
            "speakers": [{"speaker": s, "text": t} for s, t in speakers],
        }
        if "language" in r:
            chunk_data["language"] = r["language"]
        transcript_chunks.append(chunk_data)
        preview = text[:80].replace('\n', ' ')
        print(f"        ✓ {preview}{'...' if len(text) > 80 else ''}")
        if i < len(chunks):
            time.sleep(1.5)

    # 合并
    from collections import Counter
    full_text = "\n\n".join(r["raw_text"] for r in transcript_chunks)
    languages = [r["language"] for r in transcript_chunks if "language" in r]
    lang_count = Counter(languages) if languages else Counter()

    transcript = {
        "source_file": str(src),
        "duration_seconds": duration_seconds,
        "model": args.model,
        "chunks": transcript_chunks,
        "full_text": full_text,
        "detected_languages": dict(lang_count),
        "primary_language": lang_count.most_common(1)[0][0] if lang_count else "unknown",
    }

    # 保存 transcript.json
    transcript_path = workdir / "transcript.json"
    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False, indent=2)
    print(f"      ✓ 转录完成: {len(full_text)} 字符")

    # === Step 5: 生成 Prompt ===
    print(f"\n[5/5] 生成摘要 Prompt...")

    # 修正 prompt（始终生成，供 LLM 预处理）
    fix_tpl = load_prompt("fix_transcript.txt")
    fix_rendered = render_prompt(
        fix_tpl,
        MODEL=transcript["model"],
        DURATION=f"{duration_min:.1f} 分钟",
        LANGUAGE=transcript.get("primary_language", "unknown"),
        FULL_TEXT=full_text,
    )

    # 说话人画像 prompt
    id_tpl = load_prompt("identify_speakers.txt")
    id_rendered = render_prompt(
        id_tpl,
        MEETING_TYPE=args.meeting_type,
        DURATION=duration_str,
        LANGUAGE=transcript.get("primary_language", "unknown"),
        TRANSCRIPT=full_text[:6000],
    )

    # 纪要 prompt（使用选定模板）
    template_file = TEMPLATES.get(args.template, TEMPLATES["generic"])
    min_tpl = load_prompt(template_file)
    min_rendered = render_prompt(
        min_tpl,
        MEETING_TYPE=args.meeting_type,
        DURATION=duration_str,
        LANGUAGE=transcript.get("primary_language", "unknown"),
        DATE=datetime.now().strftime("%Y-%m-%d"),
        SPEAKERS="参见说话人画像",
        TITLE=args.title or args.meeting_type,
        TRANSCRIPT=full_text[:10000],
    )

    # 输出
    out_dir = workdir / "prompts"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "1_fix_transcript.md").write_text(fix_rendered, encoding="utf-8")
    (out_dir / "2_identify_speakers.md").write_text(id_rendered, encoding="utf-8")
    (out_dir / "3_generate_minutes.md").write_text(min_rendered, encoding="utf-8")

    # === 保存到 SQLite ===
    if not args.no_store:
        try:
            store_cmd = [sys.executable, str(SCRIPT_DIR / "meeting_store.py"), "save",
                         "--title", args.title or args.meeting_type,
                         "--type", args.meeting_type,
                         "--duration", str(round(duration_min, 1)),
                         "--source", str(src),
                         "--transcript", str(transcript_path),
                         "--model", args.model,
                         "--language", transcript.get("primary_language", "unknown")]
            r = subprocess.run(store_cmd, capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                store_result = json.loads(r.stdout)
                print(f"\n      💾 已保存到会议历史 (ID: {store_result.get('id', '?')})")
            else:
                print(f"\n      ⚠ 存储失败: {r.stderr[:100]}", file=sys.stderr)
        except Exception as e:
            print(f"\n      ⚠ 存储异常: {e}", file=sys.stderr)

    # === 完成 ===
    print(f"\n{'='*60}")
    print(f"✅ 全部完成！")
    print(f"{'='*60}")
    print(f"\n📁 输出目录: {workdir}")
    print(f"  ├─ transcript.json         # 转录数据")
    print(f"  ├─ audio.wav               # 处理后的音频")
    print(f"  └─ prompts/")
    print(f"     ├─ 1_fix_transcript.md   # 修正转录")
    print(f"     ├─ 2_identify_speakers.md # 说话人画像")
    print(f"     └─ 3_generate_minutes.md  # 纪要生成")
    print(f"\n📋 使用方式（Hermes Agent 内）：")
    print(f"  Agent 会自动读取 transcript.json，使用当前模型生成纪要")
    print(f"  无需手动复制粘贴 Prompt")
    print(f"\n📋 手动使用：")
    print(f"  cat {out_dir}/3_generate_minutes.md | pbcopy")
    print()

    # 输出最终 JSON 摘要（供 agent 解析）
    summary = {
        "status": "completed",
        "transcript_path": str(transcript_path),
        "prompts_dir": str(out_dir),
        "duration_minutes": round(duration_min, 1),
        "chunks": len(chunks),
        "method": method,
        "language": transcript.get("primary_language", "unknown"),
        "characters": len(full_text),
        "template": args.template,
        "model": args.model,
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
