"""
单文件转录：SiliconFlow SenseVoiceSmall（无说话人识别）
- 适用：≤ 10 分钟、单人/不需要说话人分离的场景
- 优势：速度快、API 简单
"""
import os
import sys
import json
import requests
from pathlib import Path

api_key = None
env_path = Path.home() / ".hermes" / ".env"
with open(env_path) as f:
    for line in f:
        if "SILICONFLOW_API_KEY" in line and "=" in line:
            api_key = line.strip().split("=", 1)[1]
            break

if not api_key:
    print("ERROR: 找不到 SILICONFLOW_API_KEY in ~/.hermes/.env")
    sys.exit(1)

audio_path = Path(sys.argv[1])
if not audio_path.exists():
    print(f"ERROR: 文件不存在: {audio_path}")
    sys.exit(1)
# 提示：本脚本不处理视频，传入视频请先抽音轨
url = "https://api.siliconflow.cn/v1/audio/transcriptions"
headers = {"Authorization": f"Bearer {api_key}"}

print(f"上传: {audio_path.name} ({audio_path.stat().st_size} bytes)")

with open(audio_path, "rb") as f:
    resp = requests.post(
        url,
        headers=headers,
        files={"file": (audio_path.name, f, "audio/wav")},
        data={"model": "FunAudioLLM/SenseVoiceSmall"},
        timeout=120,
    )

print(f"HTTP {resp.status_code}")
result = resp.json()
print(json.dumps(result, ensure_ascii=False, indent=2))