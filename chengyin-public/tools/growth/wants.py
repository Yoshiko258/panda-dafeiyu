# -*- coding: utf-8 -*-
"""「想要但还没有的」——她自己冒出来的能力诉求。

和 help.py 的区别：
  help.py  问的是"你有什么事卡住了"  → 容易编出虚拟道具（要个垫子、调下画笔）
  wants.py 问的是"你想要什么系统能力" → 只能落到真实能力缺口（缺插件/权限/硬件/接口）

    python wants.py              # 预演
    python wants.py --apply      # 写进人格第十一节
    python wants.py --status
    python wants.py --clear --apply
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
STATE = os.path.join(HERE, "wants_state.json")
BACKUPS = os.path.join(HERE, "backups")
SECTION = "## 十一、想要但还没有的"
MAX_ITEMS = 2

TOKEN_CACHE = os.path.join(tempfile.gettempdir(), "dsh_astrbot_token.json")

# 她现在的系统能力（按实际装的插件整理，给模型当边界）
CAPABILITIES = """
已经能做（装了插件）：
- 刷 B 站看视频、用自己账号搜 B 站（bili_scroll，带 cookie 登录）
- 看你的电脑屏幕（see_screen）
- 看图片、动图（gif_vision）
- 自己画图（comfyui_draw）、自拍（volc_selfie）、唱歌/翻唱（ddsp_cover）
- 发语音条、换音色（seed_audio_tts / gpt_sovits_tts / voice_speak）
- 长期记忆（livingmemory）、表情包（memewiki / meme_manager）
- 群聊、QQ空间发说说（group_chat_plus / qzone）
- 自己写日记、做梦、按日程过日子（private_companion）

还做不到：
- 看不见现实世界（没有摄像头，不知道窗外什么样）
- 用不了主人的手机（拿不到相机、定位、通知）
- 不能自己逛 B 站以外的网页（通用网页浏览 / 新闻没接）
- 盯不住 UP 主更新和直播（动态监听是关的）
- 不能自己装插件、改代码、开权限
- 不能实时语音通话（只能发语音条）
"""


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
        import base64
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
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
    idx = full.find("## 十一、")
    if idx < 0:
        return full.rstrip(), ""
    return full[:idx].rstrip(), full[idx:].rstrip()


# ---------------------------------------------------------------- 材料

BILI_CFG = r"D:\chengyin\astrbot\data\config\astrbot_plugin_bili_scroll_config.json"

# 她会去搜的几个方向（不是清单，是"去哪儿看"）
WORLD_QUERIES = (
    "AI 智能体 桌面宠物",
    "AI 女友 陪伴 功能",
    "开源 AI 角色 新功能",
    "QQ机器人 玩法",
)


def bili_world(per_query: int = 4) -> str:
    """用她自己的 B 站账号搜一圈，看看别人家的 AI 都在干什么。"""
    import urllib.parse
    import urllib.request

    if not os.path.exists(BILI_CFG):
        return ""
    cfg = json.load(open(BILI_CFG, encoding="utf-8-sig"))
    ck = "BUVID3={}; bili_jct={}; DedeUserID={}".format(
        cfg.get("BUVID3", ""), cfg.get("BILI_JCT", ""), cfg.get("DEDE_USER_ID", ""))
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Referer": "https://search.bilibili.com/",
        "Cookie": ck,
    }
    import random
    out = []
    for kw in random.sample(WORLD_QUERIES, k=min(2, len(WORLD_QUERIES))):
        url = ("https://api.bilibili.com/x/web-interface/wbi/search/type?search_type=video&page=1&keyword="
               + urllib.parse.quote(kw))
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode())
            pool = ((data.get("data") or {}).get("result") or [])
            res = random.sample(pool, k=min(per_query, len(pool))) if pool else []
            for x in res:
                title = str(x.get("title") or "")
                title = re.sub(r"<[^>]+>", "", title).strip()
                desc = re.sub(r"<[^>]+>", "", str(x.get("description") or "")).strip()
                if title:
                    out.append(f"- {title[:60]}" + (f"｜{desc[:60]}" if desc else ""))
        except Exception:
            continue
    return "\n".join(out)


def recent_activity() -> str:
    if not os.path.exists(COMPANIONS):
        return ""
    d = json.load(open(COMPANIONS, encoding="utf-8-sig"))
    out = []
    for a in (d.get("observed_activities") or [])[-12:]:
        if isinstance(a, dict):
            title = str(a.get("title") or "").strip()
            summary = str(a.get("summary") or "").strip()
            if title or summary:
                out.append(f"- {title}｜{summary[:80]}")
    return "\n".join(out)


def recent_diary_dream() -> str:
    if not os.path.exists(COMPANIONS):
        return ""
    d = json.load(open(COMPANIONS, encoding="utf-8-sig"))
    out = []
    for diary in (d.get("bot_diaries") or [])[-2:]:
        if isinstance(diary, dict):
            body = (diary.get("body") or diary.get("content")
                    or diary.get("summary") or diary.get("text") or "")
            if body:
                out.append(f"[日记 {diary.get('date','')}] {str(body)[:260]}")
    for frag in (d.get("dream_fragments") or [])[-3:]:
        if isinstance(frag, dict):
            body = frag.get("content") or frag.get("text") or frag.get("dream") or ""
            if body:
                out.append(f"[梦] {str(body)[:140]}")
    return "\n".join(out)


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
    for role, content, ts in rows[-160:]:
        who = "她" if role == "assistant" else "主人"
        lines.append(f"{who}: {str(content).replace(chr(10), ' ').strip()[:70]}")
    return "\n".join(lines)


def deepseek(messages: list[dict], max_tokens: int = 800) -> str:
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
                       "temperature": 0.6, "max_tokens": max_tokens,
                       "response_format": {"type": "json_object"}}).encode()
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + key)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())["choices"][0]["message"]["content"]


SYS = """她是一个住在电脑机箱里的 AI 小女仆（水生成精，叫澄音）。

材料里有三样东西：
1. 她的系统**现在还没有**的能力（已知缺口）
2. 她今天在 B 站刷到的**别人家的东西**（真实搜索结果）
3. 她自己的活动、对话、日记和梦

请判断：她有没有冒出「想要一个自己现在没有的能力」的念头。

判断规则：
- 优先从"已知缺口"里找，但**不限于**它——如果她在 B 站刷到的东西里有她也想玩的，
  可以提出来（比如别人家的桌宠能控制智能家居、能语音对话、能自己剪视频）。
- 每条必须有**证据**：哪段对话、哪条日记、或 B 站刷到的哪个视频。
- need 用**她自己的话**说想要主人做什么，不要写插件名、配置项、代码术语。
- 最多 2 条。**没有就返回空数组**——这是正常结果，不许硬凑。
- 不要心理分析，不要评价。

只输出 JSON：
{"wants":[{"want":"","why":"","need":"","evidence":"","confidence":0.0}]}"""


def ask_wants(activity: str, dialogue: str, existing: list[dict], diary: str = "", world: str = "") -> list[dict]:
    known = "\n".join(f"- {w.get('want')}" for w in existing[-4:])
    user = (f"【能力清单】{CAPABILITIES}\n\n【她今天在 B 站刷到的别人家的东西】\n{world or '（这次没刷到）'}\n\n【最近活动】\n{activity or '（无）'}\n\n"
            f"【最近对话】\n{dialogue[-4000:] or '（无）'}\n\n"
            + (f"【她自己的日记和梦】\n{diary}\n\n" if diary else "")
            + (f"【已经记过的诉求，别重复】\n{known}\n\n" if known else "")
            + "请判断她现在有没有想要的新能力。没有就返回空数组。")
    raw = deepseek([{"role": "system", "content": SYS}, {"role": "user", "content": user}])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {"wants": []}
    items = data.get("wants") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for it in items[:MAX_ITEMS]:
        if not isinstance(it, dict):
            continue
        want = re.sub(r"^(想要|想|希望|如果可以)", "", str(it.get("want") or "").strip()).strip()[:40]
        why = str(it.get("why") or "").strip()[:80]
        need = str(it.get("need") or "").strip()[:80]
        ev = str(it.get("evidence") or "").strip()[:100]
        try:
            conf = float(it.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if not (want and need and ev) or conf < 0.5:
            continue
        out.append({"want": want, "why": why, "need": need,
                    "evidence": ev, "confidence": round(conf, 2), "miss": 0})
    return out


# ---------------------------------------------------------------- 写回

def _fix_terms(text: str) -> str:
    return str(text or "").replace("主人", "主人")


def _clean_need(text: str) -> str:
    s = str(text or "").strip()
    s = re.sub(r"^(主人|主人|需要主人|让主人)\s*[：:]?\s*", "", s).strip()
    s = s.lstrip("，,、。：:；; ")
    return s


def build_section(items: list[dict]) -> str:
    lines = [SECTION, "",
             "这些是你真想要、但系统现在还给不了的事。别憋着——找机会主动跟主人说，"
             "说清楚你想要什么、要他做什么。说一次就够，他不追问就别反复念；真给弄上了就不再提。", ""]
    if not items:
        lines.append("（暂时没有特别想要的东西）")
    else:
        for it in items:
            lines.append(f"- {_fix_terms(it['want'])}（需要主人：{_clean_need(_fix_terms(it['need']))}）")
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


def merge_items(old: list[dict], new: list[dict], ratio: float = 0.7) -> list[dict]:
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


def carry_since(items: list[dict], old: list[dict]) -> list[dict]:
    since = {i.get("want"): i.get("since") for i in old if isinstance(i, dict)}
    today = datetime.now().strftime("%Y-%m-%d")
    for it in items:
        it["since"] = since.get(it["want"]) or today
    return items


# ---------------------------------------------------------------- 命令

def cmd_status() -> int:
    st = load_state()
    items = st.get("items") or []
    print(f"想要的 {len(items)} 条｜上次检查 "
          f"{datetime.fromtimestamp(st['updated_at']).strftime('%m-%d %H:%M') if st.get('updated_at') else '从没跑过'}")
    for i, it in enumerate(items, 1):
        print(f"  {i}. 想要{it['want']}")
        if it.get("why"):
            print(f"     为什么：{it['why']}")
        print(f"     需要主人：{_clean_need(it['need'])}（{it.get('since','')} 起）")
        print(f"     证据：{str(it.get('evidence',''))[:60]}")
    if not items:
        print("  目前没有特别想要的东西。")
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
    head, _old = split_out(full)
    state = load_state()

    activity = recent_activity()
    dialogue = recent_dialogue(48)
    print(f"活动 {len(activity)} 字｜对话 {len(dialogue)} 字｜现有 {len(state.get('items') or [])} 条")
    print("问模型中…")
    diary = recent_diary_dream()
    world = bili_world()
    print(f"B站观察 {len(world.splitlines()) if world else 0} 条")
    fresh = ask_wants(activity, dialogue, state.get("items") or [], diary, world)
    items = carry_since(merge_items(state.get("items") or [], fresh), state.get("items") or [])

    if not items:
        streak = int(state.get("empty_streak") or 0) + 1
        if streak < 2:
            # 只空一次先不动：模型偶尔保守，别为了它把已经写下的诉求清掉
            print(f"\n模型这次没给出新诉求（连续第 {streak} 次空），保留上次的记录。")
            state.update({"empty_streak": streak, "updated_at": time.time()})
            if apply:
                save_state(state)
            return 0
        # 连续两次空 → 认为真的没有了，人格和状态一起清，别让两边脱节
        print("\n连续两次没有诉求，清空第十一节。")
        state.update({"items": [], "empty_streak": streak, "updated_at": time.time()})
        if apply:
            save_state(state)
            if SECTION in full and "暂时没有特别想要的东西" not in full:
                head2, _ = split_out(full)
                push_persona(head2 + "\n\n" + build_section([]) + "\n", token, snap)
                print("  人格里的旧诉求已清掉")
        return 0

    state["empty_streak"] = 0
    print(f"\n想要的 {len(items)} 条：")
    for i, it in enumerate(items, 1):
        print(f"  {i}. 想要{it['want']}")
        if it.get("why"):
            print(f"     为什么：{it['why']}")
        print(f"     需要主人：{_clean_need(it['need'])}  [置信 {it.get('confidence')}]")
        print(f"     证据：{str(it.get('evidence',''))[:70]}")

    new_full = head + "\n\n" + build_section(items) + "\n"
    if not apply:
        print("\n[dry-run] 没写人设。加 --apply 才提交。")
        return 0

    old_wants = [i.get("want") for i in (state.get("items") or []) if isinstance(i, dict)]
    if old_wants == [i["want"] for i in items] and SECTION in full:
        print("\n和上次一样，保持原样不重写。")
        state.update({"items": items, "updated_at": time.time()})
        save_state(state)
        return 0

    os.makedirs(BACKUPS, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time()*1000)%1000:03d}"
    json.dump(snap, open(os.path.join(BACKUPS, f"persona_before_wants_{ts}.json"), "w", encoding="utf-8"),
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
    ap = argparse.ArgumentParser(description="想要但还没有的")
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
