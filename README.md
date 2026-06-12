# meeting-minutes-interview

> A [Hermes Agent](https://hermes-agent.nousresearch.com/docs) skill that turns interview recordings and meeting audio into structured, bilingual minutes — transcription, speaker diarization, and LLM refinement in one pipeline.

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
| 🎙️ **Long-audio transcription** | Auto-slices audio >10 min and transcribes serially with rate-limit guard |
| 🗣️ **Speaker diarization** | Detects and labels multiple speakers across the meeting |
| ✍️ **LLM refinement** | 3-step prompt pipeline: fix ASR errors → identify speakers → generate minutes |
| 🌏 **Multilingual** | Mandarin, Cantonese, English, Japanese, Korean + Chinese dialects (Sichuan/Shanghai/Tianjin/Min) |
| 🌐 **Bilingual output** | Minutes produced in mixed Chinese/English (original + translation) |
| 💰 **Free ASR** | Uses SiliconFlow `SenseVoiceSmall` — no duration or call-count limits |

---

## 📋 Supported Formats

| Type | Formats |
|------|---------|
| Audio ✅ | `.mp3` `.m4a` `.wav` `.flac` `.ogg` `.opus` `.aac` `.amr` |
| Video ❌ | Not supported directly — extract audio first (see below) |

---

## 🧰 Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (Python package manager)
- `ffmpeg` — only needed for video → audio extraction
- SiliconFlow API key — [free signup](https://siliconflow.cn), key placed in `~/.hermes/.env`

---

## 🚀 Quick Start

### 1. Configure your API key

Add to `~/.hermes/.env`:

```
SILICONFLOW_API_KEY=sk-...
```

### 2. Run the pipeline

```bash
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input meeting.m4a \
    --meeting-type "Product Review" \
    --duration-estimate 60
```

This automatically:
1. Extracts audio (skipped if input is already audio)
2. Slices long audio into 10-minute chunks
3. Transcribes serially with 1.5s delay (rate-limit guard)
4. Generates 3 prompt files for LLM refinement

### 3. Refine with the LLM

Copy the generated prompts in order into your LLM chat:

1. `1_fix_transcript.md` — fix ASR errors, formalize spoken language, keep technical terms
2. `2_identify_speakers.md` — identify speaker roles (S1 → Project Manager, etc.)
3. `3_generate_minutes.md` — generate the final bilingual Markdown minutes

> The LLM steps are manual (copy-paste) to keep API costs transparent and let you steer quality.

---

## 🎥 Video Files

The skill doesn't process video directly. Extract the audio first:

```bash
# 16kHz mono WAV (best for SenseVoice)
ffmpeg -i meeting.mp4 -vn -ac 1 -ar 16000 -c:a pcm_s16le meeting.wav

# Or keep as m4a (smaller)
ffmpeg -i meeting.mp4 -vn -ac 1 -ar 16000 -c:a aac meeting.m4a
```

Then run the pipeline on the extracted audio.

---

## 📁 Repository Layout

```
meeting-minutes-interview/
├── SKILL.md                            # Skill definition (consumed by Hermes Agent)
├── README.md                           # English (this file)
├── README.zh-CN.md                     # 简体中文
├── LICENSE                             # MIT
├── scripts/
│   ├── extract_audio.py                # Audio extraction (PyAV, 16k mono WAV)
│   ├── transcribe_single.py            # Single-file SenseVoice (≤10 min)
│   ├── meeting_transcribe_batch.py     # Batch transcription (long meetings)
│   └── run_pipeline.py                 # One-shot runner
├── prompts/
│   ├── fix_transcript.txt              # Step 1: fix ASR text
│   ├── identify_speakers.txt           # Step 2: speaker profiling
│   ├── merge_speakers.txt              # Cross-chunk speaker merge
│   └── generate_minutes.txt            # Step 3: bilingual minutes
└── templates/
    └── meeting_minutes.md              # Final output template
```

---

## 📊 Performance Reference

> Cost: ASR is free (SiliconFlow SenseVoiceSmall). Only the LLM refinement step uses your chat model.

| Meeting Length | Chunks | Transcription | Refine + Minutes | Total |
|---|---|---|---|---|
| 5 min   | 1  | 30 s    | 1 min  | **2 min**  |
| 30 min  | 3  | 1.5 min | 3 min  | **5 min**  |
| 1 hour  | 6  | 3 min   | 5 min  | **10 min** |
| 2 hours | 12 | 6 min   | 8 min  | **16 min** |

---

## 📥 Install in Hermes Agent

```bash
hermes skills install github:eiritsu/meeting-minutes-interview
```

Or place the folder at `~/.hermes/skills/meeting-minutes-interview/` and restart Hermes.

---

## 🌍 Language Coverage

| Family | Languages | ASR Model |
|---|---|---|
| **Chinese** | Mandarin, Cantonese, Sichuan/Shanghai/Tianjin/Min | SenseVoiceSmall |
| **East Asian** | Japanese, Korean | SenseVoiceSmall |
| **European / Middle Eastern / African** | ❌ Not supported in this skill | — |

> For other languages, integrate OpenAI Whisper API or local `faster-whisper` separately.

---

## ⚠️ Notes

1. **API key safety** — read from `~/.hermes/.env`, never hardcoded
2. **Rate limit guard** — 1.5s delay between chunks to avoid 429
3. **Format recommendation** — convert to 16k mono WAV before upload (most compatible)
4. **Large files** — files >100 MB should be compressed or proxied via OSS
5. **Speaker names** — supplying a participant list / CV greatly improves speaker identification
6. **Privacy** — processing is local; only the audio itself is uploaded to SiliconFlow for ASR
7. **Multilingual scope** — limited to SenseVoice's native languages (zh/en/ja/ko + Chinese dialects)

---

## 📄 License

[MIT](LICENSE) — Copyright (c) 2024 Y

---

Built with ❤️ by [Y](https://github.com/eiritsu)
