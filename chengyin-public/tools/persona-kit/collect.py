# -*- coding: utf-8 -*-
"""把 companions.json 里的一段真实对话，导出成盲判用的 pack。

用法：
    python collect.py                      # 导最近的所有群 + 私聊
    python collect.py --out packet.md
    python collect.py --since-hours 6      # 只看最近 6 小时

产物是给**判官**看的：不含 rubric、不含探针、不含任何项目名，只标 A（对方）和 B（待判方）。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # 被别的程序 import 时 stdout 可能不是 TextIO，忽略即可

DEFAULT_COMPANIONS = r"D:\chengyin\astrbot\data\plugin_data\astrbot_plugin_private_companion\companions.json"
DEFAULT_LM = r"D:\chengyin\astrbot\data\plugin_data\astrbot_plugin_livingmemory\conversations.db"
DEFAULT_BOT_ID = "1234567890"


def collect_from_lm(db_path: str, since_hours: float | None, group_names: dict[str, str] | None = None) -> list[dict]:
    """从 livingmemory 的 conversations.db 里取对话。

    这是唯一同时存着**私聊**双方消息的地方——companions.json 只有群聊的 recent_messages
    和私聊的最后一条，导不出整段私聊。
    """
    import sqlite3

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        rows = con.execute(
            "select session_id, role, content, sender_name, timestamp from messages order by id asc"
        ).fetchall()
    finally:
        con.close()

    cutoff = time.time() - since_hours * 3600 if since_hours is not None else 0.0
    gnames = group_names or {}
    out: list[dict] = []
    for session_id, role, content, sender_name, ts in rows:
        if not ts or float(ts) < cutoff:
            continue
        text = str(content or "").replace("\n", " ").strip()
        if not text:
            continue
        sid = str(session_id or "")
        if "GroupMessage:" in sid:
            gid = sid.rsplit(":", 1)[-1]
            ch = f"群 {gnames.get(gid, gid)}"
        elif "FriendMessage:" in sid:
            ch = f"私聊 {sid.rsplit(':', 1)[-1]}"
        else:
            ch = sid
        row = {"ts": float(ts), "ch": ch, "who": "B" if role == "assistant" else "A", "text": text}
        if row["who"] == "A" and sender_name:
            row["name"] = str(sender_name)
        out.append(row)
    out.sort(key=lambda r: r["ts"])
    return out


def _fmt_ts(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%m-%d %H:%M:%S")
    except Exception:
        return "??"


def collect(path: str, bot_id: str, since_hours: float | None) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    cutoff = time.time() - since_hours * 3600 if since_hours is not None else 0.0
    rows: list[dict] = []

    # 私聊：最后一条用户消息 + 最后一条机器人消息
    for uid, u in (data.get("users") or {}).items():
        if not isinstance(u, dict):
            continue
        for key, who in (("last_user_message", "A"), ("last_companion_message", "B")):
            v = u.get(key)
            if isinstance(v, dict):
                v = v.get("text")
            ts = u.get(f"{key}_at") or 0
            if isinstance(v, str) and v.strip() and float(ts) >= cutoff:
                rows.append({"ts": float(ts), "ch": f"私聊 {uid}", "who": who, "text": v.strip()})

    # 群聊：recent_messages 与 recent_bot_replies 按时间合并
    for gid, g in (data.get("groups") or {}).items():
        if not isinstance(g, dict):
            continue
        for m in g.get("recent_messages") or []:
            if not isinstance(m, dict):
                continue
            ts = float(m.get("ts") or 0)
            text = m.get("text")
            if not isinstance(text, str) or not text.strip() or ts < cutoff:
                continue
            is_bot = str(m.get("sender_id") or "") == bot_id
            rows.append({
                "ts": ts,
                "ch": f"群 {g.get('group_name') or gid}",
                "who": "B" if is_bot else "A",
                "name": m.get("name") or m.get("identity_name") or m.get("sender_id"),
                "text": text.strip(),
            })
        for m in g.get("recent_bot_replies") or []:
            if not isinstance(m, dict):
                continue
            ts = float(m.get("ts") or 0)
            text = m.get("text")
            if isinstance(text, str) and text.strip() and ts >= cutoff:
                rows.append({"ts": ts, "ch": f"群 {g.get('group_name') or gid}", "who": "B", "text": text.strip()})

    rows.sort(key=lambda r: r["ts"])
    # 同一个 ch 内，A 的相邻重复去掉
    out: list[dict] = []
    for r in rows:
        if out and out[-1]["who"] == r["who"] == "A" and out[-1]["text"] == r["text"]:
            continue
        out.append(r)
    return out


def render(rows: list[dict]) -> str:
    lines = [
        "# 聊天记录（供盲判）",
        "",
        "B 是被审核方。请按 rubric 判 B 的每条回复。",
        "",
    ]
    # 先按频道归组，避免多个频道的消息按时间交错时把同一频道拆成好几节
    order: list[str] = []
    buckets: dict[str, list[dict]] = {}
    for r in rows:
        if r["ch"] not in buckets:
            buckets[r["ch"]] = []
            order.append(r["ch"])
        buckets[r["ch"]].append(r)

    for ch in order:
        lines += ["", f"## {ch}", "", "| 时间 | 方 | 内容 |", "|---|---|---|"]
        for r in buckets[ch]:
            who = r["who"] + (f"（{r['name']}）" if r.get("name") and r["who"] == "A" else "")
            text = str(r["text"]).replace("|", "\\|")
            lines.append(f"| {_fmt_ts(r['ts'])} | {who} | {text} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="导出盲判包")
    ap.add_argument("--companions", default=DEFAULT_COMPANIONS)
    ap.add_argument("--lm-db", default=DEFAULT_LM, help="livingmemory 的 conversations.db（私聊记录在这里）")
    ap.add_argument("--source", choices=("auto", "livingmemory", "companions"), default="auto")
    ap.add_argument("--bot-id", default=DEFAULT_BOT_ID)
    ap.add_argument("--since-hours", type=float, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rows: list[dict] = []
    used = ""

    want_lm = args.source in ("auto", "livingmemory")
    if want_lm and os.path.exists(args.lm_db):
        group_names: dict[str, str] = {}
        if os.path.exists(args.companions):
            try:
                data = json.load(open(args.companions, encoding="utf-8-sig"))
                for gid, g in (data.get("groups") or {}).items():
                    if isinstance(g, dict) and g.get("group_name"):
                        group_names[gid] = str(g["group_name"])
            except Exception:
                pass
        rows = collect_from_lm(args.lm_db, args.since_hours, group_names)
        used = "livingmemory"

    if not rows:
        if args.source == "livingmemory":
            print(f"livingmemory 里这段时间没有消息（{args.lm_db}）", file=sys.stderr)
            return 2
        if not os.path.exists(args.companions):
            print(f"找不到 {args.companions}", file=sys.stderr)
            return 2
        try:
            rows = collect(args.companions, args.bot_id, args.since_hours)
        except json.JSONDecodeError as e:
            print(f"companions.json 解析失败: {e}", file=sys.stderr)
            return 2
        used = "companions"

    if not rows:
        print("这段时间没有对话。", file=sys.stderr)
        return 1

    text = render(rows)
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "packet.md")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)

    n_b = sum(1 for r in rows if r["who"] == "B")
    chans = len({r["ch"] for r in rows})
    print(f"来源 {used} | {chans} 个会话 | 已导出 {len(rows)} 行（B 的回复 {n_b} 条）→ {out}")
    print("下一步：把 packet.md 原样丢给判官，让它按 verdicts 格式输出 JSON。")
    print("参考格式见 verdicts.example.json。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
