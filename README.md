# meeting-minutes-interview

> Turns interview recordings and meeting audio into structured, bilingual minutes — transcription, speaker diarization, and LLM refinement in one pipeline.

English | [简体中文](README.zh-CN.md)

![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue?logo=python&logoColor=white)
![SiliconFlow](https://img.shields.io/badge/ASR-SiliconFlow%20SenseVoiceSmall-00B8A9?logo=waveform&logoColor=white)
![Last Commit](https://img.shields.io/github/last-commit/eiritsu/meeting-minutes-interview)
![Stars](https://img.shields.io/github/stars/eiritsu/meeting-minutes-interview?style=social)

---

## ✨ Features

| | |
|---|---|
| 🔊 **Audio normalization** | EBU R128 loudness normalization (-16 LUFS) for consistent ASR quality |
| 🎯 **VAD chunking** | Splits audio at natural speech pauses instead of fixed time intervals |
| 🎙️ **Long-audio transcription** | Auto-slices audio and transcribes serially with rate-limit guard |
| 🗣️ **Speaker diarization** | Detects and labels multiple speakers across the meeting |
| 🌐 **Multilingual** | Mandarin, Cantonese, English, Japanese, Korean + Chinese dialects |
| 📝 **Meeting templates** | Interview / Weekly / Product Review / Generic templates |
| 🤖 **Auto LLM summary** | Agent uses current model to generate minutes — no manual copy-paste |
| 💾 **Meeting history** | SQLite storage with search and statistics |
| 🎬 **Video support** | Auto-extracts audio track from video files |
| 💰 **100% free ASR** | SiliconFlow SenseVoiceSmall — no usage limits |

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (Python package manager)
- ffmpeg (for audio normalization and video extraction)
- SiliconFlow API key — [free signup](https://siliconflow.cn), store in `~/.hermes/.env`:
  ```
  SILICONFLOW_API_KEY=sk-...
  ```

### Run

```bash
# Install dependencies
uv pip install av requests

# Basic usage
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input meeting.m4a \
    --meeting-type "Product Review"

# Interview with template
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input interview.mp3 \
    --meeting-type "Technical Interview" \
    --template interview \
    --title "Zhang San - Backend Engineer Round 2"
```

### Available templates

| Template | Use case |
|---|---|
| `interview` | Technical/HR interviews — candidate assessment, scoring, hire recommendation |
| `weekly` | Weekly standups — progress, blockers, next week plan, risk tracking |
| `product_review` | Product reviews — feasibility, resources, timeline, decision log |
| `generic` | General meetings — topics, decisions, action items, risks |

## 📋 Pipeline

```
Audio Input
  ↓
1. Normalize (EBU R128, -16 LUFS)
  ↓
2. VAD Chunk (split at natural pauses)
  ↓
3. Transcribe (SiliconFlow SenseVoiceSmall, free)
  ↓
4. LLM Auto-Summary (current session model)
  ↓
5. Store (SQLite history)
```

## 📁 Project Structure

```
scripts/
├── run_pipeline.py              # One-shot pipeline runner
├── vad_chunk.py                 # VAD silence-based chunker
├── normalize_audio.py           # EBU R128 normalization
├── meeting_store.py             # SQLite storage
├── extract_audio.py             # Audio track extraction
├── transcribe_single.py         # Single file transcription
└── meeting_transcribe_batch.py  # Batch transcription

prompts/
├── fix_transcript.txt           # ASR error correction
├── identify_speakers.txt        # Speaker role identification
├── generate_minutes.txt         # Generic meeting minutes
├── template_interview.txt       # Interview-specific
├── template_weekly.txt          # Weekly standup
└── template_product_review.txt  # Product review
```

## 📊 Performance

| Duration | Chunks | Transcription | Summary | Total |
|---|---|---|---|---|
| 5 min | 1-2 | 30s | 1 min | **2 min** |
| 30 min | 3-5 | 1.5 min | 3 min | **5 min** |
| 1 hour | 5-8 | 3 min | 5 min | **10 min** |
| 2 hours | 8-12 | 6 min | 8 min | **16 min** |

## 🛠️ Advanced Options

```bash
# Skip normalization (good quality audio)
--no-normalize

# Skip VAD, use fixed-time chunking
--no-vad --chunk-seconds 300

# Specify transcription model
--model Paraformer-V2

# Skip SQLite storage
--no-store
```

## 🔒 Privacy

- Only audio is uploaded to SiliconFlow for ASR
- All other processing is local
- Meeting history stored in `~/.hermes/data/meeting_minutes.db`

## 📄 License

[MIT](LICENSE) — Copyright (c) 2024 Y
