# -*- coding: utf-8 -*-
"""澄音的自动成长引擎。

每天跑一次：读最近的材料 → 让模型判断"她有没有真的变" → 有变化才写进人设第十节。

    python growth.py                  # dry-run：生成候选，打印，不写任何人设
    python growth.py --apply          # 采纳并写入人格（会先备份）
    python growth.py --status         # 看当前成长履历
    python growth.py --rollback       # 退回上一次改动
    python growth.py --hours 72       # 看更长的材料窗口

设计原则（抄自 AI-Buddy 的 R30，也抄自我们踩过的坑）：
  * 允许"这次没有变化"——空数组是正常结果，不许硬凑
  * 每条必须有原文证据，不能从人设里推断
  * 写回的是第十节，不动一到九节；崩了 --rollback 或直接重贴原始人设
  * 成长履历最多保留 12 条进 prompt，老的留在 growth.json 里但不占 token
"""
from __future__ import annotations

import argparse
import copy
import difflib
import base64
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # 被别的程序 import 时 stdout 可能不是 TextIO，忽略即可

BASE = "http://127.0.0.1:6185"
PERSONA_ID = "澄音"
CRED_FILE = r"D:\chengyin\我的信息.txt"
CMD_CONFIG = r"D:\chengyin\astrbot\data\cmd_config.json"
COMPANIONS = r"D:\chengyin\astrbot\data\plugin_data\astrbot_plugin_private_companion\companions.json"
LM_DB = r"D:\chengyin\astrbot\data\plugin_data\astrbot_plugin_livingmemory\conversations.db"
HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "growth.json")
BACKUPS = os.path.join(HERE, "backups")
SECTION = "## 十、成长履历"
TAIL_MARKER = "## 十一、"
MAX_IN_PROMPT = 12

# 历史上改过的称呼/说法，重建第十节时统一刷成现在的写法。
# 起因：老快照里存的是"给主人念语音"，回滚会把它带回来。
TERM_FIXES = (("主人", "主人"),)


def _fix_terms(text: str) -> str:
    for old, new in TERM_FIXES:
        text = text.replace(old, new)
    return text

# ---------------------------------------------------------------- 基础设施


def credentials() -> tuple[str, str]:
    user = os.environ.get("DSH_DASH_USER")
    pwd = os.environ.get("DSH_DASH_PASS")
    if user and pwd:
        return user, pwd
    text = open(CRED_FILE, encoding="utf-8-sig").read()
    u = re.search(r"账号[:：]\s*(\S+)", text)
    p = re.search(r"密码[:：]\s*(\S+)", text)
    if not u or not p:
        raise SystemExit(f"读不到后台账号密码：确认 {CRED_FILE} 有「账号：」「密码：」")
    return u.group(1), p.group(1)


def api(method: str, path: str, payload=None, token: str | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


TOKEN_CACHE = os.path.join(tempfile.gettempdir(), "dsh_astrbot_token.json")


def _cached_token() -> str | None:
    """复用未过期的令牌。后台限流 1 次/秒、突发 3 次，天天登录会撞 429。"""
    try:
        rec = json.load(open(TOKEN_CACHE, encoding="utf-8"))
        if rec.get("base") == BASE and float(rec.get("exp") or 0) > time.time() + 60:
            return str(rec["token"])
    except Exception:
        pass
    return None


def _save_token(token: str) -> None:
    exp = time.time() + 1800
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = float(json.loads(base64.urlsafe_b64decode(payload)).get("exp") or exp)
    except Exception:
        pass
    try:
        json.dump({"base": BASE, "token": token, "exp": exp},
                  open(TOKEN_CACHE, "w", encoding="utf-8"))
    except Exception:
        pass


def _login_once() -> str:
    text = open(CRED_FILE, encoding="utf-8-sig").read()
    u = re.search(r"账号[:：]\s*(\S+)", text).group(1)
    p = re.search(r"密码[:：]\s*(\S+)", text).group(1)
    return api("POST", "/api/auth/login", {"username": u, "password": p})["data"]["token"]


def login() -> str:
    cached = _cached_token()
    if cached:
        return cached
    try:
        token = _login_once()
    except urllib.error.HTTPError as exc:
        if exc.code != 429:
            raise
        time.sleep(2.5)
        token = _login_once()
    _save_token(token)
    return token



def get_persona(token: str) -> dict:
    return api("GET", "/api/v1/personas/by-id?persona_id=" + urllib.parse.quote(PERSONA_ID), token=token)["data"]


def deepseek_key() -> tuple[str, str]:
    """从 AstrBot 的 provider_sources 里取 key。不打印、不落盘。

    注意：key 字段是**列表**（支持多把），这里取第一把。
    """
    cfg = json.load(open(CMD_CONFIG, encoding="utf-8-sig"))
    for s in cfg.get("provider_sources") or []:
        if not isinstance(s, dict):
            continue
        if "deepseek" not in str(s.get("api_base", "")):
            continue
        raw = s.get("key")
        if isinstance(raw, list):
            keys = [str(x).strip() for x in raw if str(x).strip()]
        else:
            keys = [str(raw).strip()] if raw else []
        if keys:
            return keys[0], str(s.get("api_base") or "https://api.deepseek.com/v1")
    raise SystemExit("找不到 DeepSeek 的 key（cmd_config.json → provider_sources）")


def chat(messages: list[dict], *, temperature: float = 0.3, max_tokens: int = 900) -> str:
    key, base = deepseek_key()
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + key)
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode())
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------- 材料收集


def split_persona(full: str) -> tuple[str, str]:
    """把人格拆成（基础部分, 第十节）。第十节是我们自己拼的，每次重拼。

    注意：第十节后面可能还有十一节（卡住的事），要原样保留，
    不然每次成长都会把后面那节吃掉。
    """
    idx = full.find(SECTION)
    if idx < 0:
        return full.rstrip(), ""
    return full[:idx].rstrip(), full[idx:].rstrip()


def split_with_tail(full: str) -> tuple[str, str, str]:
    """拆成（基础, 第十节, 后面的尾巴）。尾巴原样带回，不动。"""
    idx = full.find(SECTION)
    if idx < 0:
        return full.rstrip(), "", ""
    tail_at = full.find(TAIL_MARKER, idx + len(SECTION))
    if tail_at < 0:
        return full[:idx].rstrip(), full[idx:].rstrip(), ""
    return full[:idx].rstrip(), full[idx:tail_at].rstrip(), full[tail_at:].rstrip()


def compose(base: str, entries: list[dict], tail: str) -> str:
    parts = [base]
    if entries:
        parts.append(build_section(entries))
    if tail:
        parts.append(tail)
    return "\n\n".join(p for p in parts if p).rstrip() + "\n"


def load_store() -> dict:
    if os.path.exists(STORE):
        try:
            d = json.load(open(STORE, encoding="utf-8"))
            d.setdefault("entries", [])
            return d
        except Exception:
            pass
    return {"version": 1, "entries": [], "last_run": 0}


def save_store(d: dict) -> None:
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STORE)


def recent_dialogue(hours: float) -> str:
    """最近一段时间的私聊+群聊，拼成"谁: 什么"的行。"""
    if not os.path.exists(LM_DB):
        return ""
    cutoff = time.time() - hours * 3600
    con = sqlite3.connect(f"file:{LM_DB}?mode=ro", uri=True, timeout=10)
    try:
        rows = con.execute(
            "select role, content, timestamp from messages where timestamp >= ? order by timestamp asc",
            (cutoff,),
        ).fetchall()
    finally:
        con.close()
    lines, last_day = [], None
    for role, content, ts in rows[-260:]:
        t = datetime.fromtimestamp(ts)
        if t.date() != last_day:
            lines.append(f"\n[{t:%m-%d}]")
            last_day = t.date()
        who = "她" if role == "assistant" else "主人"
        text = str(content).replace("\n", " ").strip()
        if len(text) > 90:
            text = text[:90] + "…"
        lines.append(f"{who}: {text}")
    return "\n".join(lines)


def recent_diaries() -> str:
    if not os.path.exists(COMPANIONS):
        return ""
    d = json.load(open(COMPANIONS, encoding="utf-8-sig"))
    out = []
    for diary in (d.get("bot_diaries") or [])[-2:]:
        if isinstance(diary, dict):
            body = diary.get("content") or diary.get("text") or diary.get("diary") or ""
            if body:
                out.append(f"[日记 {diary.get('date','')}] {str(body)[:300]}")
    for frag in (d.get("dream_fragments") or [])[-3:]:
        if isinstance(frag, dict):
            body = frag.get("content") or frag.get("text") or frag.get("dream") or ""
            if body:
                out.append(f"[梦] {str(body)[:160]}")
    return "\n".join(out)


# ---------------------------------------------------------------- 成长判断

SYS_PROMPT = """你是一个"成长编辑"，负责判断一个虚拟角色最近有没有**真的发生变化**。

规则的底线：
1. 只记录真正发生的变化：新喜欢/讨厌的东西、形成的习惯、改掉的小毛病、和某人关系的变化、
   说过并真的做到的事。日常重复的寒暄、当下情绪、一次性事件都不算。
2. 每条必须附**原文证据**——从给你的材料里摘一句话，不能从人设推断，不能编。
3. **如果这一段时间什么都没变，必须返回空数组。空数组是正常且常见的结果，不许为了交差硬凑。**
4. 最多 3 条。每条 insight 一句话，30 字以内；用第三人称写她。
5. 不要心理分析，不要建议，不要评价她"像个真人"之类。

只输出 JSON：
{"growth": [{"insight": "...", "evidence": "...", "confidence": 0.0, "risk": "low"}]}
risk 只能是 low / medium / high。"""


def ask_growth(base_persona: str, material: str, existing: list[dict] | None = None) -> list[dict]:
    known = "\n".join(f"- {e['insight']}" for e in (existing or [])[-MAX_IN_PROMPT:])
    user_msg = (
        f"【角色当前人设（节选）】\n{base_persona[:1200]}\n\n"
        f"【最近的材料】\n{material[:6000]}\n\n"
        + (f"【已经记录过的成长，不要重复，也不要换个说法重说】\n{known}\n\n" if known else "")
        + "请判断这段时间她有没有**新的**变化。没有就返回空数组。"
    )
    raw = chat([{"role": "system", "content": SYS_PROMPT},
                {"role": "user", "content": user_msg}])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {"growth": []}
    items = data.get("growth") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        insight = str(it.get("insight") or "").strip()
        evidence = str(it.get("evidence") or "").strip()
        try:
            conf = float(it.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        risk = str(it.get("risk") or "low").lower()
        if not insight or not evidence:
            continue
        if conf < 0.6 or risk == "high":
            continue
        out.append({"insight": insight[:60], "evidence": evidence[:120],
                    "confidence": round(conf, 2), "risk": risk})
    return out[:3]


# ---------------------------------------------------------------- 写回人格


def _too_similar(insight: str, others: list[dict], ratio: float = 0.5) -> bool:
    """换汤不换药的重说，也要挡掉。"""
    for o in others:
        if difflib.SequenceMatcher(None, insight, o.get("insight", "")).ratio() >= ratio:
            return True
        if insight and o.get("evidence") and insight in o["evidence"]:
            return True
    return False


def build_section(entries: list[dict]) -> str:
    recent = entries[-MAX_IN_PROMPT:]
    lines = [SECTION, "",
             "这些是你后来自己慢慢长出来的，不是最开始就写好的设定。不用刻意提，但别人问起别否认。", ""]
    for e in recent:
        day = str(e.get("date") or "")[5:]
        lines.append(f"- {_fix_terms(str(e['insight']))}（{day}）")
    return "\n".join(lines)


def backup(payload: dict, store: dict) -> str:
    os.makedirs(BACKUPS, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time()*1000)%1000:03d}"
    path = os.path.join(BACKUPS, f"snapshot_{ts}.json")
    json.dump({"persona": payload, "store": store, "at": ts},
              open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return path


def push_persona(full_text: str, token: str, snap: dict) -> None:
    body = {"persona_id": PERSONA_ID, "system_prompt": full_text,
            "begin_dialogs": snap.get("begin_dialogs") or []}
    for k in ("tools", "skills", "custom_error_message"):
        if snap.get(k) is not None:
            body[k] = snap[k]
    api("PUT", "/api/v1/personas/by-id", body, token=token)


# ---------------------------------------------------------------- 命令


def cmd_status() -> int:
    store = load_store()
    entries = store.get("entries") or []
    token = login()
    full = get_persona(token)["system_prompt"]
    base, section = split_persona(full)
    print(f"人格总长 {len(full)} 字｜基础 {len(base)} 字｜第十节 {len(section)} 字")
    print(f"成长条目 {len(entries)} 条｜上次运行 "
          f"{datetime.fromtimestamp(store['last_run']).strftime('%m-%d %H:%M') if store.get('last_run') else '从没跑过'}")
    print()
    if not entries:
        print("还没有任何成长记录。")
        return 0
    for i, e in enumerate(entries, 1):
        print(f"{i:2d}. [{str(e.get('date',''))}] {e['insight']}")
        print(f"     证据：{e.get('evidence','')[:70]}")
    return 0


def cmd_rollback() -> int:
    """只回滚第十节，不碰一到九节。

    旧做法是整份人格还原成快照——那会把快照之后所有无关改动一起吃掉
    （比如改称呼、改锚点）。现在改成：拿当前人格的基础部分，套上快照里的成长条目。
    """
    if not os.path.isdir(BACKUPS):
        print("没有备份目录", file=sys.stderr)
        return 2
    snaps = sorted(f for f in os.listdir(BACKUPS) if f.startswith("snapshot_"))
    if not snaps:
        print("没有可用备份", file=sys.stderr)
        return 2
    path = os.path.join(BACKUPS, snaps[-1])
    snap = json.load(open(path, encoding="utf-8"))
    old_entries = snap["store"].get("entries") or []

    token = login()
    cur = get_persona(token)
    base, _sec, tail = split_with_tail(cur["system_prompt"])
    new_full = compose(base, old_entries, tail)
    push_persona(new_full, token, cur)
    save_store(snap["store"])
    print(f"已回滚到 {snap['at']}（只回滚成长记录，其他改动保留）")
    print(f"  成长条目 {len(old_entries)} 条｜人格 {len(cur['system_prompt'])} → {len(new_full)} 字")
    return 0


def cmd_run(apply: bool, hours: float) -> int:
    token = login()
    snap = get_persona(token)
    full = snap["system_prompt"]
    base, _old_section, tail = split_with_tail(full)
    store = load_store()
    entries = store.get("entries") or []

    material = recent_dialogue(hours)
    diaries = recent_diaries()
    if diaries:
        material = f"{material}\n\n【她的日记和梦】\n{diaries}"
    if not material.strip():
        print("最近没有材料，跳过。", file=sys.stderr)
        return 1

    print(f"材料 {len(material)} 字（最近 {hours:g} 小时）｜现有成长 {len(entries)} 条")
    print("问模型中…")
    new = ask_growth(base, material, entries)

    # 挡掉跟已有条目重复的（模型偶尔还是会把旧事换个说法再报一次）
    kept = []
    for it in new:
        if _too_similar(it["insight"], entries + kept):
            print(f"  跳过重复：{it['insight']}")
            continue
        kept.append(it)
    new = kept

    if not new:
        print("\n模型判断：这段时间没有值得记的变化。")
        print("（空结果是正常的，不写人设）")
        store["last_run"] = time.time()
        save_store(store)
        return 0

    print(f"\n候选 {len(new)} 条：")
    day = datetime.now().strftime("%Y-%m-%d")
    for i, it in enumerate(new, 1):
        print(f"  {i}. {it['insight']}  [置信 {it['confidence']} / 风险 {it['risk']}]")
        print(f"     证据：{it['evidence'][:80]}")
        it["date"] = day

    if not apply:
        print("\n[dry-run] 没写人设。加 --apply 才提交。")
        return 0

    merged = entries + new
    new_full = compose(base, merged, tail)
    bak = backup(snap, store)
    print(f"\n已备份 → {os.path.basename(bak)}")

    push_persona(new_full, token, snap)
    chk = get_persona(token)["system_prompt"]
    if SECTION not in chk or not chk.startswith(base[:200]):
        print("!! 回读校验失败，尝试自动回滚", file=sys.stderr)
        push_persona(full, token, snap)
        return 1

    store["entries"] = merged
    store["last_run"] = time.time()
    save_store(store)
    print(f"已写入：人格 {len(full)} → {len(chk)} 字，成长条目 {len(entries)} → {len(merged)}")
    print("回读校验通过。回滚：python growth.py --rollback")
    return 0


def cmd_dedupe(apply: bool) -> int:
    """清掉历史里"换汤不换药"的重复条目，并按剩下的重拼第十节。"""
    store = load_store()
    entries = store.get("entries") or []
    kept: list[dict] = []
    for e in entries:
        if _too_similar(str(e.get("insight", "")), kept):
            print(f"  剔除：{e.get('insight')}")
            continue
        kept.append(e)
    print(f"{len(entries)} 条 → {len(kept)} 条")
    if not apply:
        print("[dry-run] 加 --apply 才写回")
        return 0

    token = login()
    snap = get_persona(token)
    base, _sec, tail = split_with_tail(snap["system_prompt"])
    new_full = compose(base, kept, tail)
    backup(snap, store)
    push_persona(new_full, token, snap)
    store["entries"] = kept
    save_store(store)
    chk = get_persona(token)["system_prompt"]
    print(f"已写回：{len(snap['system_prompt'])} → {len(chk)} 字")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="澄音自动成长")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--dedupe", action="store_true")
    ap.add_argument("--hours", type=float, default=24)
    args = ap.parse_args()
    try:
        if args.status:
            return cmd_status()
        if args.rollback:
            return cmd_rollback()
        if args.dedupe:
            return cmd_dedupe(args.apply)
        return cmd_run(args.apply, args.hours)
    except urllib.error.URLError as exc:
        print(f"连不上后台（AstrBot 没在跑？）：{exc}", file=sys.stderr)
        return 3
    except TimeoutError:
        print("后台超时，这次跳过。", file=sys.stderr)
        return 3
    except json.JSONDecodeError as exc:
        print(f"接口返回的不是 JSON：{exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
