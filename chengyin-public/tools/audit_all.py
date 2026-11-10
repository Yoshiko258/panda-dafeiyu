# -*- coding: utf-8 -*-
"""全项目体检（只读）：找出可比 verify_all 更细的问题。

检查：日志告警分布、数据膨胀、残留文件、进程与内存、计划任务、
配置与 schema 的键差异、面板接口、磁盘。
"""

from __future__ import annotations

import collections
import glob
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request

ROOT = r"D:\chengyin"
LOGS = os.path.join(ROOT, "logs")
DATA = os.path.join(ROOT, "astrbot", "data")
PLUGINS = os.path.join(DATA, "plugins")
PLUGIN_DATA = os.path.join(DATA, "plugin_data")
CONFIGS = os.path.join(DATA, "config")

findings: list[tuple[str, str, str]] = []


def note(level: str, area: str, message: str) -> None:
    """Record one finding.

    Args:
        level: OK / WARN / BUG.
        area: Short area label.
        message: Human readable detail.
    """
    findings.append((level, area, message))


def dir_size(path: str) -> int:
    """Total bytes under a directory."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def mb(value: int) -> str:
    """Format bytes as MB."""
    return f"{value / 1024 / 1024:.1f} MB"


def check_logs() -> None:
    """Log volume, warning hotspots, tracebacks."""
    path = os.path.join(LOGS, "astrbot.log")
    if not os.path.exists(path):
        note("BUG", "日志", "astrbot.log 不存在")
        return
    size = os.path.getsize(path)
    note("OK" if size < 60 * 1024 * 1024 else "WARN", "日志", f"astrbot.log {mb(size)}")

    age_min = (time.time() - os.path.getmtime(path)) / 60
    note("OK" if age_min < 15 else "WARN", "日志",
         f"astrbot.log 最后写入 {age_min:.0f} 分钟前")

    files = sorted(glob.glob(os.path.join(LOGS, "*.log")))
    note("OK", "日志", f"{len(files)} 个日志文件，共 {mb(sum(os.path.getsize(f) for f in files))}")

    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()[-40000:]

    warn_by_plugin: collections.Counter[str] = collections.Counter()
    err_by_plugin: collections.Counter[str] = collections.Counter()
    for line in lines:
        tag = "[WARN]" if "[WARN]" in line else ("[ERRO]" if "[ERRO]" in line else "")
        if not tag:
            continue
        m = re.search(r"\[(astrbot_plugin_[a-z0-9_]+|Core|core)[^\]]*\]", line)
        who = m.group(1) if m else "other"
        (warn_by_plugin if tag == "[WARN]" else err_by_plugin)[who] += 1

    if err_by_plugin:
        top = err_by_plugin.most_common(3)
        note("WARN", "日志", "错误最多的来源: " + "，".join(f"{k}×{v}" for k, v in top))
    else:
        note("OK", "日志", "近 4 万行没有 [ERRO]")

    noisy = [(k, v) for k, v in warn_by_plugin.most_common(3) if v >= 20]
    if noisy:
        detail = "，".join(f"{k}×{v}" for k, v in noisy)
        note("WARN", "日志", f"告警密集: {detail}")

    tb = sum(1 for line in lines if "Traceback (most recent call last)" in line)
    note("OK" if tb <= 5 else "WARN", "日志", f"近 4 万行 traceback {tb} 次")


def check_data_size() -> None:
    """Grow of runtime data."""
    for label, path in (
        ("plugin_data", PLUGIN_DATA),
        ("plugins", PLUGINS),
        ("conversations.db", os.path.join(PLUGIN_DATA, "astrbot_plugin_livingmemory", "conversations.db")),
        ("备份目录", os.path.join(ROOT, "tools", "persona-kit", "backup")),
        ("媒体缓存", os.path.join(PLUGIN_DATA, "astrbot_plugin_private_companion", "attachments")),
    ):
        if not os.path.exists(path):
            continue
        size = os.path.getsize(path) if os.path.isfile(path) else dir_size(path)
        level = "OK"
        if label in {"plugin_data", "备份目录", "媒体缓存"} and size > 800 * 1024 * 1024:
            level = "WARN"
        note(level, "数据", f"{label} {mb(size)}")

    db = os.path.join(PLUGIN_DATA, "astrbot_plugin_livingmemory", "conversations.db")
    if os.path.exists(db):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
            rows = con.execute("select count(*) from messages").fetchone()[0]
            con.close()
            note("OK", "数据", f"对话库 {rows:,} 条消息")
        except Exception as exc:  # noqa: BLE001
            note("WARN", "数据", f"对话库统计失败: {exc}")


def check_leftovers() -> None:
    """Stray build/backup files inside the project."""
    skip = ("node_modules", os.sep + "runtime", os.sep + "aisong", os.sep + ".tmp")
    for label, pattern, limit in (
        ("临时 .new", os.path.join(ROOT, "**", "*.new"), 20),
        ("备份 .bak", os.path.join(ROOT, "**", "*.bak"), 40),
    ):
        hits = [p for p in glob.glob(pattern, recursive=True)
                if not any(s in p for s in skip)]
        note("OK" if len(hits) <= limit else "WARN", "残留", f"{label}: {len(hits)} 个")

    # 项目自身的 __pycache__（不含 venv / 训练工程）
    code_pyc = [
        p for p in glob.glob(os.path.join(ROOT, "**", "*.pyc"), recursive=True)
        if not any(s in p for s in skip)
    ]
    note("OK" if len(code_pyc) < 3000 else "WARN", "残留", f"项目代码 pyc: {len(code_pyc)} 个")

    tmp_dir = os.path.join(ROOT, ".tmp")
    if os.path.exists(tmp_dir):
        size = dir_size(tmp_dir)
        note("OK" if size < 200 * 1024 * 1024 else "WARN", "残留", f".tmp 占用 {mb(size)}")


def check_processes() -> None:
    """Who is running and how much memory they hold."""
    try:
        import psutil
    except ImportError:
        note("WARN", "进程", "psutil 不可用")
        return

    wanted = {
        "AstrBot": None,
        "NapCat": None,
        "面板": None,
        "看门狗": None,
    }
    for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_info", "create_time"]):
        try:
            cmd = " ".join(proc.info["cmdline"] or [])
        except Exception:  # noqa: BLE001
            continue
        mem = proc.info["memory_info"].rss / 1024 / 1024 if proc.info["memory_info"] else 0
        if "main.py" in cmd and ROOT.lower() in cmd.lower():
            wanted["AstrBot"] = (proc.info["pid"], mem)
        elif "napcat" in cmd.lower():
            wanted["NapCat"] = (proc.info["pid"], mem)
        elif "panel\\server.py" in cmd.lower() or "panel/server.py" in cmd.lower():
            wanted["面板"] = (proc.info["pid"], mem)
        elif "supervisor.py" in cmd.lower():
            wanted["看门狗"] = (proc.info["pid"], mem)

    for name, info in wanted.items():
        if info:
            note("OK", "进程", f"{name} PID {info[0]} · {info[1]:.0f} MB")
            continue
        if name == "看门狗":
            # 常驻进程可能被安全软件结束；计划任务每 10 分钟跑一次算活着
            age = 999.0
            heartbeat = os.path.join(ROOT, "tools", "supervisor.heartbeat")
            if os.path.exists(heartbeat):
                age = (time.time() - os.path.getmtime(heartbeat)) / 60
            note("OK" if age < 20 else "BUG", "进程",
                 f"看门狗没有常驻进程，但计划任务每 10 分钟代跑（心跳 {age:.0f} 分钟前）")
            continue
        note("BUG", "进程", f"{name} 没在跑")

    for port in (6185, 6199, 8899, 8100, 8188):
        with socket.socket() as sock:
            sock.settimeout(1.5)
            alive = sock.connect_ex(("127.0.0.1", port)) == 0
        note("OK" if alive else "WARN", "端口", f"{port} {'通' if alive else '不通'}")

    vm = psutil.virtual_memory()
    note("OK" if vm.available > 2 * 1024**3 else "WARN", "内存",
         f"可用 {vm.available / 1024**3:.1f} GB / 共 {vm.total / 1024**3:.1f} GB")


def check_tasks() -> None:
    """Scheduled tasks and next run times."""
    schtasks = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "schtasks.exe")
    try:
        out = subprocess.run([schtasks, "/query", "/fo", "csv", "/nh"],
                             capture_output=True, text=True, timeout=60,
                             encoding="gbk", errors="replace").stdout
    except Exception as exc:  # noqa: BLE001
        note("WARN", "任务", f"查询失败: {exc}")
        return
    for name in ("ChengYin-Growth", "ChengYin-Help", "ChengYin-Archive"):
        line = next((l for l in out.splitlines() if name in l), "")
        if not line:
            note("BUG", "任务", f"{name} 不存在")
            continue
        cells = [c.strip('"') for c in line.split('","')]
        note("OK", "任务", f"{name} 下次 {cells[-2] if len(cells) >= 3 else '?'}")


def check_config_drift() -> None:
    """Config keys that the schema does not know (orphans)."""
    for schema_path in glob.glob(os.path.join(PLUGINS, "*", "_conf_schema.json")):
        plugin = os.path.basename(os.path.dirname(schema_path))
        config_path = os.path.join(CONFIGS, f"{plugin}_config.json")
        if not os.path.exists(config_path):
            continue
        try:
            schema = json.load(open(schema_path, encoding="utf-8"))
            config = json.load(open(config_path, encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(schema, dict) or not isinstance(config, dict):
            continue
        orphans = [
            key for key in config
            if key not in schema and not isinstance(config[key], dict) and key not in {"__template_key"}
        ]
        if orphans:
            note("WARN", "配置", f"{plugin} 有 {len(orphans)} 个键不在 schema: {orphans[:5]}")


def check_panel() -> None:
    """Panel endpoints and the new error detail view."""
    base = "http://127.0.0.1:8899"
    for path in ("/api/health", "/api/state", "/api/system", "/api/detail?kind=errors"):
        start = time.time()
        try:
            with urllib.request.urlopen(base + path, timeout=20) as resp:
                payload = json.loads(resp.read().decode())
            cost = (time.time() - start) * 1000
            extra = ""
            if "kind=errors" in path:
                extra = f"（{payload.get('count')} 组）"
            note("OK" if cost < 3000 else "WARN", "面板", f"{path} {cost:.0f} ms{extra}")
        except Exception as exc:  # noqa: BLE001
            note("BUG", "面板", f"{path} 失败: {str(exc)[:60]}")


def check_runtime_state() -> None:
    """Core runtime data: goals, blacklist, proactive sessions, balance."""
    companions = os.path.join(PLUGIN_DATA, "astrbot_plugin_private_companion", "companions.json")
    try:
        data = json.load(open(companions, encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        note("BUG", "状态", f"companions.json 读不到: {exc}")
        return

    goals = [g for g in (data.get("personal_goals") or []) if isinstance(g, dict)]
    stale = [g.get("title") for g in goals
             if (time.time() - float(g.get("last_progress_at") or 0)) > 4 * 86400]
    note("OK" if not stale else "WARN", "状态",
         f"个人目标 {len(goals)} 个" + (f"，{stale} 超 4 天没动" if stale else "，都在近期动过"))

    users = data.get("users") or {}
    note("OK", "状态", f"私聊档案 {len(users)} 人")

    qq_config = os.path.join(CONFIGS, "astrbot_plugin_chengyin_poke_guard_config.json")
    if os.path.exists(qq_config):
        blacklist_path = os.path.join(PLUGIN_DATA, "astrbot_plugin_chengyin_poke_guard", "state.json")
        if os.path.exists(blacklist_path):
            try:
                state = json.load(open(blacklist_path, encoding="utf-8"))
                black = state.get("blacklist") or {}
                legacy = [k for k in black if ":" in k]
                note("OK" if not legacy else "WARN", "状态",
                     f"黑屋 {len(black)} 人" + (f"，{len(legacy)} 条旧格式" if legacy else ""))
            except Exception:  # noqa: BLE001
                pass

    balance_state = os.path.join(ROOT, "tools", "balance_state.json")
    if os.path.exists(balance_state):
        state = json.load(open(balance_state, encoding="utf-8"))
        age = (time.time() - float(state.get("last_check_at") or 0)) / 3600
        note("OK" if age < 24 else "WARN", "状态",
             f"余额监控 {float(state.get('last_amount') or 0):.2f} 元，{age:.1f} 小时前查过")

    proactive = os.path.join(PLUGIN_DATA, "astrbot_plugin_proactive_chat", "session_data.json")
    if os.path.exists(proactive):
        sessions = json.load(open(proactive, encoding="utf-8"))
        groups = [k for k in sessions if "Group" in k]
        note("OK", "状态", f"主动消息会话 {len(sessions)} 个（群 {len(groups)} 个）")


def check_outbox() -> None:
    """Bot Personal 出站队列：积压说明记忆桥没接上。"""
    path = os.path.join(PLUGIN_DATA, "astrbot_plugin_private_companion", "companions.json")
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    queue = data.get("bot_personal_outbox")
    if not isinstance(queue, list):
        note("OK", "记忆", "没有出站队列")
        return
    pending = [item for item in queue
               if isinstance(item, dict) and str(item.get("state") or "") in {"pending", "retry"}]
    if len(queue) >= 120:
        note("WARN", "记忆", f"出站队列积压 {len(queue)} 条（记忆桥未接上，已限制上限）")
    elif pending:
        note("OK", "记忆", f"出站队列 {len(queue)} 条，待投递 {len(pending)} 条")
    else:
        note("OK", "记忆", f"出站队列 {len(queue)} 条")


def main() -> int:
    """Run every check and print the report."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    check_logs()
    check_data_size()
    check_leftovers()
    check_processes()
    check_tasks()
    check_config_drift()
    check_panel()
    check_runtime_state()
    check_outbox()

    order = {"BUG": 0, "WARN": 1, "OK": 2}
    findings.sort(key=lambda item: (order[item[0]], item[1]))
    counts = collections.Counter(item[0] for item in findings)
    for level, area, message in findings:
        print(f"[{level:4}] {area} · {message}")
    print()
    print(f"结论：BUG {counts['BUG']} 个 / 警告 {counts['WARN']} 个 / 正常 {counts['OK']} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
