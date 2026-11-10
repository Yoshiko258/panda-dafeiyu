# -*- coding: utf-8 -*-
"""交接包：从 companions.json 里提炼三样 persona-engine 强调、澄音目前没有的东西。

    情绪余温 emotional_residue  —— 还没消化完的情绪，下次带进来
    未说出口 unsaid             —— 答应过/延宕过但没给的话
    已掉线头 dropped_threads    —— 用户问了、她没接的，下次禁止回收

产物：
    handoff.json          结构化结果
    直接打印一段可粘贴进 persona_conversation_voice_prompt 的文本块

只读，不改任何文件（除非 --write）。

用法：
    python handoff.py
    python handoff.py --hours 24 --user 1000000001 --write
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # 被别的程序 import 时 stdout 可能不是 TextIO，忽略即可

DEFAULT_COMPANIONS = r"D:\chengyin\astrbot\data\plugin_data\astrbot_plugin_private_companion\companions.json"
DEFAULT_BOT_ID = "1234567890"

# 延宕词：说了这些等于"我欠你一句话"
DEFER = re.compile(r"回头说|改天|下次|等会儿说|一会儿说|待会儿|等会|先不说|等下再|晚点说|明儿说")
# 结束感：这些出现说明这条线收住了
CLOSE = re.compile(r"晚安|拜拜|睡了|先这样|就这样|不说了")
QUESTION = re.compile(r"[？?]|吗[呀啊呢]?$|怎么|为什么|啥|多少|几[点个]")


def _ts(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _fmt(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else "?"


def load(path: str) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def timeline(data: dict, bot_id: str, hours: float) -> dict[str, list[dict]]:
    """按会话把 A/B 消息排成时间线。"""
    cutoff = time.time() - hours * 3600
    chans: dict[str, list[dict]] = {}

    for gid, g in (data.get("groups") or {}).items():
        if not isinstance(g, dict):
            continue
        ch = f"群 {g.get('group_name') or gid}"
        rows: list[dict] = []
        for m in g.get("recent_messages") or []:
            if not isinstance(m, dict):
                continue
            ts, text = _ts(m.get("ts")), m.get("text")
            if isinstance(text, str) and text.strip() and ts >= cutoff:
                rows.append({"ts": ts, "who": "B" if str(m.get("sender_id")) == bot_id else "A", "text": text.strip()})
        for m in g.get("recent_bot_replies") or []:
            if not isinstance(m, dict):
                continue
            ts, text = _ts(m.get("ts")), m.get("text")
            if isinstance(text, str) and text.strip() and ts >= cutoff:
                rows.append({"ts": ts, "who": "B", "text": text.strip()})
        rows.sort(key=lambda r: r["ts"])
        if rows:
            chans[ch] = rows

    for uid, u in (data.get("users") or {}).items():
        if not isinstance(u, dict):
            continue
        ch = f"私聊 {uid}"
        rows = []
        for key, who in (("last_user_message", "A"), ("last_companion_message", "B")):
            v = u.get(key)
            if isinstance(v, dict):
                v = v.get("text")
            ts = _ts(u.get(f"{key}_at"))
            if isinstance(v, str) and v.strip() and ts >= cutoff:
                rows.append({"ts": ts, "who": who, "text": v.strip()})
        rows.sort(key=lambda r: r["ts"])
        if rows:
            chans[ch] = rows

    return chans


def _substantive(text: str) -> bool:
    """去掉标点/省略号后还剩至少 2 个字，才算真的回了话。"""
    return len(re.sub(r"[\s…。，、！？!?.~～]", "", str(text or ""))) >= 2


def dropped(rows: list[dict], wait_minutes: int = 20) -> list[dict]:
    """A 问了、20 分钟内没有 B 有效接话 → 掉线头。只回一串省略号不算接。"""
    out = []
    for i, r in enumerate(rows):
        if r["who"] != "A" or not QUESTION.search(r["text"]):
            continue
        replied = any(
            x["who"] == "B"
            and x["ts"] <= r["ts"] + wait_minutes * 60
            and _substantive(x["text"])
            for x in rows[i + 1:]
        )
        if not replied:
            out.append(r)
    return out


def collect(path: str, bot_id: str, hours: float) -> dict:
    data = load(path)
    chans = timeline(data, bot_id, hours)

    residue: list[dict] = []
    unsaid: list[dict] = []
    drops: list[dict] = []

    for ch, rows in chans.items():
        for r in rows:
            if r["who"] == "B" and DEFER.search(r["text"]):
                unsaid.append({"chan": ch, "ts": r["ts"], "text": r["text"]})
        drops += [{"chan": ch, "ts": r["ts"], "text": r["text"]} for r in dropped(rows)]

    # 同一句话在多处出现只留最近一条，免得 prompt 里重复念
    uniq: dict[str, dict] = {}
    for u in unsaid:
        if u["text"] not in uniq or u["ts"] > uniq[u["text"]]["ts"]:
            uniq[u["text"]] = u
    unsaid = sorted(uniq.values(), key=lambda x: x["ts"])

    # 情绪余温：最近 24h 的情绪事件 + 当日状态
    for uid, u in (data.get("users") or {}).items():
        if not isinstance(u, dict):
            continue
        for e in (u.get("emotion_event_ledger") or [])[-5:]:
            if not isinstance(e, dict):
                continue
            at = e.get("occurred_at") or ""
            try:
                when = datetime.fromisoformat(at).timestamp()
            except Exception:
                # 没有可解析的时间戳就没法判断新旧，宁可不用，也不要捞出半年前的旧账
                continue
            if when < time.time() - 86400:
                continue
            residue.append({
                "who": uid,
                "event": e.get("event_type"),
                "intensity": e.get("intensity"),
                "at": at,
            })

    daily = data.get("daily_state") or {}
    mood = {
        "mood_bias": daily.get("mood_bias"),
        "energy": daily.get("energy"),
        "sleep": daily.get("sleep"),
    }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window_hours": hours,
        "channels": {ch: len(rows) for ch, rows in chans.items()},
        "emotional_residue": {"events": residue, "today": mood},
        "unsaid": unsaid[-10:],
        "dropped_threads": [{"chan": d["chan"], "at": _fmt(d["ts"]), "text": d["text"]} for d in drops[-10:]],
    }


def _clip(text: str, n: int) -> str:
    """截断并去掉结尾标点，免得拼出「吗？。」这种双标点。"""
    t = str(text or "").strip()[:n]
    return t.rstrip("。，、！？!?.…~～ ")


def prompt_block(h: dict) -> str:
    """压成一段能直接进 prompt 的短文本。"""
    parts: list[str] = []

    ev = h["emotional_residue"]["events"]
    today = h["emotional_residue"]["today"]
    bits = []
    if today.get("mood_bias"):
        bits.append(f"今天底色偏{today['mood_bias']}")
    if today.get("energy") is not None:
        bits.append(f"能量{today['energy']}")
    for e in ev:
        if e.get("event") in {"boundary", "conflict", "reject"}:
            bits.append(f"上一轮有过{e['event']}，还没散")
    if bits:
        parts.append("情绪余温：" + "，".join(bits) + "。")

    if h["unsaid"]:
        samples = "；".join(_clip(x["text"], 18) for x in h["unsaid"][-2:])
        parts.append(f"你欠着没说完的话（自然时机再接，别硬提）：{samples}。")

    if h["dropped_threads"]:
        samples = "；".join(_clip(x["text"], 16) for x in h["dropped_threads"][-2:])
        parts.append(f"已经掉线的（对方再提也别主动捡回来）：{samples}。")

    if not parts:
        return "（这一段没有可交接的东西：没欠话、没掉线头、情绪平稳。空着就是对的，不要硬编。）"
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成交接包")
    ap.add_argument("--companions", default=DEFAULT_COMPANIONS)
    ap.add_argument("--bot-id", default=DEFAULT_BOT_ID)
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--write", action="store_true", help="写 handoff.json")
    args = ap.parse_args()

    if not os.path.exists(args.companions):
        print(f"找不到 {args.companions}", file=sys.stderr)
        return 2

    try:
        h = collect(args.companions, args.bot_id, args.hours)
    except json.JSONDecodeError as e:
        print(f"companions.json 解析失败: {e}", file=sys.stderr)
        return 2

    print("=" * 62)
    print(f"交接包   窗口 {args.hours:g}h   会话 {len(h['channels'])} 个")
    print("=" * 62)
    print(json.dumps(h["channels"], ensure_ascii=False))
    print()
    print(f"情绪余温事件 {len(h['emotional_residue']['events'])} 条 | "
          f"欠着的话 {len(h['unsaid'])} 条 | 掉线头 {len(h['dropped_threads'])} 条")
    print()

    if h["unsaid"]:
        print("— 欠着的话 —")
        for x in h["unsaid"][-5:]:
            print(f"  [{_fmt(x['ts'])}] {x['text']}")
        print()
    if h["dropped_threads"]:
        print("— 掉线头（对方问了她没接）—")
        for x in h["dropped_threads"][-5:]:
            print(f"  [{x['at']}] {x['text']}")
        print()

    block = prompt_block(h)
    print("— 可直接粘进 persona_conversation_voice_prompt 的文本 —")
    print("-" * 62)
    print(block)
    print("-" * 62)

    if args.write:
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "handoff.json")
        h["prompt_block"] = block
        json.dump(h, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"已写入 {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
