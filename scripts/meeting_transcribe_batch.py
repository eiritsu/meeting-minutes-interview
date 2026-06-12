"""
长会议批量转录：抽音轨 → 切片 → 串行转录 → 合并 → 说话人分段
支持的转录模型：
  - FunAudioLLM/SenseVoiceSmall（无说话人识别，最快）
  - Paraformer-V2（带说话人分段，中英混合优秀）  🆕
  - iic/SenseVoiceSmall（备用）

输出 JSON schema:
{
  "source_file": "...",
  "duration_seconds": 5400,
  "model": "Paraformer-V2",
  "chunks": [
    {"index": 1, "start_time": 0,    "end_time": 600,  "text": "...", "speaker": "S1"}
  ],
  "full_text": "..."
}

CLI:
  uv run --with av --with requests python3 meeting_transcribe_batch.py \\
      --input meeting.mp4 \\
      --output /tmp/transcript.json \\
      --chunk-seconds 600 \\
      --model Paraformer-V2
"""
import argparse
import json
import os
import re
import sys
import time
import wave
from pathlib import Path

import av
import requests


def read_api_key():
    env_path = Path.home() / ".hermes" / ".env"
    with open(env_path) as f:
        for line in f:
            if "SILICONFLOW_API_KEY" in line and "=" in line:
                return line.strip().split("=", 1)[1]
    raise SystemExit("ERROR: 找不到 SILICONFLOW_API_KEY in ~/.hermes/.env")


def extract_audio(src_path: Path, dst_path: Path) -> float:
    """抽音轨到 16k mono WAV，返回时长（秒）"""
    container = av.open(str(src_path))
    audio_streams = [s for s in container.streams if s.type == 'audio']
    if not audio_streams:
        container.close()
        raise SystemExit(
            f"ERROR: 文件中没有可解码的音轨\n"
            f"      可能原因：1) 编码格式不支持 2) 文件损坏 3) 原本就是视频（skill 仅支持音频）"
        )

    stream = audio_streams[0]
    resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dst_path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        for frame in container.decode(stream):
            for r in resampler.resample(frame):
                wf.writeframes(bytes(r.planes[0]))
    container.close()

    return dst_path.stat().st_size / (16000 * 2)


def split_wav(wav_path: Path, chunk_seconds: int, out_dir: Path) -> list:
    """把 WAV 按 chunk_seconds 切片，返回切片文件路径列表"""
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks = []
    with wave.open(str(wav_path), 'rb') as src:
        sr = src.getframerate()
        nch = src.getnchannels()
        sw = src.getsampwidth()
        total_frames = src.getnframes()
        frames_per_chunk = sr * chunk_seconds

        idx = 0
        for start in range(0, total_frames, frames_per_chunk):
            idx += 1
            end = min(start + frames_per_chunk, total_frames)
            n_frames = end - start
            data = src.readframes(n_frames)

            chunk_path = out_dir / f"chunk_{idx:03d}.wav"
            with wave.open(str(chunk_path), 'wb') as dst:
                dst.setnchannels(nch)
                dst.setsampwidth(sw)
                dst.setframerate(sr)
                dst.writeframes(data)
            chunks.append({
                "path": chunk_path,
                "index": idx,
                "start_time": start / sr,
                "end_time": end / sr,
            })
    return chunks


def transcribe_with_paraformer(wav_path: Path, api_key: str, model: str) -> dict:
    """用 Paraformer-V2 转录 + 说话人分段"""
    url = "https://api.siliconflow.cn/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}

    with open(wav_path, 'rb') as f:
        resp = requests.post(
            url,
            headers=headers,
            files={"file": (wav_path.name, f, "audio/wav")},
            data={"model": model, "response_format": "json"},
            timeout=300,
        )
    if resp.status_code != 200:
        return {"text": f"[ERROR HTTP {resp.status_code}] {resp.text[:200]}"}
    return resp.json()


def transcribe_with_sensevoice(wav_path: Path, api_key: str) -> dict:
    """用 SenseVoiceSmall 转录（无说话人识别，支持中/英/日/韩 + 中文方言）"""
    return transcribe_with_paraformer(wav_path, api_key, "FunAudioLLM/SenseVoiceSmall")


def merge_speaker_tags(text: str) -> list:
    """
    把 Paraformer-V2 返回的说话人标签文本切分成 [(speaker, content), ...]
    格式: '说话人1: xxx 说话人2: yyy' 或 'S1: xxx S2: yyy'
    """
    # 尝试匹配 '说话人1' / '说话人 1' / 'S1' 等
    pattern = r'(说话人\s*\d+|S\d+)[:：]\s*'
    parts = re.split(pattern, text)
    # parts: [pre, tag, content, tag, content, ...]
    result = []
    i = 1
    while i < len(parts) - 1:
        speaker = parts[i].strip()
        content = parts[i + 1].strip()
        if content:
            result.append((speaker, content))
        i += 2
    if not result and text.strip():
        # 没匹配到说话人标签，整体作为 S1
        result = [("S1", text.strip())]
    return result


# 不支持的文件扩展名（本 skill 不处理视频）
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.webm', '.m4v', '.mpg', '.mpeg', '.3gp', '.ts', '.m2ts'}
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.flac', '.ogg', '.opus', '.aac', '.wma', '.amr', '.ac3', '.ape', '.mka'}
SUPPORTED_EXTENSIONS = AUDIO_EXTENSIONS  # = VIDEO_EXTENSIONS 的补集


def main():
    parser = argparse.ArgumentParser(description="长会议批量转录")
    parser.add_argument("--input", required=True, help="输入文件（仅音频，不支持视频）")
    parser.add_argument("--output", required=True, help="输出 JSON 路径")
    parser.add_argument("--chunk-seconds", type=int, default=600, help="切片秒数，默认 600（10 分钟）")
    parser.add_argument("--model", default="FunAudioLLM/SenseVoiceSmall",
                        choices=["FunAudioLLM/SenseVoiceSmall",
                                 "iic/SenseVoiceSmall"],
                        help="转录模型（硅基流动仅提供 SenseVoiceSmall，支持中/英/日/韩 + 中文方言）")
    parser.add_argument("--workdir", default="/tmp/meeting_batch",
                        help="临时工作目录（音轨+切片）")
    parser.add_argument("--delay", type=float, default=1.5, help="每段间隔秒数，防限流")
    args = parser.parse_args()

    src = Path(args.input)
    out = Path(args.output)
    work = Path(args.workdir)
    work.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        raise SystemExit(f"ERROR: 输入文件不存在: {src}")

    ext = src.suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        raise SystemExit(
            f"ERROR: 本 skill 不支持视频文件: {src.name}\n"
            f"      原因：skill 设计上不处理视频\n"
            f"      请用以下方案之一：\n"
            f"        1) ffmpeg -i {src.name} -vn -ac 1 -ar 16000 audio.wav  # 抽音轨后传入\n"
            f"        2) 飞书/Tencent 会议/Zoom 导出 m4a/mp3 音轨\n"
            f"        3) 手机录音机导出为 m4a"
        )
    if ext not in AUDIO_EXTENSIONS:
        raise SystemExit(
            f"ERROR: 不支持的文件格式: {ext}\n"
            f"      支持的音频格式: {', '.join(sorted(AUDIO_EXTENSIONS))}"
        )

    if src.stat().st_size == 0:
        raise SystemExit(f"ERROR: 文件为空: {src}")

    api_key = read_api_key()
    print(f"[1/4] 抽音轨...")
    wav_path = work / "audio.wav"
    duration = extract_audio(src, wav_path)
    print(f"      时长: {duration:.2f} 秒")

    print(f"[2/4] 切片（每段 ≤ {args.chunk_seconds} 秒）...")
    if duration <= args.chunk_seconds:
        chunks = [{
            "path": wav_path,
            "index": 1,
            "start_time": 0.0,
            "end_time": duration,
        }]
        print(f"      长度 ≤ {args.chunk_seconds}s，不切片")
    else:
        chunks = split_wav(wav_path, args.chunk_seconds, work / "chunks")
        print(f"      切成 {len(chunks)} 段")
    for c in chunks:
        print(f"        [{c['index']}] {c['start_time']:.0f}s - {c['end_time']:.0f}s ({c['path'].name})")

    print(f"[3/4] 串行转录（模型: {args.model}）...")
    results = []
    for i, c in enumerate(chunks, 1):
        print(f"      [{i}/{len(chunks)}] {c['path'].name} ...")
        if args.model == "Paraformer-V2":
            # SiliconFlow Paraformer-V2（仅当平台支持时可用）
            r = transcribe_with_paraformer(c["path"], api_key, "Paraformer-V2")
        else:
            # 默认 SenseVoiceSmall（硅基流动唯一可用 ASR）
            r = transcribe_with_sensevoice(c["path"], api_key)

        text = r.get("text", "")
        # 解析说话人
        speakers = merge_speaker_tags(text)
        chunk_result = {
            "index": c["index"],
            "start_time": c["start_time"],
            "end_time": c["end_time"],
            "raw_text": text,
            "speakers": [{"speaker": s, "text": t} for s, t in speakers],
        }
        # 语种检测字段
        if "language" in r:
            chunk_result["language"] = r["language"]
        results.append(chunk_result)
        preview = text[:60].replace('\n', ' ')
        print(f"        ✓ {preview}{'...' if len(text) > 60 else ''}")

        if i < len(chunks):
            time.sleep(args.delay)

    print(f"[4/4] 合并 & 写入 JSON...")
    full_text = "\n\n".join(r["raw_text"] for r in results)

    output = {
        "source_file": str(src),
        "duration_seconds": duration,
        "model": args.model,
        "chunks": results,
        "full_text": full_text,
    }
    # 聚合语种检测结果
    from collections import Counter
    languages = [r["language"] for r in results if "language" in r]
    if languages:
        lang_count = Counter(languages)
        output["detected_languages"] = dict(lang_count)
        output["primary_language"] = lang_count.most_common(1)[0][0]
    else:
        output["primary_language"] = "unknown"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完成: {out}")
    print(f"   时长: {duration/60:.1f} 分钟")
    print(f"   段数: {len(results)}")
    print(f"   字符数: {len(full_text)}")
    # 打印检测到的语种
    langs = [r.get("language", "?") for r in results]
    from collections import Counter
    lang_count = Counter(langs)
    if lang_count:
        print(f"   检测语种: {dict(lang_count)}")
        primary = lang_count.most_common(1)[0][0]
        print(f"   主语言: {primary}")


if __name__ == "__main__":
    main()