# -*- coding: utf-8 -*-
"""澄音控制面板 —— 本地只读看板。

    python server.py            # 起在 http://127.0.0.1:8899
    python server.py --port 9000

只读：不写人格、不改配置、不给机器人发消息。
唯一会"动手"的是体检按钮，它跑的是 healthcheck.py（纯读）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = r"D:\chengyin"
PY = os.path.join(ROOT, r"runtime\python\python.exe")
PLUGINS = os.path.join(ROOT, r"astrbot\data\plugins")
DATA = os.path.join(ROOT, r"astrbot\data\plugin_data\astrbot_plugin_private_companion")
COMPANIONS = os.path.join(DATA, "companions.json")
LM_DB = os.path.join(ROOT, r"astrbot\data\plugin_data\astrbot_plugin_livingmemory\conversations.db")
PLUGIN_CFG = os.path.join(ROOT, r"astrbot\data\config\astrbot_plugin_private_companion_config.json")
BILI_CFG = os.path.join(ROOT, r"astrbot\data\config\astrbot_plugin_bili_scroll_config.json")
GROWTH = os.path.join(ROOT, r"tools\growth\growth.json")
WANTS = os.path.join(ROOT, r"tools\growth\wants_state.json")
HEALTH = os.path.join(ROOT, r"tools\growth\healthcheck.py")
BASE = "http://127.0.0.1:6185"
CRED = os.path.join(ROOT, "我的信息.txt")

_cache: dict = {}


# ---------------------------------------------------------------- 采集

def _cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def login_token() -> str | None:
    cache = os.path.join(tempfile.gettempdir(), "dsh_astrbot_token.json")
    try:
        rec = json.load(open(cache, encoding="utf-8"))
        if rec.get("base") == BASE and float(rec.get("exp") or 0) > time.time() + 60:
            return str(rec["token"])
    except Exception:
        pass
    try:
        text = open(CRED, encoding="utf-8-sig").read()
        u = re.search(r"账号[:：]\s*(\S+)", text).group(1)
        p = re.search(r"密码[:：]\s*(\S+)", text).group(1)
        req = urllib.request.Request(BASE + "/api/auth/login",
                                     data=json.dumps({"username": u, "password": p}).encode(),
                                     method="POST")
        req.add_header("Content-Type", "application/json")
        token = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())["data"]["token"]
        try:
            import base64
            payload = token.split(".")[1] + "=="
            exp = float(json.loads(base64.urlsafe_b64decode(payload)).get("exp") or time.time() + 1800)
        except Exception:
            exp = time.time() + 1800
        json.dump({"base": BASE, "token": token, "exp": exp}, open(cache, "w", encoding="utf-8"))
        return token
    except Exception:
        return None


def persona_text() -> str:
    token = login_token()
    if not token:
        return ""
    req = urllib.request.Request(
        BASE + "/api/v1/personas/by-id?persona_id=" + urllib.parse.quote("澄音"))
    req.add_header("Authorization", "Bearer " + token)
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())["data"]["system_prompt"]


def bullets(section: str) -> list[str]:
    return [l.lstrip("- ").strip() for l in section.splitlines() if l.startswith("- ")]


def load_json(path: str, default=None):
    try:
        return json.load(open(path, encoding="utf-8-sig"))
    except Exception:
        return default if default is not None else {}


def build_state() -> dict:
    sp = persona_text()
    companions = load_json(COMPANIONS, {})
    cfg = load_json(PLUGIN_CFG, {})

    sec10 = sp[sp.index("## 十、"):sp.index("## 十一、")] if "## 十一、" in sp and "## 十、" in sp else ""
    sec11 = sp[sp.index("## 十一、"):] if "## 十一、" in sp else ""

    growth = load_json(GROWTH, {})
    wants = load_json(WANTS, {})

    skills = []
    raw_skills = ((companions.get("skill_growth") or {}).get("skills") or {})
    for v in raw_skills.values():
        if isinstance(v, dict):
            skills.append({"name": v.get("name"), "level": v.get("level"),
                           "title": v.get("level_title"), "exp": v.get("exp"),
                           "category": v.get("category")})
    skills.sort(key=lambda x: (-(x.get("level") or 0), -(x.get("exp") or 0)))

    members = companions.get("worldbook_member_profiles") or {}
    groups = companions.get("worldbook_group_profiles") or {}
    goals = [g for g in (companions.get("personal_goals") or []) if isinstance(g, dict)]

    ds = companions.get("daily_state") or {}
    diaries = len(companions.get("bot_diaries") or [])
    dreams = len(companions.get("dream_fragments") or [])
    episodes = len(companions.get("daily_review_reports") or [])

    msgs = 0
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{LM_DB}?mode=ro", uri=True, timeout=5)
        msgs = con.execute("select count(*) from messages").fetchone()[0]
        con.close()
    except Exception:
        pass

    watch = load_json(os.path.join(ROOT, r"astrbot\data\plugin_data\astrbot_plugin_bili_scroll\watch_log.json"), [])
    if isinstance(watch, dict):
        watch = list(watch.values())

    tts = cfg.get("voice_action_config", {}).get("tts_trigger_probability", cfg.get("tts_trigger_probability"))
    inject = cfg.get("skill_growth_config", {}).get(
        "enable_skill_growth_passive_injection", cfg.get("enable_skill_growth_passive_injection"))

    return {
        "persona": {
            "length": len(sp),
            "zhu_ren": sp.count("主人"),
            "lao_die": sp.count("主人"),
            "sections": [
                {"name": "一~七 原始人设", "ok": "七、 语感参考示例" in sp},
                {"name": "八 生活锚点", "ok": "## 八、生活锚点" in sp},
                {"name": "九 落地纪律", "ok": "## 九、几条落地纪律" in sp},
                {"name": "十 成长履历", "ok": bool(sec10)},
                {"name": "十一 想要但还没有的", "ok": bool(sec11)},
            ],
            "growth": bullets(sec10),
            "wants": bullets(sec11),
        },
        "growth_store": [{"date": e.get("date"), "insight": e.get("insight")}
                         for e in (growth.get("entries") or [])],
        "wants_store": [{"want": i.get("want"), "need": i.get("need"), "since": i.get("since")}
                        for i in (wants.get("items") or [])],
        "skills": skills,
        "worldbook": {
            "members": [{"name": v.get("name"), "aliases": v.get("aliases")} for v in members.values() if isinstance(v, dict)],
            "groups": [{"name": v.get("name")} for v in groups.values() if isinstance(v, dict)],
        },
        "goals": [{"title": g.get("title"), "next": g.get("next_step"), "progress": g.get("progress")} for g in goals],
        "blackout": {"count": blackout_detail().get("count", 0)},
        "counters": {"messages": msgs, "diaries": diaries, "dreams": dreams,
                     "reviews": episodes, "bili_watch": len(watch) if isinstance(watch, list) else 0},
        "state": {"mood": ds.get("mood_bias"), "energy": ds.get("energy"), "sleep": ds.get("sleep")},
        "flags": {"tts": tts, "skill_inject": inject},
    }


def scan_plugins() -> tuple[list[dict], list[dict]]:
    """扫插件目录，拿到聊天指令（含别名）和 LLM 工具。"""
    commands, tools = [], []
    if not os.path.isdir(PLUGINS):
        return commands, tools
    cmd_re = re.compile(r'@filter\.command(?:_group)?\(\s*"([^"]+)"')
    alias_re = re.compile(
        r'@filter\.command(?:_group)?\(\s*"([^"]+)"\s*,\s*alias(?:es)?\s*=\s*(\{[^}]*\}|"[^"]*"|\[[^\]]*\])')
    word_re = re.compile(r'"([^"]+)"')
    tool_re = re.compile(r'llm_tool\(\s*(?:name\s*=\s*)?"([^"]+)"')
    for name in sorted(os.listdir(PLUGINS)):
        d = os.path.join(PLUGINS, name)
        if not os.path.isdir(d):
            continue
        aliases: dict[str, list[str]] = {}
        cmds, tls = set(), set()
        for f in os.listdir(d):
            if not f.endswith(".py"):
                continue
            try:
                text = open(os.path.join(d, f), encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            cmds.update(cmd_re.findall(text))
            tls.update(tool_re.findall(text))
            for primary, raw in alias_re.findall(text):
                names = [w for w in word_re.findall(raw) if w and w != primary]
                if names:
                    aliases.setdefault(primary, [])
                    aliases[primary] += [w for w in names if w not in aliases[primary]]
        for c in sorted(cmds):
            commands.append({"plugin": name, "command": c, "aliases": aliases.get(c, [])})
        for t in sorted(tls):
            tools.append({"plugin": name, "tool": t})
    return commands, tools


def recent_chat(limit: int = 12) -> list[dict]:
    """最近几轮对话。媒体占位符换成 [媒体]，免得满屏 <pc_history_media/>。"""
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{LM_DB}?mode=ro", uri=True, timeout=8)
        rows = con.execute(
            "select role, content, timestamp, sender_name from messages "
            "order by timestamp desc limit ?", (limit,)).fetchall()
        con.close()
    except Exception:
        return []
    out = []
    for role, content, ts, name in reversed(rows):
        text = re.sub(r"<pc_history_media[^>]*/?>", "[媒体]", str(content or ""))
        text = re.sub(r"\s+", " ", text).strip()[:220]
        stamp = ""
        if isinstance(ts, (int, float)) and ts > 1e9:
            stamp = time.strftime("%m-%d %H:%M", time.localtime(ts))
        out.append({"role": "her" if role == "assistant" else "me",
                    "who": "她" if role == "assistant" else (name or "主人"),
                    "at": stamp, "text": text})
    return out


POKE_STATE = os.path.join(
    ROOT, r"astrbot\data\plugin_data\astrbot_plugin_chengyin_poke_guard\state.json")
POKE_CFG = os.path.join(
    ROOT, r"astrbot\data\config\astrbot_plugin_chengyin_poke_guard_config.json")


def blackout_detail() -> dict:
    """小黑屋：谁被关着、还剩多久。只读忍耐度插件的状态文件。"""
    import time
    now = time.time()
    state = load_json(POKE_STATE, {}) or {}
    cfg = load_json(POKE_CFG, {}) or {}
    rows = state.get("blackout") if isinstance(state, dict) else None
    items = []
    if isinstance(rows, dict):
        for user, until in rows.items():
            if ":" in str(user):
                continue  # 旧格式（群:用户），新逻辑按人记，忽略
            try:
                until = float(until)
            except (TypeError, ValueError):
                continue
            if until <= now:
                continue
            items.append({
                "user": str(user),
                "left_minutes": int((until - now) // 60),
                "until": time.strftime("%H:%M", time.localtime(until)),
            })
    items.sort(key=lambda r: r["left_minutes"])
    return {
        "title": "小黑屋",
        "count": len(items),
        "rules": {
            "window_seconds": cfg.get("window_seconds"),
            "warn_count": cfg.get("warn_count"),
            "angry_count": cfg.get("angry_count"),
            "blackout_count": cfg.get("blackout_count"),
            "blackout_hours": round((cfg.get("blackout_seconds") or 0) / 3600, 1),
            "poke_back_probability": cfg.get("poke_back_probability"),
            "owner_ids": cfg.get("owner_ids") or [],
        },
        "items": items,
    }


def load_detail(kind: str) -> dict:
    """「她能查到什么」点开的详情。只读她自己的数据文件。"""
    companions = load_json(COMPANIONS, {}) if isinstance(load_json(COMPANIONS, {}), dict) else {}
    if kind == "bili":
        rows = load_json(os.path.join(ROOT, r"astrbot\data\plugin_data\astrbot_plugin_bili_scroll\watch_log.json"), [])
        if isinstance(rows, dict):
            rows = list(rows.values())
        items = [{"time": r.get("time"), "title": r.get("title"), "up": r.get("up_name"),
                  "score": r.get("score"), "mood": r.get("mood"),
                  "comment": r.get("comment"), "review": r.get("review")}
                 for r in rows if isinstance(r, dict)]
        return {"title": "B 站看过什么", "items": items[::-1]}
    if kind == "diary":
        items = [{"date": d.get("date"), "summary": d.get("summary"), "body": d.get("body"),
                  "tags": d.get("tags") or []}
                 for d in (companions.get("bot_diaries") or []) if isinstance(d, dict)]
        return {"title": "她的日记", "items": items[::-1]}
    if kind == "dream":
        items = [{"date": d.get("date"), "text": d.get("text"), "weight": d.get("weight"),
                  "source": d.get("source")}
                 for d in (companions.get("dream_fragments") or []) if isinstance(d, dict)]
        return {"title": "她做的梦", "items": items[::-1]}
    if kind == "review":
        items = [{"date": r.get("date"), "headline": r.get("headline"), "summary": r.get("summary"),
                  "score": r.get("health_score")}
                 for r in (companions.get("daily_review_reports") or []) if isinstance(r, dict)]
        return {"title": "每日复盘", "items": items[::-1]}
    if kind == "memory":
        return {"title": "长期记忆（按重要度）", "items": memory_items(30)}
    if kind == "backup":
        groups = backup_items()
        items = []
        for g in groups:
            for f in g["files"]:
                items.append({"group": g["label"], "name": f["name"],
                              "size_kb": f["size_kb"], "at": f["at"], "path": g["path"]})
        return {"title": "备份清单", "items": items, "groups": groups}
    if kind == "poke":
        return blackout_detail()
    if kind == "errors":
        return recent_errors()
    if kind == "relation":
        prof = companions.get("worldbook_member_profiles") or {}
        grp = companions.get("worldbook_group_profiles") or {}
        items = [{"name": v.get("name"), "kind": "成员", "aliases": v.get("aliases"),
                  "content": v.get("content")}
                 for v in prof.values() if isinstance(v, dict)]
        items += [{"name": v.get("name"), "kind": "群", "aliases": [], "content": v.get("content")}
                  for v in grp.values() if isinstance(v, dict)]
        return {"title": "关系档案", "items": items}
    return {"title": "不知道要看什么", "items": []}


ERR_LOG = os.path.join(ROOT, r"logs\astrbot.log")

# 已知无关噪音（网络抖动、加载顺序告警）
_ERR_NOISE = (
    "ConnectionResetError",
    "_call_connection_lost",
    "Win32。10054",
    "WinError 10054",
    "远程主机强迫关闭",
    "ProactorBasePipeTransport",
    "Failed to import plugin",
    "未检测到陪伴主插件",
)


def _err_source(line: str) -> str:
    """从日志行里认出是哪个插件/模块报的。

    Args:
        line: 单行日志。

    Returns:
        插件名或模块名，认不出就返回 "core"。
    """
    m = re.search(r"\[([a-z0-9_]*plugin_[a-z0-9_]+)[^\]]*\]", line)
    if m:
        return m.group(1)
    m = re.search(r"\[([a-zA-Z0-9_.]+):\d+\]", line)
    if m:
        return m.group(1)
    return "core"


def recent_errors(limit: int = 40) -> dict:
    """扫日志，把报错按来源归堆。

    每组给出：来源、异常/消息、traceback 最后几帧、出现次数与最近时间。

    Args:
        limit: 最多返回多少组。

    Returns:
        {"title": ..., "count": 组数, "items": [...]}
    """
    import collections

    groups: "collections.OrderedDict[str, dict]" = collections.OrderedDict()
    total_file_lines = 0
    try:
        with open(ERR_LOG, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        total_file_lines = len(lines)
        lines = lines[-6000:]
    except OSError:
        return {"title": "最近的报错", "count": 0, "items": [], "missing": True}

    i = 0
    total = len(lines)
    while i < total:
        line = lines[i].rstrip("\n")
        is_error = "[ERRO]" in line or "ERROR" in line
        is_tb = line.strip().startswith("Traceback (most recent call last)")
        if not (is_error or is_tb):
            i += 1
            continue
        if any(n in line for n in _ERR_NOISE):
            i += 1
            continue

        ts = ""
        m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if m:
            ts = m.group(1)
        source = _err_source(line)
        message = re.sub(r"^.*?\]:\s*", "", line)[:300]

        # 抓紧随其后的 traceback 帧与异常行
        frames: list[str] = []
        exception = ""
        j = i + 1
        while j < total and j <= i + 40:
            nxt = lines[j].rstrip("\n")
            if not nxt.strip():
                break
            if 'File "' in nxt:
                frames.append(nxt.strip()[:160])
            elif re.match(r"^[A-Za-z_.]*(Error|Exception|Warning)\b", nxt.strip()):
                exception = nxt.strip()[:220]
                break
            elif nxt.startswith("[") and "[ERRO]" in nxt:
                break
            elif not nxt.startswith(" ") and not nxt.startswith("\t"):
                break
            j += 1
        i = j + 1

        # 归一化：BV 号、长数字、十六进制都换成占位符，同类错误才能合并
        normalized = re.sub(r"BV[0-9A-Za-z]{10}", "<BV>", exception or message)
        normalized = re.sub(r"\b[0-9a-f]{8,}\b", "<hex>", normalized)
        normalized = re.sub(r"\d{4,}", "<n>", normalized)
        signature = f"{source}|{normalized}"
        line_no = total_file_lines - (total - j) if total_file_lines else 0
        record = groups.get(signature)
        if record:
            record["count"] += 1
            record["last"] = ts or record["last"]
            record["line"] = line_no
        elif len(groups) < limit:
            groups[signature] = {
                "time": ts,
                "last": ts,
                "source": source,
                "message": message,
                "exception": exception,
                "frames": frames[-4:],
                "count": 1,
                "line": line_no,
            }

    items = list(groups.values())
    items.sort(key=lambda r: r.get("last") or "", reverse=True)
    return {"title": "最近的报错", "count": len(items), "items": items, "log": ERR_LOG}


def system_status() -> dict:
    """谁在跑、跑了多久、吃多少内存、日志里有多少错。全只读。"""
    out = {"bot": {}, "ports": {}, "log": {}, "panel": {"pid": os.getpid()}}
    try:
        import psutil
        try:
            out["panel"]["mem_mb"] = round(psutil.Process().memory_info().rss / 1024 / 1024)
        except Exception:
            pass
        for pid, kind in ((_listener_pid(6185), "bot"), (_listener_pid(6199), "napcat")):
            if not pid:
                out["ports"][kind] = False
                continue
            out["ports"][kind] = True
            try:
                p = psutil.Process(pid)
                started = p.create_time()
                out[kind] = {
                    "pid": pid,
                    "uptime_h": round((time.time() - started) / 3600, 1),
                    "started": time.strftime("%m-%d %H:%M", time.localtime(started)),
                    "mem_mb": round(p.memory_info().rss / 1024 / 1024),
                    "cpu": round(p.cpu_percent(interval=0.15), 1),
                }
            except Exception:
                pass
    except Exception:
        pass
    try:
        errs = 0
        lines = 0
        last = ""
        last_source = ""
        with open(os.path.join(ROOT, r"logs\astrbot.log"), encoding="utf-8", errors="replace") as f:
            for line in f.readlines()[-600:]:
                lines += 1
                stripped = line.strip()
                is_header = "Traceback (most recent call last)" in stripped
                is_frame = stripped.startswith('File "')
                if ("ERROR" in line or "Traceback" in line) and not is_header and not is_frame and not any(
                    n in line for n in _ERR_NOISE
                ):
                    errs += 1
                    m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                    if m and not last:
                        last = m.group(1)
                    if not last_source and errs == 1:
                        last_source = _err_source(line)
        out["log"] = {"scanned": lines, "errors": errs,
                      "last": (f"{last[5:]} {last_source}".strip() if last else ""),
                      "source": last_source}
    except Exception:
        pass
    return out


def _listener_pid(port: int) -> int:
    try:
        import psutil
        for c in psutil.net_connections(kind="tcp"):
            if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port and c.pid:
                return c.pid
    except Exception:
        pass
    return 0


def mood_and_plan() -> dict:
    """今天的心情底子和日程。日程从 raw JSON 里解析，解析不了就算了。"""
    d = load_json(COMPANIONS, {})
    if not isinstance(d, dict):
        return {}
    state = d.get("daily_state") or {}
    plan = d.get("daily_plan") or {}
    items = plan.get("items")
    if not isinstance(items, list) or not items:
        items = []
        raw = str(plan.get("raw") or "")
        try:
            parsed = json.loads(raw)
            items = parsed.get("schedule") or []
        except Exception:
            m = re.search(r"\[.*\]", raw, re.S)
            if m:
                try:
                    items = json.loads(m.group(0))
                except Exception:
                    items = []
    clean = []
    for it in items[:10]:
        if isinstance(it, dict):
            clean.append({"time": it.get("time"), "end": it.get("end"),
                          "activity": str(it.get("activity") or "")[:120],
                          "mood": it.get("mood"), "seed": it.get("message_seed")})
    return {
        "date": state.get("date"), "mood": state.get("mood_bias"), "energy": state.get("energy"),
        "sleep": state.get("sleep"), "health": state.get("health"),
        "hunger": state.get("hunger"), "weather": state.get("weather"),
        "plan_date": plan.get("date"), "plan_source": plan.get("source"), "plan": clean,
    }


def memory_items(limit: int = 30) -> list[dict]:
    try:
        import sqlite3
        path = os.path.join(ROOT, r"astrbot\data\plugin_data\astrbot_plugin_livingmemory\livingmemory.db")
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=8)
        rows = con.execute(
            "select content, importance, decay_type, ttl_days, status, created_at "
            "from memory_atoms order by importance desc, created_at desc limit ?", (limit,)).fetchall()
        con.close()
    except Exception:
        return []
    out = []
    for content, imp, decay, ttl, status, created in rows:
        out.append({"text": str(content or "")[:160], "importance": imp,
                    "decay": decay, "ttl": round(float(ttl), 1) if ttl else None,
                    "status": status,
                    "at": time.strftime("%m-%d %H:%M", time.localtime(created))
                    if isinstance(created, (int, float)) and created > 1e9 else ""})
    return out


def backup_items() -> list[dict]:
    """三处备份的清单。只列，不给一键还原——写人格的路要经过脚本。"""
    out = []
    dirs = [
        ("人格/配置", os.path.join(ROOT, r"tools\persona-kit\backup")),
        ("人格/配置(子目录)", os.path.join(ROOT, r"tools\persona-kit\backup\config")),
        ("成长快照", os.path.join(ROOT, r"tools\growth\backups")),
        ("补丁前代码", os.path.join(ROOT, r"tools\persona-kit\backup\code")),
        ("人生存档 I:", os.path.join(ROOT, "archives")),
        ("人生存档 E:", r"D:\chengyin\archives"),
    ]
    for label, path in dirs:
        if not os.path.isdir(path):
            continue
        files = []
        try:
            for f in sorted(os.listdir(path))[:40]:
                fp = os.path.join(path, f)
                if not os.path.isfile(fp):
                    continue
                files.append({"name": f, "size_kb": round(os.path.getsize(fp) / 1024),
                              "at": time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(fp)))})
        except Exception:
            continue
        out.append({"label": label, "path": path, "count": len(files), "files": files[::-1]})
    return out


def trigger_words() -> dict:
    """她会被哪些话叫出来。这些不在代码里，在配置里。"""
    cfg = load_json(PLUGIN_CFG, {})
    if not isinstance(cfg, dict):
        return {}

    def get(key, default=None):
        if key in cfg:
            return cfg[key]
        for grp in cfg.values():
            if isinstance(grp, dict) and key in grp:
                return grp[key]
        return default

    def to_list(raw):
        if isinstance(raw, list):
            return [str(x) for x in raw if str(x).strip()]
        if isinstance(raw, str):
            return [x.strip() for x in re.split(r"[,，、\n]+", raw) if x.strip()]
        return []

    return {
        "bot_name": str(get("bot_name", "") or ""),
        "voice": to_list(get("tts_trigger_keywords", "")),
        "group_context": to_list(get("group_wakeup_context_words", [])),
        "group_direct": to_list(get("group_wakeup_direct_words", [])),
        "group_owner_direct": to_list(get("group_wakeup_owner_direct_words", [])),
        "bot_name_wakeup": bool(get("enable_group_bot_name_wakeup", False)),
        "image_wakeup": bool(get("enable_group_image_wakeup", False)),
    }


TASKS = (
    ("ChengYin-Growth", "每天 05:10", 5, 10, None),
    ("ChengYin-Help", "每天 06:10", 6, 10, None),
    ("ChengYin-Archive", "每周日 05:30", 5, 30, 6),   # 6 = 周日
)


def scheduled_tasks() -> list[dict]:
    """按已知计划算下次时间。不调 schtasks —— 中文系统下它的输出编码不可靠。"""
    from datetime import datetime, timedelta

    now = datetime.now()
    out = []
    for name, label, hh, mm, weekday in TASKS:
        nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if weekday is None:
            if nxt <= now:
                nxt += timedelta(days=1)
        else:
            while nxt <= now or nxt.weekday() != weekday:
                nxt += timedelta(days=1)
        out.append({"name": name, "label": label,
                    "next": nxt.strftime("%m-%d %H:%M")})
    return out


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "ChengYinPanel/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            html = open(os.path.join(HERE, "index.html"), "rb").read()
            return self._send(200, html, "text/html; charset=utf-8")
        if path == "/api/state":
            try:
                return self._send(200, json.dumps(build_state(), ensure_ascii=False).encode(),
                                  "application/json; charset=utf-8")
            except Exception as exc:
                return self._send(500, json.dumps({"error": str(exc)}, ensure_ascii=False).encode(),
                                  "application/json; charset=utf-8")
        if path == "/api/catalog":
            commands, tools = _cached("catalog", 120, scan_plugins)
            data = {"commands": commands, "tools": tools, "tasks": scheduled_tasks(),
                    "triggers": trigger_words()}
            return self._send(200, json.dumps(data, ensure_ascii=False).encode(),
                              "application/json; charset=utf-8")
        if path == "/api/detail":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            kind = (qs.get("kind") or [""])[0]
            if kind not in {"bili", "diary", "dream", "review", "relation", "memory", "backup", "poke", "errors"}:
                return self._send(400, json.dumps({"error": "unknown kind"}).encode(),
                                  "application/json; charset=utf-8")
            try:
                data = load_detail(kind)
            except Exception as exc:
                return self._send(500, json.dumps({"error": str(exc)}, ensure_ascii=False).encode(),
                                  "application/json; charset=utf-8")
            return self._send(200, json.dumps(data, ensure_ascii=False).encode(),
                              "application/json; charset=utf-8")
        if path == "/api/system":
            try:
                data = {"status": _cached("system", 30, system_status)}
            except Exception as exc:
                data = {"error": str(exc)}
            return self._send(200, json.dumps(data, ensure_ascii=False).encode(),
                              "application/json; charset=utf-8")
        if path == "/api/mood":
            try:
                data = mood_and_plan()
            except Exception as exc:
                data = {"error": str(exc)}
            return self._send(200, json.dumps(data, ensure_ascii=False).encode(),
                              "application/json; charset=utf-8")
        if path == "/api/chat":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                limit = max(1, min(50, int(qs.get("limit", ["12"])[0])))
            except ValueError:
                limit = 12
            return self._send(200, json.dumps({"messages": recent_chat(limit)}, ensure_ascii=False).encode(),
                              "application/json; charset=utf-8")
        if path == "/api/health":
            try:
                r = subprocess.run([PY, HEALTH], capture_output=True, text=True, timeout=60,
                                   encoding="utf-8", errors="replace")
                payload = {"ok": r.returncode == 0, "output": (r.stdout or "") + (r.stderr or "")}
            except Exception as exc:
                payload = {"ok": False, "output": f"体检跑不起来：{exc}"}
            return self._send(200, json.dumps(payload, ensure_ascii=False).encode(),
                              "application/json; charset=utf-8")
        return self._send(404, b'{"error":"not found"}', "application/json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"澄音面板：http://127.0.0.1:{args.port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
