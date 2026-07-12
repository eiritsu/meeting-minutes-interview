# AGENTS.md — meeting-minutes-interview

> **Note to AI assistants (Codex CLI, Claude Code, Cursor, Windsurf, OpenClaw, generic LLMs, etc.)**:
> This file is the **agent-agnostic** entry point for this skill. It describes what the skill does and how to use it from any LLM-powered environment.
>
> If you are **Hermes Agent**, ignore this file and read [`SKILL.md`](./SKILL.md) instead — that file's YAML frontmatter is the canonical skill descriptor and is required for `hermes skills install` to recognize this skill.

## What this skill does

Takes interview recordings or meeting audio and produces structured, bilingual (Chinese + English) Markdown meeting minutes through a 5-step pipeline:

1. **Normalize** audio loudness (EBU R128, -16 LUFS) via ffmpeg
2. **VAD chunk** — split at natural speech pauses instead of fixed time intervals
3. **Transcribe** audio chunks via SiliconFlow's free `SenseVoiceSmall` ASR (Mandarin / Cantonese / English / Japanese / Korean + Chinese dialects)
4. **LLM-refine** the raw transcript through 3 sequential prompts:
   - Fix ASR errors and formalize spoken language
   - Identify and label speakers by role
   - Generate the final bilingual Markdown minutes
5. **Store** meeting history in SQLite (`~/.hermes/data/meeting_minutes.db`)

## Quick start — for any LLM agent

### Prerequisites

- Python 3.10+
- [`uv`](https://github.com/astral-sh/uv) (Python package manager)
- `ffmpeg` — for audio normalization and video audio extraction
- A **SiliconFlow API key** ([free signup](https://siliconflow.cn)) stored at `SILICONFLOW_API_KEY` in `~/.hermes/.env`
  - If you don't have `~/.hermes/.env` (e.g. you're not running Hermes Agent), create it: `echo "SILICONFLOW_API_KEY=sk-xxx" >> ~/.hermes/.env`

### Run the pipeline

```bash
# From the repo root
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input meeting.m4a \
    --meeting-type "Product Review"
```

### With meeting templates

```bash
# Interview
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input interview.mp3 \
    --meeting-type "Technical Interview" \
    --template interview \
    --title "Zhang San - Backend Engineer Round 2"

# Weekly standup
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input weekly.m4a \
    --meeting-type "Weekly" \
    --template weekly

# Product review
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input review.mp3 \
    --meeting-type "Product Review" \
    --template product_review
```

### Feed the prompts back to your LLM

The pipeline produces 3 prompt files in the working directory:
- `1_fix_transcript.md` — fix ASR errors, normalize spoken language, preserve technical terms
- `2_identify_speakers.md` — assign roles to speakers (S1 → Project Manager, etc.)
- `3_generate_minutes.md` — produce the final bilingual Markdown minutes

Open each prompt file in order, **copy the prompt body into your LLM chat** along with the referenced transcript text. The prompts are agent-agnostic — they work with any LLM that can follow instructions in Chinese/English.

## Repository layout

```
meeting-minutes-interview/
├── SKILL.md                            # Hermes Agent skill descriptor (frontmatter)
├── AGENTS.md                           # ← This file (agent-agnostic entry point)
├── README.md                           # English (project overview)
├── README.zh-CN.md                     # 简体中文
├── LICENSE                             # MIT
├── scripts/
│   ├── run_pipeline.py                 # One-shot pipeline runner (v2.0)
│   ├── vad_chunk.py                    # VAD silence-based audio chunker
│   ├── normalize_audio.py              # EBU R128 loudness normalization
│   ├── meeting_store.py                # SQLite meeting history storage
│   ├── extract_audio.py                # PyAV, 16k mono WAV extraction
│   ├── transcribe_single.py            # SenseVoice (≤10 min)
│   └── meeting_transcribe_batch.py     # SenseVoice (long audio)
├── prompts/
│   ├── fix_transcript.txt              # Fix ASR errors
│   ├── identify_speakers.txt           # Speaker role identification
│   ├── generate_minutes.txt            # Generic meeting minutes
│   ├── template_interview.txt          # Interview-specific template
│   ├── template_weekly.txt             # Weekly standup template
│   └── template_product_review.txt     # Product review template
```

## Custom ASR endpoint (optional)

The default ASR endpoint is `https://api.siliconflow.cn/v1/audio/transcriptions`. Any **OpenAI-compatible** `/v1/audio/transcriptions` endpoint will work. Edit the endpoint URL in `scripts/meeting_transcribe_batch.py`.

## File-format support

| Type | Supported |
|---|---|
| Audio (`.mp3` `.m4a` `.wav` `.flac` `.ogg` `.opus` `.aac` `.amr`) | ✅ |
| Video (`.mp4` `.mov` `.avi` `.mkv` ...) | ✅ (auto-extracts audio track) |

## Notes for non-Hermes users

1. **The `SKILL.md` file is not a generic spec** — its YAML frontmatter is parsed by Hermes Agent only. If you're a different agent, ignore the frontmatter and read the body, or just read this `AGENTS.md` instead.
2. **The `scripts/` directory has zero Hermes dependency** — it's plain Python + `av` + `requests`. Run it from anywhere.
3. **The `prompts/` directory is agent-agnostic** — paste the prompt text into any LLM chat and it will work.
4. **Privacy**: only the audio is uploaded to SiliconFlow for ASR. All other processing is local.
5. **SenseVoice language scope**: Mandarin, Cantonese, English, Japanese, Korean, and Chinese dialects (Sichuan / Shanghai / Tianjin / Min). European / Middle Eastern / African languages are **not** supported by this skill.

## License

[MIT](LICENSE) — Copyright (c) 2024 Y
