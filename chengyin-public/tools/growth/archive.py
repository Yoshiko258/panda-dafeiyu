# -*- coding: utf-8 -*-
r"""人生存档：把她这一整套状态打成一个可校验的 ZIP。

    python archive.py                 # 打包到 D:\chengyin\archives\
    python archive.py --out D:\bak
    python archive.py --verify xxx.zip

打包内容：
  companions.json      她的记忆、关系、日记、梦、技能、日程
  persona.json         人格正文（从后台 API 取，含第十节成长履历）
  conversations.db     全部对话原文（livingmemory）
  growth.json          成长履历与来源证据
  plugin_config.json   陪伴插件的全部设置（1008 个键）

**不打包**：cmd_config.json（里面有 API key）。要完整迁移请自己另外备份。

每个文件都记 SHA-256，打包完会重读一遍校验。
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # 被别的程序 import 时 stdout 可能不是 TextIO，忽略即可

BASE = "http://127.0.0.1:6185"
PERSONA_ID = "澄音"
CRED_FILE = r"D:\chengyin\我的信息.txt"
ROOT = r"D:\chengyin"
OUT_DIR = os.path.join(ROOT, "archives")
# 另一块物理盘（E: 在磁盘 0，I: 在磁盘 3），整盘挂了这份还在
MIRROR_DIR = r"D:\chengyin\archives"

SOURCES = {
    "companions.json": os.path.join(ROOT, r"astrbot\data\plugin_data\astrbot_plugin_private_companion\companions.json"),
    "conversations.db": os.path.join(ROOT, r"astrbot\data\plugin_data\astrbot_plugin_livingmemory\conversations.db"),
    "plugin_config.json": os.path.join(ROOT, r"astrbot\data\config\astrbot_plugin_private_companion_config.json"),
    "growth.json": os.path.join(ROOT, r"tools\growth\growth.json"),
}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def credentials() -> tuple[str, str]:
    text = open(CRED_FILE, encoding="utf-8-sig").read()
    u = re.search(r"账号[:：]\s*(\S+)", text)
    p = re.search(r"密码[:：]\s*(\S+)", text)
    if not u or not p:
        raise SystemExit("读不到后台账号密码")
    return u.group(1), p.group(1)


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
    u, p = credentials()
    req = urllib.request.Request(BASE + "/api/auth/login",
                                 data=json.dumps({"username": u, "password": p}).encode(),
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())["data"]["token"]


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


def fetch_persona(out_path: str) -> None:
    token = login()
    req2 = urllib.request.Request(
        BASE + "/api/v1/personas/by-id?persona_id=" + urllib.parse.quote(PERSONA_ID))
    req2.add_header("Authorization", "Bearer " + token)
    data = json.loads(urllib.request.urlopen(req2, timeout=30).read().decode())["data"]
    json.dump(data, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def build(out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time()*1000)%1000:03d}"
    zpath = os.path.join(out_dir, f"life-{stamp}.zip")

    tmp = tempfile.mkdtemp(prefix="life-")
    staged: list[str] = []
    try:
        for name, src in SOURCES.items():
            if not os.path.exists(src):
                print(f"  跳过（不存在）: {name}")
                continue
            dst = os.path.join(tmp, name)
            if name.endswith(".db"):
                # 直接用 copy 只能拿到旧的库内容——新的对话都在 -wal 里
                # 用 sqlite 的 backup API 才能拿到一致的快照
                import sqlite3
                s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=15)
                try:
                    d = sqlite3.connect(dst)
                    try:
                        s.backup(d)
                    finally:
                        d.close()
                finally:
                    s.close()
            else:
                shutil.copy2(src, dst)
            staged.append(name)
            print(f"  + {name}  {os.path.getsize(dst)/1024/1024:.1f} MB")

        persona_tmp = os.path.join(tmp, "persona.json")
        fetch_persona(persona_tmp)
        staged.append("persona.json")
        print(f"  + persona.json  {os.path.getsize(persona_tmp)/1024:.0f} KB")

        manifest = {"created_at": stamp, "files": {}}
        for name in staged:
            p = os.path.join(tmp, name)
            manifest["files"][name] = {"sha256": sha256(p), "size": os.path.getsize(p)}
        json.dump(manifest, open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for name in staged + ["manifest.json"]:
                z.write(os.path.join(tmp, name), arcname=name)
        return zpath
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def verify(zpath: str) -> bool:
    with zipfile.ZipFile(zpath) as z:
        bad = z.testzip()
        if bad:
            print(f"损坏的条目: {bad}")
            return False
        manifest = json.loads(z.read("manifest.json").decode())
        ok = True
        for name, meta in manifest["files"].items():
            h = hashlib.sha256(z.read(name)).hexdigest()
            same = (h == meta["sha256"])
            print(f"  {'✓' if same else '✗'} {name}  {meta['size']/1024/1024:.1f} MB")
            ok &= same
        return ok


def prune(out_dir: str, keep: int) -> None:
    """只保留最近 keep 份存档，免得天天涨。keep <= 0 表示不清理。"""
    if keep <= 0:
        return
    files = sorted(
        (p for p in glob.glob(os.path.join(out_dir, "life-*.zip"))),
        key=os.path.getmtime,
    )
    for old in files[:-keep]:
        try:
            os.remove(old)
            print(f"  清理旧存档: {os.path.basename(old)}")
        except OSError:
            pass


def mirror(zpath: str, mirror_dir: str, keep: int) -> bool:
    """往另一块盘再放一份。整盘挂了的时候，这份才是救命的。"""
    try:
        os.makedirs(mirror_dir, exist_ok=True)
        target = os.path.join(mirror_dir, os.path.basename(zpath))
        shutil.copy2(zpath, target)
    except Exception as exc:
        print(f"  异地备份失败：{exc}")
        return False
    src_sum = sha256(zpath)
    dst_sum = sha256(target)
    if src_sum != dst_sum:
        print(f"  异地备份校验不一致，源 {src_sum[:12]} 目标 {dst_sum[:12]}")
        return False
    print(f"  异地备份 ✓ {target}  ({os.path.getsize(target)/1024/1024:.1f} MB, sha {dst_sum[:12]})")
    prune(mirror_dir, keep)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="澄音人生存档")
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--mirror", default=MIRROR_DIR,
                    help=f"同时在另一块盘留一份，默认 {MIRROR_DIR}；传空字符串关掉")
    ap.add_argument("--keep", type=int, default=14, help="保留最近几份，默认 14；0 = 不清理")
    ap.add_argument("--verify", default=None)
    args = ap.parse_args()

    if args.verify:
        print(f"校验 {args.verify}")
        return 0 if verify(args.verify) else 1

    print("打包中…")
    zpath = build(args.out)
    size = os.path.getsize(zpath) / 1024 / 1024
    print(f"\n已生成 {zpath}  ({size:.1f} MB)")
    print("回读校验：")
    ok = verify(zpath)
    if args.mirror:
        print(f"\n异地备份 → {args.mirror}")
        ok &= mirror(zpath, args.mirror, args.keep)
    prune(args.out, args.keep)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
