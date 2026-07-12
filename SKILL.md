---
name: meeting-minutes-interview
description: 从面试录音/会议音频生成结构化会议纪要，含音频归一化、VAD切片、ASR转录、说话人识别、LLM自动摘要、会议历史存储。多语言支持，双语输出。SiliconFlow SenseVoiceSmall 免费调用，LLM 摘要用当前会话模型。
version: 2.0.1
author: y
tags: [meeting, minutes, audio-transcription, speaker-diarization, multilingual, ocr, free, vad, auto-summary]
related_skills: []
triggers:
  - 会议纪要
  - 面试纪要
  - 整理会议
  - 整理面试
  - meeting minutes
  - 录音转文字
  - 中英混合
---

# 会议纪要生成 v2.0

> 💰 **费用提示**：转录使用 SiliconFlow `FunAudioLLM/SenseVoiceSmall`，**完全免费**。摘要使用当前会话的 LLM 模型，**零额外成本**。

## v2.0 新特性

- 🎯 **VAD 静音检测切片**：在自然停顿处分割，不再固定时间切，转录质量更高
- 🔊 **EBU R128 响度归一化**：统一音频响度，减少 ASR 误识别
- 🤖 **LLM 自动摘要**：Agent 读取转录后自动用当前模型生成纪要，无需手动粘贴 Prompt
- 📝 **会议模板**：面试/周会/产品评审/通用 四种专用模板
- 💾 **SQLite 会议历史**：自动保存转录和纪要，支持搜索和统计

---

## ⚠️ Step 0: 前置检查

需要**音频文件**：

- 支持：`.mp3` `.m4a` `.wav` `.flac` `.ogg` `.opus` `.aac` `.amr`
- 视频：`.mp4` `.mov` `.avi` `.mkv` 等（自动抽音轨）
- 环境变量：`~/.hermes/.env` 中配置 `SILICONFLOW_API_KEY=sk-...`

**没有素材时先提醒用户**，不要直接生成。

---

## 🚀 一键流程

### 基础用法

```bash
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input meeting.m4a \
    --meeting-type "产品评审会"
```

### 面试专用

```bash
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input interview.mp3 \
    --meeting-type "技术面试" \
    --template interview \
    --title "张三 - 后端工程师二面"
```

### 周会

```bash
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input weekly.mp3 \
    --meeting-type "周会" \
    --template weekly
```

### 跳过归一化（音频质量好时）

```bash
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input meeting.wav \
    --no-normalize
```

---

## 📋 完整工作流

```
Step 1: 归一化 ──→ Step 2: VAD切片 ──→ Step 3: ASR转录 ──→ Step 4: Agent自动摘要
  (EBU R128)      (静音检测)        (SiliconFlow)       (当前LLM模型)
```

### Step 1: 音频预处理

`normalize_audio.py` 自动完成：
- EBU R128 响度归一化（目标 -16 LUFS）
- 输出 16kHz mono WAV（ASR 最佳格式）
- 如果 ffmpeg 不可用，fallback 到 peak normalization

### Step 2: VAD 切片

`vad_chunk.py` 基于 RMS 能量检测静音：
- 静音阈值：-40dB（可调）
- 最短静音：1.5s
- 最大片段：900s（15 分钟）
- 边界重叠：0.5s（避免截断单词）
- **自动过滤开头/结尾3秒内的静音段**（防止前导静音导致切片失败）
- 静音检测失败时 fallback 到固定时间切片



### Step 3: ASR 转录

SiliconFlow `SenseVoiceSmall`（免费）：
- 中文普通话/粤语/方言、英日韩
- 每段间隔 1.5s 防限流
- 支持 Paraformer-V2（带说话人分段）

### Step 4: Agent 自动摘要

**这是 v2.0 的核心改进**——Agent 读取转录数据后，使用当前会话的 LLM 模型自动生成纪要：

1. Agent 读取 `transcript.json`
2. 按模板生成修正后的文本 + 说话人画像 + 最终纪要
3. 无需用户手动复制粘贴 Prompt
4. 支持四种模板（interview/weekly/product_review/generic）

---

## 📝 模板选择

| 模板 | 用途 | 特色 |
|------|------|------|
| `interview` | 面试评估 | 技术能力/软技能评分、录用建议、后续步骤 |
| `weekly` | 周会/站会 | 本周进展、阻塞问题、下周计划、风险跟踪 |
| `product_review` | 产品评审 | 方案评估、技术可行性、资源排期、决策记录 |
| `generic` | 通用会议 | 议题概览、详细讨论、决策事项、行动项 |

---

## 💾 会议历史

自动保存到 `~/.hermes/data/meeting_minutes.db`：

```bash
# 查看历史
python3 scripts/meeting_store.py list --limit 10

# 按类型筛选
python3 scripts/meeting_store.py list --type "面试"

# 搜索
python3 scripts/meeting_store.py search --query "Kubernetes"

# 统计
python3 scripts/meeting_store.py stats
```

---

## 🔧 工具脚本

```
scripts/
├── run_pipeline.py              # 一键全流程 runner
├── vad_chunk.py                 # VAD 静音检测切片
├── normalize_audio.py           # EBU R128 响度归一化
├── meeting_transcribe_batch.py  # 批量转录（长会议）
├── transcribe_single.py         # 单文件转录
├── extract_audio.py             # 音轨抽取
└── meeting_store.py             # SQLite 会议历史

prompts/
├── fix_transcript.txt           # 转录修正
├── identify_speakers.txt        # 说话人画像
├── generate_minutes.txt         # 通用纪要
├── template_interview.txt       # 面试专用
├── template_weekly.txt          # 周会专用
└── template_product_review.txt  # 产品评审专用
```

---

## 📊 性能参考

| 会议时长 | 切片数 | 转录耗时 | 摘要(自动) | 合计 |
|---------|--------|---------|-----------|------|
| 5 分钟 | 1-2 | 30s | 1 min | **2 min** |
| 30 分钟 | 3-5 | 1.5 min | 3 min | **5 min** |
| 1 小时 | 5-8 | 3 min | 5 min | **10 min** |
| 2 小时 | 8-12 | 6 min | 8 min | **16 min** |

---

## ⚙️ 配置

在 `~/.hermes/.env` 中：

```bash
SILICONFLOW_API_KEY=sk-...
```

可选：LLM 摘要 API（如需独立于当前会话的 LLM）：

```bash
# OpenAI 兼容 API（可选，当前会话模型优先）
LLM_API_KEY=sk-...
LLM_API_BASE=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

---

## ⚠️ Pitfalls

1. **Python 3.9 type annotations**：macOS 系统自带 Python 3.9.6，**不支持** `str | None` 语法（需要 3.10+）。scripts/ 下的 Python 文件必须用 `from typing import Optional` + `Optional[str]` 代替。写完后 `python3 -c "import ast; ast.parse(open('script.py').read())"` 快速验证语法。
2. **ffmpeg 路径**：macOS Homebrew 装在 `/opt/homebrew/bin/ffmpeg`，非 Homebrew 装在 `/usr/local/bin/ffmpeg`。脚本中用 `shutil.which()` + 硬编码 fallback 双重检测。
3. **VAD 边缘静音陷阱**：`vad_chunk.py` 在检测到的静音段中心点切片时，必须先过滤掉音频开头/结尾3秒内的静音段（`filter_edge_silences`）。否则前导静音会产生极小的第一个 chunk，后续 chunk 的 overlap 区域与其重叠，导致 merge 逻辑把所有 chunk 合并成一个。这是最常见的 VAD 切片 bug。
3. **API Key 安全**：从 `~/.hermes/.env` 读取，不硬编码
4. **限流防护**：每段间隔 1.5s 串行调用，避免 429
5. **格式要求**：自动处理格式，无需手动转换
6. **大文件**：单文件 >100MB 需先压缩或用 OSS 代理
7. **多说话人**：会议中英文人名建议加简历/参会人名单辅助识别
8. **隐私**：本地处理为主，只有音轨上传到 SiliconFlow
9. **多语言**：支持中/英/日/韩 + 中文方言
10. **Skill 文档自包含**：不在 SKILL.md 或 prompts 中引用外部项目 URL/名称（如 meetily 等竞品），保持 skill 独立可读
