# meeting-minutes-interview

> 把面试录音和会议音频一键转成结构化、双语会议纪要 —— 转录、说话人识别、LLM 修正，全流程一条龙。

[English](README.md) | 简体中文

![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue?logo=python&logoColor=white)
![SiliconFlow](https://img.shields.io/badge/ASR-SiliconFlow%20SenseVoiceSmall-00B8A9?logo=waveform&logoColor=white)
![Last Commit](https://img.shields.io/github/last-commit/eiritsu/meeting-minutes-interview)
![Stars](https://img.shields.io/github/stars/eiritsu/meeting-minutes-interview?style=social)

---

## ✨ 功能

| | |
|---|---|
| 🎙️ **长音频转录** | 自动切片（默认 10 分钟/段），串行调用防限流 |
| 🗣️ **说话人识别** | 自动区分多人并打标签 |
| ✍️ **LLM 修正** | 3 步 Prompt 流水线：修正转录 → 说话人画像 → 生成纪要 |
| 🌏 **多语言支持** | 普通话/粤语/英语/日语/韩语 + 四川话/上海话/天津话/闽南语 |
| 🌐 **双语输出** | 纪要默认中英双语（原文 + 翻译） |
| 💰 **ASR 免费** | 使用 SiliconFlow `SenseVoiceSmall`，无时长/次数限制 |

---

## 📋 支持格式

| 类型 | 格式 |
|---|---|
| 音频 ✅ | `.mp3` `.m4a` `.wav` `.flac` `.ogg` `.opus` `.aac` `.amr` |
| 视频 ❌ | 不直接支持，需先抽音轨（见下） |

---

## 🧰 前置条件

- Python 3.10+
- [uv](https://github.com/astral-sh/uv)（Python 包管理）
- `ffmpeg` —— 仅视频抽音轨时需要
- SiliconFlow API Key —— [免费注册](https://siliconflow.cn)，Key 放在 `~/.hermes/.env`
- （可选）自建或其他 **OpenAI 兼容的 ASR endpoint** —— 见下方 [🔌 配置说明](#-配置说明)

---

## 🚀 快速开始

### 1. 配置 API Key

在 `~/.hermes/.env` 中添加：

```
SILICONFLOW_API_KEY=sk-xxx...your-key
```

### 2. 一键运行

```bash
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input meeting.m4a \
    --meeting-type "产品评审会" \
    --duration-estimate 60
```

脚本会自动完成：
1. 抽音轨（输入本身是音频则跳过）
2. 长音频自动切片（10 分钟/段）
3. 串行转录（带 1.5s 间隔防限流）
4. 生成 3 个 Prompt 文件供 LLM 修正

### 3. LLM 修正（手工触发）

把生成的 3 个 Prompt 按顺序复制粘贴到 LLM 对话中：

1. `1_fix_transcript.md` —— 修正转录错别字、口语化、保留专业术语
2. `2_identify_speakers.md` —— 说话人角色画像（S1 → 项目经理等）
3. `3_generate_minutes.md` —— 生成最终双语 Markdown 纪要

> 为什么不自动调 LLM？节省外部 API 成本，且 LLM 的上下文能力强、对中英混合最友好。

---

## 🔌 配置说明

默认按 SiliconFlow 配置。**API Key**（环境变量）和 **API URL**（代码硬编码，改源码）都容易覆盖。

### 1. API Key —— 通过环境变量

Key 从 `~/.hermes/.env` 的 `SILICONFLOW_API_KEY` 行读取。要换成其他 Key（比如自建网关自己的 Key），改这一行即可，无需动代码：

```bash
# 编辑 ~/.hermes/.env
SILICONFLOW_API_KEY=sk-xxx...your-key
```

> 如果你不用 Hermes Agent，把 key 加载代码（`scripts/transcribe_single.py:16` 和 `scripts/meeting_transcribe_batch.py:43` 里的环境变量读取）改成你自己存放密钥的位置即可。

### 2. API URL —— 改源码里两行

ASR endpoint 在两处**硬编码**。要换地址（比如自建 `faster-whisper` 服务器，或 SiliconFlow 区域镜像）：

| 文件 | 行号 | 默认值 | 改成 |
|---|---|---|---|
| `scripts/transcribe_single.py`        | **L29**  | `https://api.siliconflow.cn/v1/audio/transcriptions` | 你的 endpoint |
| `scripts/meeting_transcribe_batch.py` | **L110** | `https://api.siliconflow.cn/v1/audio/transcriptions` | 你的 endpoint |

任何 **OpenAI 兼容**的 `/v1/audio/transcriptions` endpoint 都能用（请求/响应遵循 OpenAI Whisper API 规范）。

示例 —— 切到本地 `faster-whisper` 服务器：

```python
# scripts/transcribe_single.py, 大约 L29
url = "http://localhost:8000/v1/audio/transcriptions"
```

照常跑 pipeline 即可。`Authorization: Bearer sk-xxx...your-key` 请求头会自动带上，本地服务器可忽略或自用。

> 🤝 **欢迎贡献** —— 如果你希望把 `SILICONFLOW_BASE_URL` 做成正式环境变量，欢迎 PR。改动只需两行。

---

---

## 🎥 视频文件处理

本 skill 不直接处理视频，需先抽音轨：

```bash
# 16kHz mono WAV（SenseVoice 最佳格式）
ffmpeg -i meeting.mp4 -vn -ac 1 -ar 16000 -c:a pcm_s16le meeting.wav

# 或保留 m4a 格式（更小）
ffmpeg -i meeting.mp4 -vn -ac 1 -ar 16000 -c:a aac meeting.m4a
```

抽完音轨后按上方「快速开始」流程处理。

---

## 📁 目录结构

```
meeting-minutes-interview/
├── SKILL.md                            # Skill 定义（Hermes Agent 加载）
├── README.md                           # English
├── README.zh-CN.md                     # 简体中文（本文件）
├── LICENSE                             # MIT
├── scripts/
│   ├── extract_audio.py                # 抽音轨（PyAV，16k mono WAV）
│   ├── transcribe_single.py            # 单文件 SenseVoice（≤10 min）
│   ├── meeting_transcribe_batch.py     # 批量转录（长会议）
│   └── run_pipeline.py                 # 一键全流程 runner
├── prompts/
│   ├── fix_transcript.txt              # 第 1 步：修正转录
│   ├── identify_speakers.txt           # 第 2 步：说话人画像
│   ├── merge_speakers.txt              # 跨片段说话人合并
│   └── generate_minutes.txt            # 第 3 步：生成纪要
└── templates/
    └── meeting_minutes.md              # 最终输出模板
```

---

## 📊 性能参考

> 费用：转录阶段 SiliconFlow SenseVoiceSmall 免费。仅 LLM 修正/纪要阶段有 API 成本（且本 skill 让用户复制粘贴到对话由 LLM 处理，透明可控）。

| 会议时长 | 切片数 | 转录耗时 | 修正+纪要 | 合计 |
|---|---|---|---|---|
| 5 分钟   | 1  | 30 s    | 1 min  | **2 min**  |
| 30 分钟  | 3  | 1.5 min | 3 min  | **5 min**  |
| 1 小时   | 6  | 3 min   | 5 min  | **10 min** |
| 2 小时   | 12 | 6 min   | 8 min  | **16 min** |

---

## 📥 在 Hermes Agent 中安装

```bash
hermes skills install github:eiritsu/meeting-minutes-interview
```

或把整个目录放到 `~/.hermes/skills/meeting-minutes-interview/` 后重启 Hermes。

---

## 🌍 语言支持范围

| 语言家族 | 代表语种 | 支持 | ASR 模型 |
|---|---|---|---|
| **中文** | 普通话/粤语/上海话/四川话/天津话/闽南语 | ✅ | SenseVoiceSmall |
| **东亚** | 日语/韩语 | ✅ | SenseVoiceSmall |
| **欧洲/中东/非洲** | 英法德西俄意葡/阿拉伯波斯/斯瓦希里等 | ❌ | 不在本 skill 范围 |

> 如需其他语种，可自行接 OpenAI Whisper API 或本地 `faster-whisper`。

---

## ⚠️ 注意事项

1. **API Key 安全** —— 从 `~/.hermes/.env` 读取，不硬编码
2. **限流防护** —— 每段间隔 1.5s 串行调用，避免 429
3. **格式要求** —— 先抽 16k mono WAV，再上传（兼容性最好）
4. **大文件** —— 单文件 >100MB 需先压缩或用 OSS 代理
5. **多说话人** —— 建议附上参会人名单/简历以提升识别准确率
6. **隐私** —— 本地处理为主，只有音轨上传到 SiliconFlow 做 ASR
7. **多语言** —— 仅支持 SenseVoice 原生语种（中/英/日/韩 + 中文方言）

---

## 📄 License

[MIT](LICENSE) —— Copyright (c) 2024 Y

---

Built with ❤️ by [Y](https://github.com/eiritsu)
