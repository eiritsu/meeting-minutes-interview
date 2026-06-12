"""
抽音轨到 16kHz mono WAV（SiliconFlow SenseVoice/Paraformer 推荐格式）
支持视频（MP4/MOV/AVI/MKV）和音频（MP3/M4A/WAV/FLAC/OGG）输入
"""
import av
import sys
import wave
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
dst.parent.mkdir(parents=True, exist_ok=True)

container = av.open(str(src))
streams = list(container.streams)
print(f"输入: {src.name}")
print(f"流数量: {len(streams)}")
for i, s in enumerate(streams):
    print(f"  Stream {i}: type={s.type}, codec={s.codec_context.name}, rate={getattr(s.codec_context, 'sample_rate', '-')}")

audio_streams = [s for s in container.streams if s.type == 'audio']
if not audio_streams:
    print("ERROR: 没有音轨")
    sys.exit(1)

stream = audio_streams[0]
resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)

# 第一遍：估算总时长
duration_seconds = float(stream.duration * stream.time_base) if stream.duration and stream.time_base else None

# 第二遍：解码
with wave.open(str(dst), 'wb') as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)

    frame_count = 0
    for frame in container.decode(stream):
        for resampled in resampler.resample(frame):
            wf.writeframes(bytes(resampled.planes[0]))
            frame_count += 1
    container.close()

# 真实时长按文件大小反算（最准确）
file_size = dst.stat().st_size
actual_duration = file_size / (16000 * 2)

print(f"\n输出: {dst}")
print(f"大小: {file_size} bytes")
print(f"解码 frame: {frame_count}")
print(f"估算时长: {actual_duration:.2f} 秒")
if duration_seconds:
    print(f"元数据时长: {duration_seconds:.2f} 秒")