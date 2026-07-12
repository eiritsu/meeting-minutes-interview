# meeting-minutes-interview

> 从面试录音和会议音频生成结构化双语会议纪要——转录、说话人识别、LLM 摘要一体化流程。

[English](README.md) | 简体中文

![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue?logo=python&logoColor=white)
![SiliconFlow](https://img.shields.io/badge/ASR-SiliconFlow%20SenseVoiceSmall-00B8A9?logo=waveform&logoColor=white)

---

## ✨ 特性

| | |
|---|---|
| 🔊 **音频归一化** | EBU R128 响度归一化（-16 LUFS），统一 ASR 输入质量 |
| 🎯 **VAD 切片** | 基于静音检测在自然停顿处分割，不再固定时间切 |
| 🎙️ **长音频转录** | 自动切片 + 串行转录 + 限流保护 |
| 🗣️ **说话人识别** | 检测并标注多个说话人角色 |
| 🌐 **多语言** | 中文普通话/粤语/方言、英日韩 |
| 📝 **会议模板** | 面试/周会/产品评审/通用 四种专用模板 |
| 🤖 **LLM 自动摘要** | Agent 用当前会话模型自动生成纪要，无需手动粘贴 |
| 💾 **会议历史** | SQLite 存储，支持搜索和统计 |
| 🎬 **视频支持** | 自动从视频中抽取音轨 |
| 💰 **完全免费** | SiliconFlow SenseVoiceSmall，无使用限制 |

## 🚀 快速开始

### 前置条件

- Python 3.10+
- [uv](https://github.com/astral-sh/uv)
- ffmpeg（用于响度归一化和视频音轨抽取）
- SiliconFlow API Key — [免费注册](https://siliconflow.cn)，存入 `~/.hermes/.env`：
  ```
  SILICONFLOW_API_KEY=sk-...
  ```

### 运行

```bash
# 安装依赖
uv pip install av requests

# 基础用法
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input meeting.m4a \
    --meeting-type "产品评审会"

# 面试专用模板
uv run --with av --with requests python3 scripts/run_pipeline.py \
    --input interview.mp3 \
    --meeting-type "技术面试" \
    --template interview \
    --title "张三 - 后端工程师二面"
```

### 可用模板

| 模板 | 用途 |
|------|------|
| `interview` | 技术/HR 面试——候选人评估、评分、录用建议 |
| `weekly` | 周会/站会——本周进展、阻塞、下周计划、风险跟踪 |
| `product_review` | 产品评审——方案评估、技术可行性、资源排期、决策记录 |
| `generic` | 通用会议——议题概览、详细讨论、决策事项、行动项 |

## 📋 流程

```
音频输入
  ↓
1. 归一化（EBU R128，-16 LUFS）
  ↓
2. VAD 切片（在自然停顿处分割）
  ↓
3. ASR 转录（SiliconFlow SenseVoiceSmall，免费）
  ↓
4. LLM 自动摘要（当前会话模型）
  ↓
5. SQLite 存储会议历史
```

## 📁 项目结构

```
scripts/
├── run_pipeline.py              # 一键全流程 runner
├── vad_chunk.py                 # VAD 静音检测切片
├── normalize_audio.py           # EBU R128 响度归一化
├── meeting_store.py             # SQLite 会议历史存储
├── extract_audio.py             # 音轨抽取
├── transcribe_single.py         # 单文件转录
└── meeting_transcribe_batch.py  # 批量转录

prompts/
├── fix_transcript.txt           # 转录修正
├── identify_speakers.txt        # 说话人画像
├── generate_minutes.txt         # 通用纪要
├── template_interview.txt       # 面试专用
├── template_weekly.txt          # 周会专用
└── template_product_review.txt  # 产品评审专用
```

## 📊 性能参考

| 会议时长 | 切片数 | 转录耗时 | 摘要(自动) | 合计 |
|---------|--------|---------|-----------|------|
| 5 分钟 | 1-2 | 30s | 1 min | **2 min** |
| 30 分钟 | 3-5 | 1.5 min | 3 min | **5 min** |
| 1 小时 | 5-8 | 3 min | 5 min | **10 min** |
| 2 小时 | 8-12 | 6 min | 8 min | **16 min** |

## 🛠️ 高级选项

```bash
# 跳过归一化（音频质量好时）
--no-normalize

# 跳过 VAD，用固定时间切片
--no-vad --chunk-seconds 300

# 指定转录模型
--model Paraformer-V2

# 跳过 SQLite 存储
--no-store
```

## 🔒 隐私

- 仅音频上传到 SiliconFlow 做 ASR
- 其他处理全部本地完成
- 会议历史存储在 `~/.hermes/data/meeting_minutes.db`

## 📄 许可证

[MIT](LICENSE) — Copyright (c) 2024 Y
