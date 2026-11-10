# -*- coding: utf-8 -*-
"""「现在卡住的事」——让她知道自己有什么做不动，并且知道可以开口求人。

写进人格第十一节；成长引擎重建第十节时会原样保留这一节。

    python help.py                # 预演
    python help.py --apply        # 写回人格
    python help.py --status       # 看现在卡着什么
    python help.py --clear        # 清空（视为全部解决）

判断依据：她的长期目标 + 最近 48 小时的对话 + 日程。
"""
from __future__ import annotations

import argparse
import difflib
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:6185"
PERSONA_ID = "澄音"
CRED_FILE = r"D:\chengyin\我的信息.txt"
CMD_CONFIG = r"D:\chengyin\astrbot\data\cmd_config.json"
COMPANIONS = r"D:\chengyin\astrbot\data\plugin_data\astrbot_plugin_private_companion\companions.json"
LM_DB = r"D:\chengyin\astrbot\data\plugin_data\astrbot_plugin_livingmemory\conversations.db"
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "help_state.json")
BACKUPS = os.path.join(HERE, "backups")
SECTION = "## 十一、现在卡住的事"
SECTION10 = "## 十、成长履历"
MAX_ITEMS = 2

TOKEN_CACHE = os.path.join(tempfile.gettempdir(), "dsh_astrbot_token.json")


# ---------------------------------------------------------------- 基础

def api(method: str, path: str, payload=None, token: str | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def login() -> str:
    try:
        rec = json.load(open(TOKEN_CACHE, encoding="utf-8"))
        if rec.get("base") == BASE and float(rec.get("exp") or 0) > time.time() + 60:
            return str(rec["token"])
    except Exception:
        pass
    text = open(CRED_FILE, encoding="utf-8-sig").read()
    u = re.search(r"账号[:：]\s*(\S+)", text).group(1)
    p = re.search(r"密码[:：]\s*(\S+)", text).group(1)
    token = api("POST", "/api/auth/login", {"username": u, "password": p})["data"]["token"]
    exp = time.time() + 1800
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        import base64
        exp = float(json.loads(base64.urlsafe_b64decode(payload)).get("exp") or exp)
    except Exception:
        pass
    try:
        json.dump({"base": BASE, "token": token, "exp": exp}, open(TOKEN_CACHE, "w", encoding="utf-8"))
    except Exception:
        pass
    return token


def get_persona(token: str) -> dict:
    return api("GET", "/api/v1/personas/by-id?persona_id=" + urllib.parse.quote(PERSONA_ID), token=token)["data"]


def push_persona(full: str, token: str, snap: dict) -> None:
    body = {"persona_id": PERSONA_ID, "system_prompt": full,
            "begin_dialogs": snap.get("begin_dialogs") or []}
    for k in ("tools", "skills", "custom_error_message"):
        if snap.get(k) is not None:
            body[k] = snap[k]
    api("PUT", "/api/v1/personas/by-id", body, token=token)


def split_out(full: str) -> tuple[str, str]:
    """拆成（不含十一节的部分, 十一节）。没有十一节就返回 (全文, 空)。"""
    idx = full.find(SECTION)
    if idx < 0:
        return full.rstrip(), ""
    return full[:idx].rstrip(), full[idx:].rstrip()


# ---------------------------------------------------------------- 材料

def load_goals() -> list[dict]:
    if not os.path.exists(COMPANIONS):
        return []
    d = json.load(open(COMPANIONS, encoding="utf-8-sig"))
    goals = d.get("personal_goals") or []
    return [g for g in goals if isinstance(g, dict) and g.get("status") == "active"]


def recent_dialogue(hours: float = 48) -> str:
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
    lines = []
    for role, content, ts in rows[-200:]:
        who = "她" if role == "assistant" else "主人"
        text = str(content).replace("\n", " ").strip()[:80]
        lines.append(f"{who}: {text}")
    return "\n".join(lines)


def deepseek(messages: list[dict], max_tokens: int = 700) -> str:
    cfg = json.load(open(CMD_CONFIG, encoding="utf-8-sig"))
    key, base = None, "https://api.deepseek.com/v1"
    for s in cfg.get("provider_sources") or []:
        if isinstance(s, dict) and "deepseek" in str(s.get("api_base", "")):
            raw = s.get("key")
            keys = raw if isinstance(raw, list) else [raw]
            keys = [str(x).strip() for x in keys if str(x or "").strip()]
            if keys:
                key, base = keys[0], str(s.get("api_base") or base)
                break
    if not key:
        raise SystemExit("找不到 DeepSeek key")
    body = json.dumps({"model": "deepseek-chat", "messages": messages,
                       "temperature": 0.3, "max_tokens": max_tokens,
                       "response_format": {"type": "json_object"}}).encode()
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + key)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())["choices"][0]["message"]["content"]


SYS = """你负责判断一个虚拟角色有没有"卡住、自己弄不动、需要人帮"的事。

规则：
1. 只报**真的卡住**的：想做但做不了、试了几次没成、缺材料/缺权限/缺人搭把手。
2. 每条必须写清三件事：want（想干什么，20 字内）、stuck（卡在哪，30 字内）、need（要主人做什么，30 字内）。
   need 里**不要出现"主人"两个字**，也不要以"有空时"开头——模板会自动补主语。
3. **没有就返回空数组。空数组是正常结果**，不要为了交差硬凑。
4. 最多 2 条。「懒」「不想动」「在发呆」不算卡住。
5. 不要输出心理分析，不要评价。

只输出 JSON：{"blocked":[{"want":"","stuck":"","need":"","confidence":0.0}]}"""


def ask_blocked(goals: list[dict], dialogue: str) -> list[dict]:
    goal_text = "\n".join(
        f"- {g.get('title')}（进度 {g.get('progress', 0)}%）下一步：{g.get('next_step')}"
        for g in goals
    ) or "（没有登记的目标）"
    user = (f"【她登记的长期目标】\n{goal_text}\n\n【最近对话】\n{dialogue[-5000:]}\n\n"
            "请判断她现在有没有卡住、需要人帮忙的事。没有就返回空数组。")
    raw = deepseek([{"role": "system", "content": SYS}, {"role": "user", "content": user}])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {"blocked": []}
    items = data.get("blocked") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for it in items[:MAX_ITEMS]:
        if not isinstance(it, dict):
            continue
        want = str(it.get("want") or "").strip()[:40]
        stuck = str(it.get("stuck") or "").strip()[:60]
        need = str(it.get("need") or "").strip()[:60]
        try:
            conf = float(it.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if not (want and stuck and need) or conf < 0.55:
            continue
        out.append({"want": want, "stuck": stuck, "need": need, "confidence": round(conf, 2)})
    return out


# ---------------------------------------------------------------- 写回

def _clean_need(text: str) -> str:
    """模型常把"主人"写进 need 里，模板再套一层就重复了。"""
    s = str(text or "").strip()
    s = re.sub(r"^(主人|主人)\s*", "", s).strip()
    s = re.sub(r"^(有空时|有空|方便时)\s*", "", s).strip()
    return s


def build_section(items: list[dict]) -> str:
    lines = [SECTION, "",
             "这些是你眼下卡住、自己弄不动的事。别憋着——合适的时候主动跟主人说，"
             "说清楚卡在哪、要他帮你做什么。说一次就够，他不追问就别反复念；真解决了就不再提。", ""]
    if not items:
        lines.append("（暂时没有卡住的事）")
    else:
        for it in items:
            lines.append(f"- 想{it['want']}，卡在{it['stuck']}（需要主人：{_clean_need(it['need'])}）")
    return "\n".join(lines)


def load_state() -> dict:
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE, encoding="utf-8"))
        except Exception:
            pass
    return {"version": 1, "items": [], "updated_at": 0}


def save_state(d: dict) -> None:
    tmp = STATE + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)


def carry_since(new_items: list[dict], old_items: list[dict]) -> list[dict]:
    """卡着没解决的事，保留第一次出现的时间。"""
    old = {i.get("want"): i.get("since") for i in old_items if isinstance(i, dict)}
    now = datetime.now().strftime("%Y-%m-%d")
    for it in new_items:
        it["since"] = old.get(it["want"]) or now
    return new_items


def merge_items(old: list[dict], new: list[dict], ratio: float = 0.7) -> list[dict]:
    """新旧合并：措辞变的沿用旧的，没出现的再撑一轮，真新的才加。

    模型每次给的清单会小幅漂移（这次两条、下次一条），直接覆盖会天天改人设。
    """
    merged: list[dict] = []
    used: set[int] = set()
    for prev in old:
        if not isinstance(prev, dict):
            continue
        hit = None
        for idx, item in enumerate(new):
            if idx in used:
                continue
            if difflib.SequenceMatcher(None, str(item.get("want", "")),
                                       str(prev.get("want", ""))).ratio() >= ratio:
                hit = idx
                break
        if hit is not None:
            used.add(hit)
            prev["miss"] = 0
            merged.append(prev)
        else:
            prev["miss"] = int(prev.get("miss") or 0) + 1
            if prev["miss"] < 2:
                merged.append(prev)
    for idx, item in enumerate(new):
        if idx in used:
            continue
        item["miss"] = 0
        merged.append(item)
    return merged[:MAX_ITEMS]


def _same_wants(old: list[str], new: list[str], ratio: float = 0.7) -> bool:
    """模型每次措辞都会变（"歪尾巴的鱼" / "那条歪尾巴的鱼"），模糊比一下。"""
    if len(old) != len(new):
        return False
    used: set[int] = set()
    for want in new:
        hit = None
        for idx, prev in enumerate(old):
            if idx in used:
                continue
            if difflib.SequenceMatcher(None, want, str(prev or "")).ratio() >= ratio:
                hit = idx
                break
        if hit is None:
            return False
        used.add(hit)
    return True


def cmd_status() -> int:
    st = load_state()
    items = st.get("items") or []
    print(f"卡住的事 {len(items)} 条｜上次检查 "
          f"{datetime.fromtimestamp(st['updated_at']).strftime('%m-%d %H:%M') if st.get('updated_at') else '从没跑过'}")
    for i, it in enumerate(items, 1):
        print(f"  {i}. 想{it['want']}，卡在{it['stuck']}")
        print(f"     要主人：{it['need']}（{it.get('since','')} 起）")
    if not items:
        print("  目前没有卡住的事。")
    return 0


def cmd_clear(apply: bool) -> int:
    token = login()
    snap = get_persona(token)
    head, _ = split_out(snap["system_prompt"])
    new_full = head + "\n\n" + build_section([]) + "\n"
    print(f"清空十一节：{len(snap['system_prompt'])} → {len(new_full)} 字")
    if not apply:
        print("[dry-run] 加 --apply 才写")
        return 0
    push_persona(new_full, token, snap)
    save_state({"version": 1, "items": [], "updated_at": time.time()})
    print("已写入")
    return 0


def cmd_run(apply: bool) -> int:
    token = login()
    snap = get_persona(token)
    full = snap["system_prompt"]
    head, old_sec = split_out(full)
    base = head.split(SECTION10)[0].rstrip() if SECTION10 in head else head
    state = load_state()

    goals = load_goals()
    dialogue = recent_dialogue(48)
    print(f"目标 {len(goals)} 个｜材料 {len(dialogue)} 字｜现有卡住 {len(state.get('items') or [])} 条")
    print("问模型中…")
    fresh = ask_blocked(goals, dialogue)
    items = carry_since(merge_items(state.get("items") or [], fresh), state.get("items") or [])

    if not items:
        print("\n模型判断：现在没有卡住的事。")
        if old_sec and "暂时没有卡住的事" not in old_sec:
            print("（人格里还留着旧的卡住条目，加 --apply 会清掉）")
        state.update({"items": [], "updated_at": time.time()})
        if apply:
            save_state(state)
        return 0

    print(f"\n卡住的事 {len(items)} 条：")
    for i, it in enumerate(items, 1):
        print(f"  {i}. 想{it['want']}，卡在{it['stuck']}")
        print(f"     要主人：{it['need']}  [置信 {it['confidence']}]")

    section = build_section(items)
    new_full = head + "\n\n" + section + "\n"
    if not apply:
        print("\n[dry-run] 没写人设。加 --apply 才提交。")
        return 0

    # 卡着的事没变就别重写——模型每次措辞都不一样，天天改人设没意义
    old_wants = [i.get("want") for i in (state.get("items") or []) if isinstance(i, dict)]
    new_wants = [i["want"] for i in items]
    if _same_wants(old_wants, new_wants) and SECTION in full:
        print("\n卡住的事和上次一样，保持原样不重写。")
        state.update({"items": items, "updated_at": time.time()})
        save_state(state)
        return 0

    if new_full.strip() == full.strip():
        print("\n和现在完全一样，不重复写入。")
        state.update({"items": items, "updated_at": time.time()})
        save_state(state)
        return 0

    os.makedirs(BACKUPS, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time()*1000)%1000:03d}"
    json.dump(snap, open(os.path.join(BACKUPS, f"persona_before_help_{ts}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    push_persona(new_full, token, snap)
    state.update({"items": items, "updated_at": time.time()})
    save_state(state)

    chk = get_persona(token)["system_prompt"]
    ok = SECTION in chk and chk.startswith(head[:200])
    print(f"\n已写入：{len(full)} → {len(chk)} 字｜校验 {'通过' if ok else '失败'}")
    if not ok:
        push_persona(full, token, snap)
        print("已回滚")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="现在卡住的事")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--clear", action="store_true")
    args = ap.parse_args()
    try:
        if args.status:
            return cmd_status()
        if args.clear:
            return cmd_clear(args.apply)
        return cmd_run(args.apply)
    except urllib.error.URLError as exc:
        print(f"连不上后台（AstrBot 没在跑？）：{exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
