# AGENTS.md — meeting-minutes-interview

> **Note to AI assistants (Codex CLI, Claude Code, Cursor, Windsurf, OpenClaw, generic LLMs, etc.)**:
> This file is the **agent-agnostic** entry point for this skill. It describes what the skill does and how to use it from any LLM-powered environment.
>
> If you are **Hermes Agent**, ignore this file and read [`SKILL.md`](./SKILL.md) instead — that file's YAML frontmatter is the canonical skill descriptor and is required for `hermes skills install` to recognize this skill.

## What this skill does

Takes interview recordings or meeting audio and produces structured, bilingual (Chinese + English) Markdown meeting minutes through a 4-step pipeline:

1. **Extract audio** from the source file (if it's a video)
2. **Transcribe** audio chunks via SiliconFlow's free `SenseVoiceSmall` ASR (Mandarin / Cantonese / English / Japanese / Korean + Chinese dialects)
3. **LLM-refine** the raw transcript through 3 sequential prompts:
   - Fix ASR errors and formalize spoken language
   - Identify and label speakers by role
   - Generate the final bilingual Markdown minutes
4. **Output** the minutes in a standard template

## Quick start — for any LLM agent

### Prerequisites

- Python 3.10+
- [`uv`](https://github.com/astral-sh/uv) (Python package manager)
- `ffmpeg` — only if you need to extract audio from a video file
- A **SiliconFlow API key** ([free signup](https://siliconflow.cn)) stored at `SILICONFLOW_API_KEY` in `~/.hermes/.env`
  - If you don't have `~/.hermes/.env` (e.g. you're not running Hermes Agent), create it: `echo "SILICONFLOW_API_KEY=*** >> ~/.hermes/.env`
  - The skill reads from this specific path. Edit [`scripts/transcribe_single.py:16`](./scripts/transcribe_single.py) and [`scripts/meeting_transcribe_batch.py:43`](./scripts/meeting_transcribe_batch.py) if you want to use a different env file location.

### Run the pipeline

```bash
# From the repo root
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input meeting.m4a \
    --meeting-type "Product Review" \
    --duration-estimate 60
```

This produces 3 prompt files in the working directory:
- `1_fix_transcript.md`
- `2_identify_speakers.md`
- `3_generate_minutes.md`

### Feed the prompts back to your LLM

Open each prompt file in order, **copy the prompt body into your LLM chat** along with the referenced transcript text. The prompts are agent-agnostic — they work with any LLM that can follow instructions in Chinese/English.

1. **`1_fix_transcript.md`** — fix ASR errors, normalize spoken language, preserve technical terms
2. **`2_identify_speakers.md`** — assign roles to speakers (S1 → Project Manager, etc.)
3. **`3_generate_minutes.md`** — produce the final bilingual Markdown minutes (original + Chinese translation)

The output template is [`templates/meeting_minutes.md`](./templates/meeting_minutes.md).

## Repository layout

```
meeting-minutes-interview/
├── SKILL.md                            # Hermes Agent skill descriptor (frontmatter)
├── AGENTS.md                           # ← This file (agent-agnostic entry point)
├── README.md                           # English (project overview)
├── README.zh-CN.md                     # 简体中文
├── LICENSE                             # MIT
├── scripts/                            # Pure Python — no agent dependency
│   ├── extract_audio.py                # PyAV, 16k mono WAV
│   ├── transcribe_single.py            # SenseVoice (≤10 min)
│   ├── meeting_transcribe_batch.py     # SenseVoice (long audio)
│   └── run_pipeline.py                 # One-shot runner
├── prompts/                            # Agent-agnostic LLM prompts
│   ├── fix_transcript.txt
│   ├── identify_speakers.txt
│   ├── merge_speakers.txt
│   └── generate_minutes.txt
└── templates/
    └── meeting_minutes.md              # Output template
```

## Custom ASR endpoint (optional)

The default ASR endpoint is hardcoded to `https://api.siliconflow.cn/v1/audio/transcriptions` in:
- `scripts/transcribe_single.py` line **29**
- `scripts/meeting_transcribe_batch.py` line **110**

Any **OpenAI-compatible** `/v1/audio/transcriptions` endpoint will work (e.g. a self-hosted `faster-whisper` server). Just edit those two lines to point at your endpoint.

## File-format support

| Type | Supported |
|---|---|
| Audio (`.mp3` `.m4a` `.wav` `.flac` `.ogg` `.opus` `.aac` `.amr`) | ✅ |
| Video (`.mp4` `.mov` `.avi` `.mkv` ...) | ❌ — extract audio first with ffmpeg: `ffmpeg -i input.mp4 -vn -ac 1 -ar 16000 -c:a pcm_s16le out.wav` |

## Notes for non-Hermes users

1. **The `SKILL.md` file is not a generic spec** — its YAML frontmatter (the `name:` / `triggers:` block at the top) is parsed by Hermes Agent only. If you're a different agent, ignore the frontmatter and read the body, or just read this `AGENTS.md` instead.
2. **The `scripts/` directory has zero Hermes dependency** — it's plain Python + `av` + `requests`. Run it from anywhere.
3. **The `prompts/` directory is agent-agnostic** — paste the prompt text into any LLM chat and it will work.
4. **No environment variables other than `SILICONFLOW_API_KEY`** are read. The endpoint URL is hardcoded (see "Custom ASR endpoint" above).
5. **Privacy**: only the audio is uploaded to SiliconFlow for ASR. All other processing is local.
6. **SenseVoice language scope**: Mandarin, Cantonese, English, Japanese, Korean, and Chinese dialects (Sichuan / Shanghai / Tianjin / Min). European / Middle Eastern / African languages are **not** supported by this skill.

## License

[MIT](LICENSE) — Copyright (c) 2024 Y
