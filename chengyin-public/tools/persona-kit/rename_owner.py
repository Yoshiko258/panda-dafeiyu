# -*- coding: utf-8 -*-
"""把澄音对他的称呼从「主人」改成「主人」。

要改四处，少一处就会打架：
  1. 人格正文（46 处）
  2. growth.json（成长例句里也写着"给主人念语音"，不改的话下次重拼第十节会退回主人）
  3. worldbook 关系档案（name / aliases / content / note）
  4. growth.py 里给模型看的对话标签
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # 被别的程序 import 时 stdout 可能不是 TextIO，忽略即可

BASE = "http://127.0.0.1:6185"
PLUGIN = "astrbot_plugin_private_companion"
PAGE = f"/api/v1/plugins/extensions/{PLUGIN}/page"
PERSONA_ID = "澄音"
CRED = r"D:\chengyin\我的信息.txt"
COMP = r"D:\chengyin\astrbot\data\plugin_data\astrbot_plugin_private_companion\companions.json"
STORE = r"D:\chengyin\tools\growth\growth.json"
BAK = r"D:\chengyin\tools\persona-kit\backup"

OLD, NEW = "主人", "主人"


def call(method, path, payload=None, token=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())


def login() -> str:
    text = open(CRED, encoding="utf-8-sig").read()
    u = re.search(r"账号[:：]\s*(\S+)", text).group(1)
    p = re.search(r"密码[:：]\s*(\S+)", text).group(1)
    return call("POST", "/api/auth/login", {"username": u, "password": p})["data"]["token"]


def fix_grammar(text: str) -> str:
    """生硬替换之后，把几处读着别扭的顺一顺。"""
    patches = [
        ("唯一主人（QQ号", "唯一的主人（QQ号"),
        ("任何非主人的外人", "除了主人以外的任何人"),
        ("自称是你主人", "自称是你主人"),
        ("一位主人哦", "一个主人哦"),
    ]
    for a, b in patches:
        text = text.replace(a, b)
    return text


def main() -> int:
    apply = "--apply" in sys.argv

    # ---------- 1. 人格 ----------
    token = login()
    snap = call("GET", "/api/v1/personas/by-id?persona_id=" + urllib.parse.quote(PERSONA_ID), token=token)["data"]
    old_persona = snap["system_prompt"]
    n = old_persona.count(OLD)
    new_persona = fix_grammar(old_persona.replace(OLD, NEW))
    print(f"人格：{OLD} × {n} → {NEW}｜{len(old_persona)} → {len(new_persona)} 字")

    # ---------- 2. 成长库 ----------
    store = json.load(open(STORE, encoding="utf-8"))
    store_hits = 0
    for e in store.get("entries") or []:
        for k in ("insight", "evidence"):
            if isinstance(e.get(k), str) and OLD in e[k]:
                e[k] = fix_grammar(e[k].replace(OLD, NEW))
                store_hits += 1
    print(f"成长库：改了 {store_hits} 处")

    # ---------- 3. worldbook ----------
    data = json.load(open(COMP, encoding="utf-8"))
    profiles = data.get("worldbook_member_profiles") or {}
    wb_updates = []
    for uid, prof in profiles.items():
        if not isinstance(prof, dict):
            continue
        payload = {"user_id": uid}
        changed = False
        name = str(prof.get("name") or "")
        if OLD in name:
            payload["name"] = name.replace(OLD, NEW)
            changed = True
        for field in ("content", "note", "identity_note"):
            val = str(prof.get(field) or "")
            if OLD in val:
                payload[field] = fix_grammar(val.replace(OLD, NEW))
                changed = True
        aliases = [str(a) for a in (prof.get("aliases") or [])]
        if uid == "1000000001" and NEW not in aliases:
            payload["aliases"] = [NEW] + aliases
            changed = True
        if changed:
            wb_updates.append(payload)
    print(f"worldbook：{len(wb_updates)} 条要改")

    if not apply:
        print("\n[dry-run] 没写入。加 --apply 才提交。")
        return 0

    os.makedirs(BAK, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time()*1000)%1000:03d}"
    json.dump(snap, open(os.path.join(BAK, f"persona_before_laodie_{ts}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    shutil.copy2(STORE, os.path.join(BAK, f"growth_before_laodie_{ts}.json"))
    shutil.copy2(COMP, os.path.join(BAK, f"companions_before_laodie_{ts}.json"))
    print(f"已备份 3 份到 {os.path.basename(BAK)}")

    body = {"persona_id": PERSONA_ID, "system_prompt": new_persona,
            "begin_dialogs": snap.get("begin_dialogs") or []}
    for k in ("tools", "skills", "custom_error_message"):
        if snap.get(k) is not None:
            body[k] = snap[k]
    print("人格写入:", call("PUT", "/api/v1/personas/by-id", body, token=token).get("status"))

    json.dump(store, open(STORE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("成长库已写")

    for payload in wb_updates:
        r = call("POST", PAGE + "/worldbook/member/update", payload, token=token)
        print(f"  worldbook {payload['user_id']}: {r.get('status') or r.get('message') or 'ok'}")

    # ---------- 校验 ----------
    time.sleep(1)
    chk = call("GET", "/api/v1/personas/by-id?persona_id=" + urllib.parse.quote(PERSONA_ID), token=token)["data"]["system_prompt"]
    print("\n校验：")
    print(f"  人格里「{OLD}」剩 {chk.count(OLD)} 处｜「{NEW}」{chk.count(NEW)} 处")
    print(f"  原文其余未变：{chk.replace(NEW, OLD) == old_persona}")
    d2 = json.load(open(COMP, encoding="utf-8"))
    for uid, prof in (d2.get("worldbook_member_profiles") or {}).items():
        print(f"  worldbook {uid}: name={prof.get('name')} aliases={prof.get('aliases')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
