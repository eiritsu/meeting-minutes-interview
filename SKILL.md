---
name: meeting-minutes-interview
description: 从面试录音/会议音频生成结构化会议纪要，含音频转录、说话人识别、LLM 修正、中英日韩多语言支持、中英混合双语输出。仅支持音频，视频需先抽音轨。**SiliconFlow SenseVoiceSmall 免费调用**。
version: 1.0.0
author: Y
tags: [meeting, minutes, audio-transcription, speaker-diarization, multilingual, ocr, free]
triggers:
  - 会议纪要
  - 面试纪要
  - 整理会议
  - 整理面试
  - meeting minutes
  - 录音转文字
  - 中英混合
---

# 会议纪要生成 v1.0

> 💰 **费用提示**：转录阶段使用 SiliconFlow `FunAudioLLM/SenseVoiceSmall`，**完全免费**，无时长/次数限制。只需一个 `SILICONFLOW_API_KEY` 即可。

支持**长会议**、**说话人识别**、**中英日韩多语言**、**LLM 修正**的完整会议纪要生成流程。

## ⚠️ Step 0: 前置检查

需要**至少一项**素材才能开始：

- 🎙️ **音频文件**（仅音频，不支持视频）
  - 支持：`.mp3` `.m4a` `.wav` `.flac` `.ogg` `.opus` `.aac` `.amr` 等
  - **不支持**：`.mp4` `.mov` `.avi` `.mkv` `.flv` `.webm` 等视频格式
  - 视频需先用 ffmpeg 抽音轨：`ffmpeg -i input.mp4 -vn -ac 1 -ar 16000 audio.wav`
- 📄 **会议平台导出的AI纪要**（`.txt`/`.rtf`/`.docx`/`.md`）
- 📝 **会议文字记录**
- 📋 **候选人简历**（面试场景，PDF/docx）

**没有素材时先提醒用户**，不要直接生成。

> 💡 为什么不支持视频：skill 设计上专注会议场景音轨处理，不涉及视频流的转码/抽帧/字幕提取，避免依赖复杂。如需视频支持请使用专业工具（如 ffmpeg 抽音轨后传入）。

---

## 🚀 一键流程（v1.0）

### 场景 A：拿到的就是音频文件

```bash
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input meeting.m4a \
    --meeting-type "产品评审会" \
    --duration-estimate 60
```

自动完成：
1. 抽音轨（无需，本就是音频）
2. 长音频自动切片（默认 10 分钟/段）
3. 串行转录（带 1.5s 间隔防限流）
4. 生成 3 个 Prompt 文件（修正/说话人画像/纪要）

**用户复制粘贴 Prompt 到对话** → 我（LLM）当场输出最终纪要。

### 场景 B：拿到的是视频文件

本 skill 不直接处理视频，需先抽音轨：

```bash
# 一行搞定：抽 16kHz mono WAV（ASR 最佳格式）
ffmpeg -i meeting.mp4 -vn -ac 1 -ar 16000 -c:a pcm_s16le meeting.wav

# 如果想保留 m4a 格式（更小）
ffmpeg -i meeting.mp4 -vn -ac 1 -ar 16000 -c:a aac meeting.m4a
```

参数说明：
- `-vn` 不要视频流
- `-ac 1` 单声道
- `-ar 16000` 16kHz 采样率（SiliconFlow SenseVoice 最佳）
- `-c:a pcm_s16le` / `aac` 输出格式

抽完音轨后按场景 A 处理。

---

## 📋 流程详解

### Step 1: 识别输入 & 选择路径

| 文件类型 | 工具 |
|---------|------|
| 音频 → 转录 | `meeting_transcribe_batch.py` / `run_pipeline.py` |
| AI纪要 → 解析 | `read_meeting_notes()` in SKILL.md（兼容） |
| PDF简历 → OCR | 兼容 v1.0 流程 |
| 文字记录 → 直接用 | 无需处理 |
| **视频** | ❌ **不支持**，需先抽音轨 |

### Step 2: 音频转录

**唯一 ASR 后端：SiliconFlow + SenseVoiceSmall（免费）**

> 💰 **价格提示**：`FunAudioLLM/SenseVoiceSmall` 在硅基流动平台**完全免费**调用，无时长/次数限制。仅需一个 `SILICONFLOW_API_KEY` 即可。

SiliconFlow 当前只提供 `FunAudioLLM/SenseVoiceSmall` 一个 ASR 模型，能力如下：

| 语种 | 支持质量 | 备注 |
|------|----------|------|
| 中文普通话 | ⭐⭐⭐⭐⭐ | 主语言 |
| 粤语 | ⭐⭐⭐⭐⭐ | |
| 英语 | ⭐⭐⭐⭐⭐ | |
| 日语 | ⭐⭐⭐⭐⭐ | |
| 韩语 | ⭐⭐⭐⭐⭐ | |
| 四川话/上海话/天津话/闽南语 | ⭐⭐⭐⭐ | 中文方言 |
| 欧洲语种/中东/非洲 | ❌ 不支持 | 不在本 skill 范围 |

#### 使用示例

```bash
# 默认（SenseVoiceSmall）
python3 meeting_transcribe_batch.py --input meeting.m4a

# 一键 runner
python3 run_pipeline.py --input meeting.m4a \
    --meeting-type "产品评审"
```

#### 环境变量

在 `~/.hermes/.env` 中配置：

```bash
SILICONFLOW_API_KEY=sk-...
```

### Step 3: LLM 修正（手工触发）

**3 个 Prompt 顺序使用**：

1. **`1_fix_transcript.md`**：错别字、口语化、中英术语（已通用化，支持任何 SenseVoice 支持的语言）
2. **`2_identify_speakers.md`**：说话人角色画像（S1→项目经理等，含多语言观察）
3. **`3_generate_minutes.md`**：生成最终双语 Markdown 纪要（字段名中英 + 内容原文+中文翻译）

**为什么不自动调用 LLM？** 节省外部 API 成本，且 LLM 的上下文能力强、对中英混合最友好。

### Step 4: 输出 Markdown 纪要

参考 `templates/meeting_minutes.md`，结构：

```markdown
# 会议纪要 / Meeting Minutes：XXX
- 时间/时长/形式/参会人/类型

## 一、议题概览 / Overview
## 二、详细讨论 / Detailed Discussion
## 三、决策事项 / Decisions
## 四、行动项 / Action Items
## 五、风险与阻碍 / Risks & Blockers
## 六、下次会议 / Next Meeting
## 附录：原始转录
```

---

## 🔧 工具脚本

```
scripts/
├── extract_audio.py               # 抽音轨（PyAV，16k mono WAV）
├── transcribe_single.py           # 单文件 SenseVoice（≤10min）
├── meeting_transcribe_batch.py    # 批量转录（长会议）
└── run_pipeline.py                # 全流程 runner（一键）
```

---

## 📊 性能参考

> 💰 **费用**：转录阶段使用 SiliconFlow SenseVoiceSmall（**免费**），仅 LLM 修正/纪要阶段有 API 成本（本 skill 让用户复制粘贴到对话由 LLM 处理）。

| 会议时长 | 切片数 | 转录耗时 | 修正+纪要 | 合计 |
|---------|--------|---------|-----------|------|
| 5 分钟 | 1 | 30s | 1 min | **2 min** |
| 30 分钟 | 3 | 1.5 min | 3 min | **5 min** |
| 1 小时 | 6 | 3 min | 5 min | **10 min** |
| 2 小时 | 12 | 6 min | 8 min | **16 min** |

---

---

## 多语言支持范围

| 语言家族 | 代表语种 | 支持 | ASR模型 |
|----------|----------|------|---------|
| **中文** | 普通话/粤语/上海话/四川话/天津话/闽南语 | ✅ | SenseVoiceSmall |
| **东亚** | 日语/韩语 | ✅ | SenseVoiceSmall |
| **欧洲/中东/非洲** | 英法德西俄意葡/阿拉伯波斯/斯瓦希里等 | ❌ | 不在本 skill 范围 |

> ℹ️ 如果未来需要欧洲/中东/非洲语种，可考虑：① 接 OpenAI Whisper API；② 本地跑 faster-whisper；③ 等待 SiliconFlow 上线新模型。

---

## 注意事项

1. **API Key 安全**：从 `<USER_HOME>/.hermes/.env` 读取，不硬编码
2. **限流防护**：每段间隔 1.5s 串行调用，避免 429
3. **格式要求**：先抽 16k mono WAV，再上传（兼容性最好）
4. **大文件**：单文件 >100MB 需先压缩或用 OSS 代理
5. **多说话人**：会议中英文人名建议加简历/参会人名单辅助识别
6. **隐私**：本地处理为主，只有音轨上传到 SiliconFlow
7. **多语言**：仅支持 SenseVoice 原生语种（中/英/日/韩 + 中文方言），其他语种不支持