#!/usr/bin/env python3
"""
SQLite 会议存储模块
用法：
  python3 meeting_store.py save --title "xxx" --type "面试" ...
  python3 meeting_store.py list [--limit 20] [--type "面试"] [--from-date 2026-01-01]
  python3 meeting_store.py get --id 1
  python3 meeting_store.py search --query "关键词"
  python3 meeting_store.py stats
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# 数据库位置
DB_DIR = Path.home() / ".hermes" / "data"
DB_PATH = DB_DIR / "meeting_minutes.db"


def get_conn():
    """获取数据库连接，自动创建目录和表"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_tables(conn)
    return conn


def _init_tables(conn):
    """初始化表结构"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            meeting_type TEXT,
            date TEXT,
            duration_minutes REAL,
            source_file TEXT,
            transcript_json_path TEXT,
            summary_md TEXT,
            model TEXT,
            language TEXT,
            tags TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS meeting_chunks (
            id INTEGER PRIMARY KEY,
            meeting_id INTEGER REFERENCES meetings(id),
            chunk_index INTEGER,
            start_time REAL,
            end_time REAL,
            text TEXT,
            speaker TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_meetings_date ON meetings(date);
        CREATE INDEX IF NOT EXISTS idx_meetings_type ON meetings(meeting_type);
        CREATE INDEX IF NOT EXISTS idx_chunks_meeting ON meeting_chunks(meeting_id);
    """)


def _read_transcript_chunks(transcript_path):
    """读取 transcript.json，提取 chunks 列表"""
    if not transcript_path or not os.path.isfile(transcript_path):
        return []
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(json.dumps({"error": f"Failed to read transcript: {e}"}))
        return []

    # 支持多种常见格式
    chunks = []
    if isinstance(data, list):
        # 直接是 chunks 数组
        chunks = data
    elif isinstance(data, dict):
        # 常见 key: segments, chunks, sentences, utterances
        for key in ("segments", "chunks", "sentences", "utterances", "results"):
            if key in data and isinstance(data[key], list):
                chunks = data[key]
                break
        # 如果有 nested results
        if not chunks and "results" in data and isinstance(data["results"], dict):
            for key in ("segments", "chunks", "sentences", "utterances"):
                if key in data["results"] and isinstance(data["results"][key], list):
                    chunks = data["results"][key]
                    break
    return chunks


def _row_to_dict(row):
    """sqlite3.Row -> dict"""
    if row is None:
        return None
    return dict(row)


def cmd_save(args):
    """保存会议记录"""
    # 读取 summary 内容
    summary_text = ""
    if args.summary and os.path.isfile(args.summary):
        try:
            with open(args.summary, "r", encoding="utf-8") as f:
                summary_text = f.read()
        except OSError:
            pass
    elif args.summary:
        summary_text = args.summary  # 直接传入文本

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    tags = json.dumps(args.tags) if args.tags else None

    conn = get_conn()
    try:
        cursor = conn.execute(
            """INSERT INTO meetings
               (title, meeting_type, date, duration_minutes, source_file,
                transcript_json_path, summary_md, model, language, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                args.title,
                args.type,
                date_str,
                args.duration,
                args.source,
                args.transcript,
                summary_text,
                args.model,
                args.language,
                tags,
            ),
        )
        meeting_id = cursor.lastrowid

        # 自动提取 chunks
        chunks = _read_transcript_chunks(args.transcript)
        if chunks:
            chunk_rows = []
            for i, c in enumerate(chunks):
                # 兼容不同字段命名
                text = c.get("text") or c.get("content") or c.get("transcript") or ""
                speaker = c.get("speaker") or c.get("name") or c.get("channel") or None
                start = c.get("start") or c.get("start_time") or c.get("offset", 0.0)
                end = c.get("end") or c.get("end_time") or c.get("duration", 0.0)
                # 如果 end 是 duration，则计算绝对时间
                if "duration" in c and "end" not in c and "end_time" not in c:
                    end = start + (c.get("duration", 0) if isinstance(c.get("duration"), (int, float)) else 0)
                chunk_rows.append((meeting_id, i, float(start), float(end), text, speaker))
            conn.executemany(
                """INSERT INTO meeting_chunks
                   (meeting_id, chunk_index, start_time, end_time, text, speaker)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                chunk_rows,
            )

        conn.commit()

        result = {
            "status": "ok",
            "meeting_id": meeting_id,
            "chunks_inserted": len(chunks),
        }
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        conn.rollback()
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    finally:
        conn.close()


def cmd_list(args):
    """列出会议记录"""
    conn = get_conn()
    query = "SELECT * FROM meetings WHERE 1=1"
    params = []

    if args.type:
        query += " AND meeting_type = ?"
        params.append(args.type)
    if args.from_date:
        query += " AND date >= ?"
        params.append(args.from_date)
    if args.to_date:
        query += " AND date <= ?"
        params.append(args.to_date)

    query += " ORDER BY date DESC, id DESC"
    query += " LIMIT ?"
    params.append(args.limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    result = [_row_to_dict(r) for r in rows]
    print(json.dumps(result, ensure_ascii=False))


def cmd_get(args):
    """获取单个会议记录（含 chunks）"""
    conn = get_conn()
    meeting = conn.execute(
        "SELECT * FROM meetings WHERE id = ?", (args.id,)
    ).fetchone()

    if not meeting:
        print(json.dumps({"error": f"Meeting {args.id} not found"}))
        conn.close()
        sys.exit(1)

    chunks = conn.execute(
        "SELECT * FROM meeting_chunks WHERE meeting_id = ? ORDER BY chunk_index",
        (args.id,),
    ).fetchall()
    conn.close()

    result = _row_to_dict(meeting)
    result["chunks"] = [_row_to_dict(c) for c in chunks]
    print(json.dumps(result, ensure_ascii=False))


def cmd_search(args):
    """全文搜索标题和摘要"""
    conn = get_conn()
    like_pattern = f"%{args.query}%"
    rows = conn.execute(
        """SELECT * FROM meetings
           WHERE title LIKE ? OR summary_md LIKE ? OR tags LIKE ?
           ORDER BY date DESC, id DESC
           LIMIT ?""",
        (like_pattern, like_pattern, like_pattern, args.limit),
    ).fetchall()
    conn.close()

    result = [_row_to_dict(r) for r in rows]
    print(json.dumps(result, ensure_ascii=False))


def cmd_stats(args):
    """输出统计信息"""
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) as cnt FROM meetings").fetchone()["cnt"]

    # 按类型统计
    type_rows = conn.execute(
        "SELECT meeting_type, COUNT(*) as cnt FROM meetings GROUP BY meeting_type ORDER BY cnt DESC"
    ).fetchall()

    # 按月统计
    month_rows = conn.execute(
        """SELECT strftime('%Y-%m', date) as month, COUNT(*) as cnt
           FROM meetings WHERE date IS NOT NULL
           GROUP BY month ORDER BY month DESC"""
    ).fetchall()

    # 语言统计
    lang_rows = conn.execute(
        """SELECT language, COUNT(*) as cnt FROM meetings
           GROUP BY language ORDER BY cnt DESC"""
    ).fetchall()

    conn.close()

    result = {
        "total": total,
        "by_type": {r["meeting_type"] or "未分类": r["cnt"] for r in type_rows},
        "by_month": {r["month"]: r["cnt"] for r in month_rows},
        "by_language": {r["language"] or "未指定": r["cnt"] for r in lang_rows},
    }
    print(json.dumps(result, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="会议记录 SQLite 存储模块")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # save
    p_save = subparsers.add_parser("save", help="保存会议记录")
    p_save.add_argument("--title", required=True, help="会议标题")
    p_save.add_argument("--type", default="会议", help="会议类型 (默认: 会议)")
    p_save.add_argument("--date", default=None, help="日期 YYYY-MM-DD (默认: 今天)")
    p_save.add_argument("--duration", type=float, default=None, help="时长(分钟)")
    p_save.add_argument("--source", default=None, help="源文件路径")
    p_save.add_argument("--transcript", default=None, help="transcript.json 路径")
    p_save.add_argument("--summary", default=None, help="摘要文件路径或文本")
    p_save.add_argument("--model", default=None, help="转录模型名称")
    p_save.add_argument("--language", default=None, help="语言代码")
    p_save.add_argument("--tags", nargs="*", default=None, help="标签列表")

    # list
    p_list = subparsers.add_parser("list", help="列出会议记录")
    p_list.add_argument("--limit", type=int, default=20, help="最大返回数 (默认: 20)")
    p_list.add_argument("--type", default=None, help="按类型过滤")
    p_list.add_argument("--from-date", default=None, help="起始日期 YYYY-MM-DD")
    p_list.add_argument("--to-date", default=None, help="结束日期 YYYY-MM-DD")

    # get
    p_get = subparsers.add_parser("get", help="获取单个会议记录")
    p_get.add_argument("--id", type=int, required=True, help="会议 ID")

    # search
    p_search = subparsers.add_parser("search", help="全文搜索")
    p_search.add_argument("--query", required=True, help="搜索关键词")
    p_search.add_argument("--limit", type=int, default=20, help="最大返回数")

    # stats
    subparsers.add_parser("stats", help="输出统计信息")

    args = parser.parse_args()

    if args.command == "save":
        cmd_save(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "get":
        cmd_get(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "stats":
        cmd_stats(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
