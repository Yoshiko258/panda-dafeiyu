# -*- coding: utf-8 -*-
"""把人格 system_prompt 还原成某个备份。

用法：
    python restore_persona.py --list
    python restore_persona.py --file backup/persona_澄音_20261108-030244.json --apply

不带 --apply 只看差异，不写。
"""
from __future__ import annotations

import argparse
import re
import glob
import io
import json
import os
import sys
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # 被别的程序 import 时 stdout 可能不是 TextIO，忽略即可

BASE = "http://127.0.0.1:6185"
HERE = os.path.dirname(os.path.abspath(__file__))
CRED_FILE = r"D:\chengyin\我的信息.txt"


def credentials() -> tuple[str, str]:
    """后台账号密码：优先环境变量，其次读澄音后台的说明文件。

    不把密码写死在代码里——这个目录以后可能被复制或分享出去。
    """
    user = os.environ.get("DSH_DASH_USER")
    pwd = os.environ.get("DSH_DASH_PASS")
    if user and pwd:
        return user, pwd
    try:
        text = open(CRED_FILE, encoding="utf-8-sig").read()
        u = re.search(r"账号[:：]\s*(\S+)", text)
        p = re.search(r"密码[:：]\s*(\S+)", text)
        if u and p:
            return u.group(1), p.group(1)
    except OSError:
        pass
    raise SystemExit(
        "拿不到后台账号密码：设置环境变量 DSH_DASH_USER / DSH_DASH_PASS，"
        f"或确认 {CRED_FILE} 存在且含「账号：」「密码：」两行。"
    )


def call(method: str, path: str, payload=None, token: str | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    backups = sorted(glob.glob(os.path.join(HERE, "backup", "persona_*.json")))
    if args.list or not args.file:
        print("可用备份：")
        for b in backups:
            print("  ", os.path.basename(b), os.path.getsize(b), "bytes")
        if not args.file:
            print("\n用 --file 指定要还原的那份。")
            return 0

    path = args.file
    if path and not os.path.isabs(path):
        # 允许写 backup\xxx.json 这种相对路径，按脚本目录解析
        cand = os.path.join(HERE, path)
        if os.path.exists(cand):
            path = cand
    if not path or not os.path.exists(path):
        print(f"找不到备份文件: {args.file}", file=sys.stderr)
        return 2

    snap = json.load(open(path, encoding="utf-8-sig"))
    pid = snap["persona_id"]
    target = snap["system_prompt"]

    user, pwd = credentials()
    token = call("POST", "/api/auth/login", {"username": user, "password": pwd})["data"]["token"]
    cur = call("GET", "/api/v1/personas/by-id?persona_id=" + urllib.parse.quote(pid), token=token)["data"]

    print(f"人格 {pid}")
    print(f"  当前 {len(cur['system_prompt'])} 字 → 还原成 {len(target)} 字")
    if cur["system_prompt"] == target:
        print("  已经一致，不用还原。")
        return 0

    if not args.apply:
        print("  [dry-run] 没写入。加 --apply 才真正还原。")
        return 0

    body = {"persona_id": pid, "system_prompt": target, "begin_dialogs": snap.get("begin_dialogs") or []}
    for key in ("tools", "skills", "custom_error_message"):
        if snap.get(key) is not None:
            body[key] = snap[key]
    res = call("PUT", "/api/v1/personas/by-id", body, token=token)
    print("  还原结果:", res.get("status"))

    chk = call("GET", "/api/v1/personas/by-id?persona_id=" + urllib.parse.quote(pid), token=token)["data"]
    print("  回读校验一致:", chk["system_prompt"] == target)
    return 0 if chk["system_prompt"] == target else 1


if __name__ == "__main__":
    raise SystemExit(main())
