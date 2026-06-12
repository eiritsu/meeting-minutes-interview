# meeting-minutes-interview

从面试录音/会议音频生成结构化会议纪要的 Hermes Agent skill。

## 功能

- 音频转录（SiliconFlow SenseVoiceSmall，免费）
- 长音频自动切片（默认 10 分钟/段）
- 说话人识别 & 角色画像
- LLM 修正转录文本
- 双语 Markdown 纪要输出（中英日韩多语言）

## 支持格式

| 类型 | 格式 |
|------|------|
| 音频 | `.mp3` `.m4a` `.wav` `.flac` `.ogg` `.opus` `.aac` `.amr` |
| 视频 | ❌ 不支持，需先抽音轨 |

## 前置条件

- Python 3.10+
- [uv](https://github.com/astral-sh/uv)（Python 包管理）
- ffmpeg（仅视频抽音轨需要）
- SiliconFlow API Key（免费注册获取）

## 快速开始

### 1. 配置 API Key

在 `~/.hermes/.env` 中添加：

```
SILICONFLOW_API_KEY=sk-xxx
```

### 2. 一键运行

```bash
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input meeting.m4a \
    --meeting-type "产品评审会" \
    --duration-estimate 60
```

### 3. 后续处理

脚本会生成 3 个 Prompt 文件，按顺序复制粘贴到 LLM 对话中处理：

1. `1_fix_transcript.md` → 修正转录
2. `2_identify_speakers.md` → 说话人画像
3. `3_generate_minutes.md` → 生成纪要

## 视频处理

本 skill 不直接支持视频，需先抽音轨：

```bash
ffmpeg -i meeting.mp4 -vn -ac 1 -ar 16000 audio.wav
```

## 目录结构

```
meeting-minutes-interview/
├── SKILL.md                 # Skill 定义
├── README.md
├── scripts/
│   ├── extract_audio.py     # 抽音轨
│   ├── transcribe_single.py # 单文件转录
│   ├── meeting_transcribe_batch.py  # 批量转录
│   └── run_pipeline.py      # 全流程 runner
├── prompts/
│   ├── fix_transcript.txt   # 修正转录 prompt
│   ├── identify_speakers.txt # 说话人画像 prompt
│   ├── merge_speakers.txt   # 合并说话人 prompt
│   └── generate_minutes.txt # 生成纪要 prompt
└── templates/
    └── meeting_minutes.md   # 纪要模板
```

## 安装到 Hermes

```bash
hermes skills install github:your-name/meeting-minutes-interview
```

## License

MIT
