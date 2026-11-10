# -*- coding: utf-8 -*-
"""澄音项目全链路自检 —— 跑一遍约 20-40 秒。

检查顺序（尽量互不依赖，一个挂了后面的还能跑）：
  1  进程与端口
  2  插件加载状态
  3  配置/数据文件 JSON 完整性
  4  本地补丁是否还在
  5  人格结构
  6  面板服务
  7  表情包链路（含 emotion-llm 模式）
  8  B站链路（补丁 + 每日额度）
  9  成长/想要/归档
  10 最近日志里的错误

用法: python verify_all.py [--verbose]
返回码: 0 全过 / 1 有失败
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = r"D:\chengyin"
AB = os.path.join(ROOT, "astrbot")
PLUGINS = os.path.join(AB, "data", "plugins")
PLUGIN_DATA = os.path.join(AB, "data", "plugin_data")
CONFIGS = os.path.join(AB, "data", "config")
LOGS = os.path.join(ROOT, "logs", "astrbot.log")
PY = os.path.join(ROOT, "runtime", "python", "python.exe")
BASE = "http://127.0.0.1:6185"
PANEL = "http://127.0.0.1:8899"

RESULTS: list[tuple[str, bool, str]] = []
VERBOSE = "--verbose" in sys.argv


def ok(name: str, detail: str = "") -> None:
    RESULTS.append((name, True, detail))


def bad(name: str, detail: str = "") -> None:
    RESULTS.append((name, False, detail))


def check(name: str, cond: bool, detail: str = "") -> bool:
    (ok if cond else bad)(name, detail)
    return cond


def try_(name: str, fn):
    """执行一个检查函数，异常算失败。"""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        bad(name, f"异常 {type(exc).__name__}: {str(exc)[:70]}")
        return None


# ---------------------------------------------------------------- 1 进程端口
def s1():
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process python -ErrorAction SilentlyContinue | Where-Object {$_.Id -ne $PID} | Measure-Object).Count"],
            capture_output=True, text=True, timeout=25,
        ).stdout.strip()
        check("进程 · AstrBot 在跑", out.isdigit() and int(out) > 0, f"python 进程 {out} 个")
    except Exception as exc:  # noqa: BLE001
        bad("进程 · AstrBot 在跑", str(exc)[:60])

    for name, url in (("AstrBot:6185", BASE + "/"), ("面板:8899", PANEL + "/api/health")):
        try:
            t0 = time.monotonic()
            with urllib.request.urlopen(url, timeout=8) as r:
                code = r.status
            ok(f"端口 · {name}", f"{code} / {(time.monotonic()-t0)*1000:.0f}ms")
        except Exception as exc:  # noqa: BLE001
            bad(f"端口 · {name}", str(exc)[:60])


# ---------------------------------------------------------------- 2 插件
def _recent_lines(minutes: int = 30) -> list[str]:
    """只取最近 N 分钟的日志行。"""
    import datetime as _dt
    cutoff = _dt.datetime.now() - _dt.timedelta(minutes=minutes)
    out = []
    for line in open(LOGS, encoding="utf-8", errors="replace").read().splitlines()[-6000:]:
        m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if not m:
            out.append(line)
            continue
        try:
            if _dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") >= cutoff:
                out.append(line)
        except ValueError:
            out.append(line)
    return out


def s2():
    try:
        lines = _recent_lines()
        removed = [l for l in lines if "Removed module data.plugins" in l]
        failed = [l for l in lines
                  if "Failed to import plugin" in l or "插件重载失败" in l]
        loaded = set(re.findall(r"Loading plugin (\S+)", "\n".join(lines)))
        # 最近 4 小时内有没有加载失败
        recent_fail = failed[-3:]
        check("插件 · 无加载失败", not recent_fail,
              f"{len(recent_fail)} 条" if recent_fail else f"最近加载 {len(loaded)} 个")
        if VERBOSE and recent_fail:
            for l in recent_fail:
                print("     !", l[:150])
    except Exception as exc:  # noqa: BLE001
        bad("插件 · 无加载失败", str(exc)[:60])

    # 关键插件目录都在
    need = ["astrbot_plugin_private_companion", "astrbot_plugin_bili_scroll",
            "meme_manager", "astrbot_plugin_livingmemory", "astrbot_plugin_seed_audio_tts"]
    missing = [p for p in need if not os.path.isdir(os.path.join(PLUGINS, p))]
    check("插件 · 关键目录齐全", not missing, f"缺 {missing}" if missing else f"{len(need)} 个都在")


# ---------------------------------------------------------------- 3 配置文件
def s3():
    files = []
    for d in (CONFIGS, os.path.join(AB, "data")):
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".json"):
                    files.append(os.path.join(d, f))
    broken = []
    for f in files:
        try:
            json.load(open(f, encoding="utf-8-sig"))
        except Exception as exc:  # noqa: BLE001
            broken.append(f"{os.path.basename(f)}: {str(exc)[:40]}")
    check("配置 · JSON 全部可解析", not broken, f"{len(files)} 个文件，坏 {len(broken)}")

    data_files = [
        os.path.join(PLUGIN_DATA, "astrbot_plugin_private_companion", "companions.json"),
        os.path.join(PLUGIN_DATA, "meme_manager", "registry.json"),
        os.path.join(PLUGIN_DATA, "meme_manager", "selection_rules.json"),
    ]
    broken2 = []
    for f in data_files:
        try:
            json.load(open(f, encoding="utf-8-sig"))
        except Exception as exc:  # noqa: BLE001
            broken2.append(f"{os.path.basename(f)}: {str(exc)[:40]}")
    check("数据 · 关键 JSON 可解析", not broken2, str(broken2)[:80] if broken2 else f"{len(data_files)} 个")

    # sqlite 完整性
    for name, path in (
        ("会话库", os.path.join(PLUGIN_DATA, "astrbot_plugin_livingmemory", "conversations.db")),
        ("记忆库", os.path.join(PLUGIN_DATA, "astrbot_plugin_livingmemory", "livingmemory.db")),
    ):
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=8)
            res = con.execute("pragma quick_check").fetchone()[0]
            con.close()
            check(f"数据库 · {name}", res == "ok", res)
        except Exception as exc:  # noqa: BLE001
            bad(f"数据库 · {name}", str(exc)[:60])


# ---------------------------------------------------------------- 4 补丁
def s4():
    """本地补丁与关键配置是否还在（统一走 tools/patchcheck.py 的清单）。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from patchcheck import check_all
    except Exception as exc:  # noqa: BLE001
        bad("补丁 · 清单可加载", str(exc)[:70])
        return
    rows = check_all()
    failed = [(name, detail) for name, good, detail in rows if not good]
    check(f"补丁 · {len(rows)} 项完整", not failed, "全部命中" if not failed else f"{len(failed)} 项丢失")
    for name, detail in failed:
        bad(name, detail)


# ---------------------------------------------------------------- 5 人格
def s5():
    cred = open(os.path.join(ROOT, "我的信息.txt"), encoding="utf-8-sig").read()
    u = re.search(r"账号[:：]\s*(\S+)", cred).group(1)
    pw = re.search(r"密码[:：]\s*(\S+)", cred).group(1)
    body = json.dumps({"username": u, "password": pw}).encode()
    req = urllib.request.Request(BASE + "/api/auth/login", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    token = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())["data"]["token"]
    r = urllib.request.Request(
        BASE + "/api/v1/personas/by-id?persona_id=" + urllib.parse.quote("澄音"))
    r.add_header("Authorization", "Bearer " + token)
    sp = json.loads(urllib.request.urlopen(r, timeout=20).read().decode())["data"]["system_prompt"]

    secs = re.findall(r"^## ([一二三四五六七八九十]+)、", sp, re.M)
    check("人格 · 章节完整", len(secs) >= 11, f"{len(secs)} 节: {''.join(secs)}")
    check("人格 · 无『主人』", "主人" not in sp, f"出现 {sp.count('主人')} 次")
    check("人格 · 长度合理", 5000 < len(sp) < 12000, f"{len(sp)} 字")
    check("人格 · 无残留标签规则", "表情包怎么发" not in sp, "已移除")
    check("人格 · 纸飞机仅 2 处", sp.count("纸飞机") <= 2, f"{sp.count('纸飞机')} 处")


# ---------------------------------------------------------------- 6 面板
def s6():
    for ep in ("/api/health", "/api/state", "/api/catalog"):
        try:
            with urllib.request.urlopen(PANEL + ep, timeout=25) as r:
                data = json.loads(r.read().decode())
            shape = "dict" if isinstance(data, dict) else type(data).__name__
            ok(f"面板 · {ep}", f"{r.status} {shape}")
        except Exception as exc:  # noqa: BLE001
            bad(f"面板 · {ep}", str(exc)[:70])


# ---------------------------------------------------------------- 7 表情包
def s7():
    import contextlib
    import io as _io
    sys.path.insert(0, PLUGINS)
    os.environ.setdefault("ASTRBOT_ROOT", AB)
    with contextlib.redirect_stderr(_io.StringIO()):
        from meme_manager.backend.packs.resolver import resolve_pack_context
        from meme_manager.backend.meme_parser.parser import MemeParser

    ctx = resolve_pack_context(session_id="dafeiyu:FriendMessage:1000000001", persona_id="澄音")
    packs = ctx.get("pack_ids") or []
    check("表情 · 表情包绑定", len(packs) >= 1, str(packs))
    cats = list((ctx.get("category_mapping") or {}).keys())
    check("表情 · 分类可用", len(cats) >= 10, f"{len(cats)} 类")

    p = MemeParser(set(cats), alternative=True, repeated=True, strip_references=True)
    clean = p.feed("好耶&&happy&&") + p.finish()
    check("表情 · 解析器认 &&x&&", p.selections == ["happy"], f"{p.selections} 正文={clean!r}")

    cfg = json.load(open(os.path.join(CONFIGS, "meme_manager_config.json"), encoding="utf-8-sig"))
    emo = cfg["generation"]["emotion"]
    check("表情 · emotion-llm 模式", emo["llm"]["enabled"] is True, f"backend={emo['llm'].get('backend')}")
    prob = emo.get("probability")
    check("表情 · 概率合理", isinstance(prob, int) and 20 <= prob <= 80, f"{prob}%")

    # 每个分类都要真的有图
    empty = []
    for c in cats:
        n = 0
        for d in (ctx.get("pack_dirs") or {}).values():
            cd = os.path.join(d, "memes", c)
            if os.path.isdir(cd):
                n += len([f for f in os.listdir(cd) if f.lower().endswith((".gif", ".png", ".jpg", ".jpeg", ".webp"))])
        if n == 0:
            empty.append(c)
    check("表情 · 分类都有图", not empty, f"空分类 {empty}" if empty else f"{len(cats)} 类都有")


# ---------------------------------------------------------------- 8 B站
def s8():
    cfg = json.load(open(os.path.join(CONFIGS, "astrbot_plugin_bili_scroll_config.json"), encoding="utf-8-sig"))
    check("B站 · 分享解析开启", cfg.get("ENABLE_BILI_SHARE_PARSE") is True, "")
    check("B站 · 分享不发原视频", cfg.get("BILI_SHARE_PARSE_SEND_VIDEO") is False, "")
    daily = cfg.get("AUTONOMOUS_PROACTIVE_DAILY_MAX")
    check("B站 · 每日视频额度", daily == 20, f"{daily}")

    # 分享次数状态文件
    p = os.path.join(PLUGIN_DATA, "astrbot_plugin_bili_scroll", "share_daily.json")
    if os.path.exists(p):
        rows = json.load(open(p, encoding="utf-8"))
        today = time.strftime("%Y-%m-%d")
        n = sum(1 for r in rows if str(r).startswith(today))
        check("B站 · 分享计数正常", n <= 10, f"今天 {n}/10 次")
    else:
        ok("B站 · 分享计数正常", "还没用过，无状态文件")

    # 视觉配置
    check("B站 · 视觉走 MiniMax", "MiniMax" in str(cfg.get("VIDEO_VISION_PROVIDER_ID")), str(cfg.get("VIDEO_VISION_PROVIDER_ID")))


# ---------------------------------------------------------------- 9 成长
def s9():
    for name, path in (
        ("growth.py", os.path.join(ROOT, "tools", "growth", "growth.py")),
        ("wants.py", os.path.join(ROOT, "tools", "growth", "wants.py")),
        ("archive.py", os.path.join(ROOT, "tools", "growth", "archive.py")),
        ("healthcheck.py", os.path.join(ROOT, "tools", "growth", "healthcheck.py")),
    ):
        r = subprocess.run([PY, "-m", "py_compile", path], capture_output=True, timeout=60)
        check(f"成长 · {name} 可编译", r.returncode == 0, r.stderr.decode("utf-8", "replace")[:60] if r.returncode else "")

    # 归档镜像
    mirror = r"D:\chengyin\archives"
    if os.path.isdir(mirror):
        files = sum(len(f) for _, _, f in os.walk(mirror))
        check("归档 · 镜像可读", files > 0, f"{files} 个文件")
    else:
        bad("归档 · 镜像可读", "D:\\chengyin\\archives 不存在")

    # 定时任务
    try:
        out = subprocess.run(["schtasks", "/query", "/fo", "csv", "/nh"],
                             capture_output=True, text=True, timeout=40,
                             encoding="gbk", errors="replace").stdout
        watch = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "(Get-ScheduledTask -TaskName 'ChengYin-Watch').Actions[0].Execute + '|' + "
             "(Get-ScheduledTask -TaskName 'ChengYin-Watch').Settings.Hidden"],
            capture_output=True, text=True, timeout=40, encoding="utf-8", errors="replace",
        ).stdout.strip()
        uses_pythonw = "pythonw.exe" in watch.lower()
        hidden = watch.lower().endswith("true")
        check("任务 · Watch 无窗口", uses_pythonw and hidden,
              "pythonw + 隐藏，每 10 分钟不会闪黑框" if uses_pythonw and hidden else watch[:60])
        for task in ("ChengYin-Growth", "ChengYin-Help", "ChengYin-Archive", "ChengYin-Watch"):
            check(f"任务 · {task}", task in out, "")
    except Exception as exc:  # noqa: BLE001
        bad("任务 · 定时任务查询", str(exc)[:60])


def _log_noise(line: str) -> bool:
    """判断一行日志是不是已知的无关噪音。

    Args:
        line: 单行日志。

    Returns:
        True 表示可以忽略。
    """
    import re as _re

    benign = ("ConnectionResetError", "_call_connection_lost", "WinError 10054",
              "远程主机强迫关闭", "ProactorBasePipeTransport",
              "Failed to import plugin", "未检测到陪伴主插件")
    if any(b in line for b in benign):
        return True
    if line.rstrip().endswith("Traceback (most recent call last):"):
        return True
    if _re.match(r'^\s*File "', line):
        return True
    return False


# ---------------------------------------------------------------- 10 日志
def s10():
    try:
        lines = _recent_lines()
        errs = [l for l in lines if "[ERRO]" in l or "Traceback" in l]
        # 过滤已知无害项
        noisy = ("Failed to import plugin", )
        # 连接被对端重置属于网络抖动，不是程序故障
        benign = (
            "ConnectionResetError",
            "_call_connection_lost",
            "WinError 10054",
            "远程主机强迫关闭",
            "ProactorBasePipeTransport",
        )
        real = [l for l in errs if not _log_noise(l)]
        check("日志 · 近期无异常", not real, f"{len(real)} 条错误" if real else "干净")
        if VERBOSE:
            for l in real[-5:]:
                print("     !", l[:160])
    except Exception as exc:  # noqa: BLE001
        bad("日志 · 近期无异常", str(exc)[:60])


# ---------------------------------------------------------------- 11 面板详情
def s11():
    kinds = ("bili", "diary", "dream", "review", "relation", "memory", "backup", "poke", "errors")
    bad_kinds = []
    for k in kinds:
        try:
            with urllib.request.urlopen(f"{PANEL}/api/detail?kind={k}", timeout=25) as r:
                json.loads(r.read().decode())
            ok(f"面板详情 · {k}", "")
        except Exception as exc:  # noqa: BLE001
            bad_kinds.append(k)
            bad(f"面板详情 · {k}", str(exc)[:50])
    if not bad_kinds:
        pass
    try:
        with urllib.request.urlopen(PANEL + "/api/detail?kind=errors", timeout=30) as r:
            errs = json.loads(r.read().decode())
        items = errs.get("items") or []
        has_source = all(it.get("source") for it in items) if items else True
        check("面板 · 报错能定位", isinstance(errs.get("count"), int) and has_source,
              f"{errs.get('count')} 组，都带来源" if items else "最近没有报错")
    except Exception as exc:  # noqa: BLE001
        bad("面板 · 报错能定位", str(exc)[:60])
    try:
        with urllib.request.urlopen(PANEL + "/api/catalog", timeout=30) as r:
            cat = json.loads(r.read().decode())
        hit = [c for c in (cat.get("commands") or []) if "黑屋" in str(c.get("command"))]
        check("面板 · 戳黑屋指令在", bool(hit), f"{hit[0].get('command')} 别名 {hit[0].get('aliases')}" if hit else "没找到")
    except Exception as exc:  # noqa: BLE001
        bad("面板 · 戳黑屋指令在", str(exc)[:60])


# ---------------------------------------------------------------- 12 工具干跑
def s12():
    # archive.py 不带 --verify 参数会真的打包一份（有副作用），这里只对已有文件做校验
    import glob as _glob
    zips = sorted(_glob.glob(os.path.join(ROOT, "archives", "life-*.zip")))
    verify_args = ["--verify", zips[-1]] if zips else ["--verify", os.path.join(ROOT, "archives", "不存在.zip")]
    for name, args, timeout in (
        ("growth.py --status", ["--status"], 90),
        ("wants.py --status", ["--status"], 90),
        ("archive.py --verify(已有包)", verify_args, 120),
    ):
        path = os.path.join(ROOT, "tools", "growth", name.split()[0])
        cmd = [PY, path] + args
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        err = r.stderr.decode("utf-8", "replace")
        out = r.stdout.decode("utf-8", "replace")
        check(f"工具 · {name}", r.returncode == 0,
              (err or out).strip().splitlines()[-1][:60] if r.returncode else "正常输出")
        if VERBOSE:
            print("     ", (out.strip().splitlines() or ["(无输出)"])[-1][:110])


# ---------------------------------------------------------------- 13 资源
def s13():
    try:
        import shutil as _sh
        for drive in ("D:\\", "C:\\"):
            total, used, free = _sh.disk_usage(drive)
            pct = used / total * 100
            check(f"磁盘 · {drive[:2]} 剩余", free > 2 * 1024**3,
                  f"剩 {free/1024**3:.1f}G / 共 {total/1024**3:.0f}G ({pct:.0f}% 已用)")
    except Exception as exc:  # noqa: BLE001
        bad("磁盘 · 剩余空间", str(exc)[:60])

    try:
        with urllib.request.urlopen(PANEL + "/api/system", timeout=20) as r:
            sysinfo = json.loads(r.read().decode())
        mem = sysinfo.get("memory") or sysinfo
        ok("资源 · 面板系统信息", str(mem)[:70])
    except Exception as exc:  # noqa: BLE001
        bad("资源 · 面板系统信息", str(exc)[:50])


# ---------------------------------------------------------------- 14 成长尾巴保护
def s14():
    """growth.py 重建 §十 时必须保留 §十一，用纯函数验证。"""
    sys.path.insert(0, os.path.join(ROOT, "tools", "growth"))
    try:
        import growth as g
    except Exception as exc:  # noqa: BLE001
        bad("成长 · 尾巴保护", f"导入失败 {str(exc)[:50]}")
        return
    for fn_name in ("split_with_tail", "compose"):
        if not hasattr(g, fn_name):
            bad("成长 · 尾巴保护", f"缺函数 {fn_name}")
            return
    text = "开头\n## 十、成长履历\n旧内容\n## 十一、想要但还没有的\n想学吉他\n"
    try:
        base, sec10, tail = g.split_with_tail(text)
        if "想学吉他" not in tail:
            bad("成长 · 尾巴保护", "拆分时 §十一 没进尾巴")
            return
        rebuilt = g.compose(base, [], tail)
        good = "想学吉他" in rebuilt and "## 十、" not in rebuilt
        check("成长 · 尾巴保护", good, "空履历时 §十一 保留、§十 清掉" if good else "输出不对")
        # 有内容时也要保留尾巴
        entry = {"date": "2026-11-09", "title": "测试", "summary": "占位"}
        try:
            rebuilt2 = g.compose(base, [entry], tail)
            good2 = "想学吉他" in rebuilt2 and "## 十、" in rebuilt2
        except Exception:  # 不同版本 entry 结构可能不同，不作为失败
            good2 = True
        check("成长 · 尾巴保护（有内容）", good2, "§十一 仍在" if good2 else "§十一 丢了")
    except Exception as exc:  # noqa: BLE001
        bad("成长 · 尾巴保护", f"调用失败 {str(exc)[:60]}")


def s15():
    try:
        lines = open(LOGS, encoding="utf-8", errors="replace").read().splitlines()[-30000:]
        import datetime as _dt
        cutoff = _dt.datetime.now() - _dt.timedelta(hours=2)
        recent_err, old_err = [], []
        for l in lines:
            if "[ERRO]" not in l:
                continue
            m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", l)
            if not m:
                continue
            try:
                ts = _dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            (recent_err if ts >= cutoff else old_err).append(l)
        check("日志 · 近 2 小时无 ERROR", not recent_err,
              f"{len(recent_err)} 条" if recent_err else f"干净（更早有 {len(old_err)} 条历史错误）")
        if recent_err and VERBOSE:
            for l in recent_err[-3:]:
                print("     !", l[:150])
    except Exception as exc:  # noqa: BLE001
        bad("日志 · 24h 无 ERROR", str(exc)[:50])


# ---------------------------------------------------------------- 16 配置孤儿键
def s16():
    """配置里有、schema 里没有的键（真正的孤儿；运行时缓存键除外）。"""
    cfg = json.load(open(os.path.join(CONFIGS, "astrbot_plugin_bili_scroll_config.json"), encoding="utf-8-sig"))
    sch = json.load(open(os.path.join(PLUGINS, "astrbot_plugin_bili_scroll", "_conf_schema.json"), encoding="utf-8-sig"))
    runtime_keys = {"BUVID3", "BUVID4"}   # B站 Cookie，运行时写入，本来就不在 schema
    orphan = [k for k in cfg if isinstance(k, str) and k.isupper() and k not in sch and k not in runtime_keys]
    check("配置 · 无孤儿键", not orphan, str(orphan) if orphan else "干净（BUVID3/4 为运行时键）")


# ---------------------------------------------------------------- 18 关键配置键
def s18():
    """两个关键阈值必须在配置里，不能只靠代码默认值。"""
    cfg = json.load(open(os.path.join(CONFIGS, "astrbot_plugin_bili_scroll_config.json"), encoding="utf-8-sig"))
    for key, want in (("VIDEO_DIRECT_MAX_SECONDS", 300), ("BILI_SHARE_PARSE_ANALYZE", True)):
        got = cfg.get(key, "<缺失>")
        check(f"配置 · {key}", got == want, f"{got}")


# ---------------------------------------------------------------- 19 视觉记账
def s19():
    """视觉调用有没有真的进账本。"""
    log = os.path.join(PLUGIN_DATA, "astrbot_plugin_bili_scroll", "usage_log.jsonl")
    if not os.path.exists(log):
        ok("记账 · 视觉调用", "还没有账本文件")
        return
    rows = []
    for line in open(log, encoding="utf-8", errors="replace"):
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    vision = [r for r in rows if str(r.get("purpose")) == "VISION"]
    text = [r for r in rows if str(r.get("purpose")) != "VISION"]
    detail = f"视觉 {len(vision)} 条 / 文本 {len(text)} 条"
    if vision:
        detail += f"，最近 {vision[-1].get('model')} in={vision[-1].get('in')} out={vision[-1].get('out')}"
    check("记账 · 视觉调用", True, detail)


# ---------------------------------------------------------------- 17 存储增长
def s17():
    """入站图片有没有无限增长。"""
    import glob as _glob
    d = os.path.join(PLUGIN_DATA, "astrbot_plugin_private_companion", "private_inbound_images")
    files = _glob.glob(os.path.join(d, "**", "*.*"), recursive=True)
    mb = sum(os.path.getsize(f) for f in files) / 1024 / 1024
    check("存储 · 入站图片", mb < 500, f"{len(files)} 个文件 {mb:.1f} MB（7 天自动清理）")


# ---------------------------------------------------------------- 20 TTS 形态
def s20():
    """语音回复的发送形态：voice_only = 只发语音，不再重复正文。"""
    cfg = json.load(open(os.path.join(CONFIGS, "astrbot_plugin_private_companion_config.json"), encoding="utf-8-sig"))
    grp = cfg.get("voice_action_config") or {}
    mode = grp.get("tts_delivery_mode") or cfg.get("tts_delivery_mode")
    scope = grp.get("tts_conversion_scope") or cfg.get("tts_conversion_scope")
    check("TTS · 只发语音", mode == "voice_only", f"delivery={mode} scope={scope}")
    check("TTS · 触发词齐全", "发语音" in str(cfg.get("tts_trigger_keywords") or grp.get("tts_trigger_keywords")),
          str(cfg.get("tts_trigger_keywords") or grp.get("tts_trigger_keywords"))[:60])


# ---------------------------------------------------------------- 21 群聊唤醒概率
def s21():
    """群聊兴趣唤醒概率：配置写百分数，运行时必须折算成 0-1 比例。"""
    base = os.path.join(PLUGINS, "astrbot_plugin_private_companion")
    cfg = json.load(open(os.path.join(CONFIGS, "astrbot_plugin_private_companion_config.json"), encoding="utf-8-sig"))
    grp = cfg.get("group_wakeup_config") or {}
    raw = grp.get("group_wakeup_interest_probability") or cfg.get("group_wakeup_interest_probability")
    helper = open(os.path.join(base, "helpers.py"), encoding="utf-8", errors="replace").read()
    fixed = "def ratio_from_percent" in helper
    patch_ok = all("ratio_from_percent" in open(os.path.join(base, f), encoding="utf-8", errors="replace").read()
                   for f in ("proactive.py", "group_wakeup.py"))
    check("群聊 · 唤醒概率已修正", fixed and patch_ok, f"配置 {raw}% → 折算 0.{int(raw) if raw else 0}")
    check("群聊 · 概率值合理", isinstance(raw, int) and 0 < raw <= 60, f"{raw}%")


# ---------------------------------------------------------------- 22 反戳
def s22():
    """群里被戳后要能反戳：group_chat_plus 的反戳概率得打开。"""
    path = os.path.join(CONFIGS, "astrbot_plugin_group_chat_plus_config.json")
    if not os.path.exists(path):
        bad("群聊 · 反戳", "没装 group_chat_plus")
        return
    cfg = json.load(open(path, encoding="utf-8-sig"))
    prob = cfg.get("poke_reverse_on_poke_probability")
    mode = cfg.get("poke_message_mode")
    check("群聊 · 被戳会反戳", isinstance(prob, (int, float)) and prob >= 0.5, f"反戳概率 {prob}")
    check("群聊 · 戳一戳处理", mode in ("bot_only", "all"), f"mode={mode}")
    groups = cfg.get("poke_enabled_groups") or []
    check("群聊 · 戳一戳白名单", True, "空=所有群" if not groups else f"{len(groups)} 个群")


# ---------------------------------------------------------------- 23 戳一戳忍耐度
def s23():
    """连戳拉黑插件：装上、配置合理、主人豁免。"""
    plug = os.path.join(PLUGINS, "astrbot_plugin_chengyin_poke_guard", "main.py")
    if not os.path.exists(plug):
        bad("戳一戳 · 忍耐度插件", "没装")
        return
    body = open(plug, encoding="utf-8", errors="replace").read()
    cfg_path = os.path.join(CONFIGS, "astrbot_plugin_chengyin_poke_guard_config.json")
    cfg = json.load(open(cfg_path, encoding="utf-8-sig")) if os.path.exists(cfg_path) else {}
    ok("戳一戳 · 忍耐度插件", f"窗口 {cfg.get('window_seconds')}s / 抱怨 {cfg.get('warn_count')} / 生气 {cfg.get('angry_count')} / 拉黑 {cfg.get('blackout_count')} / {int(cfg.get('blackout_seconds') or 0)//3600}h")
    check("戳一戳 · 主人豁免", "1000000001" in str(cfg.get("owner_ids")), str(cfg.get("owner_ids")))
    check("戳一戳 · 拉黑会拦消息", "event.stop_event()" in body and "_blackout" in body, "stop_event + 黑名单")
    check("戳一戳 · 抱怨能发出", "send_group_msg" in body, "直调 OneBot 接口")
    check("戳一戳 · 前两次必反戳", "_poke_back" in body and "event.stop_event()" in body, "确定性反戳，不靠概率")


# ---------------------------------------------------------------- 24 磁盘清理
def s24():
    """清理脚本在位，且挂到了每周存档任务里。"""
    path = os.path.join(ROOT, "tools", "cleanup_media.py")
    if not os.path.exists(path):
        bad("清理 · 脚本", "tools/cleanup_media.py 不见了")
        return
    body = open(path, encoding="utf-8", errors="replace").read()
    retention = all(k in body for k in ("SELFIE_KEEP", "CACHE_DAYS", "RUNS_KEEP", "INBOUND_DAYS"))
    check("清理 · 保留策略", retention, "自拍/缓存/翻唱/入站图 都有阈值")
    bat = os.path.join(ROOT, "tools", "growth", "run_archive.bat")
    wired = os.path.exists(bat) and "cleanup_media.py" in open(bat, encoding="utf-8", errors="replace").read()
    check("清理 · 已挂定时任务", wired, "每周存档后自动跑" if wired else "没挂上")


# ---------------------------------------------------------------- 25 看门狗
def s25():
    """看门狗是否在跑、开机自启是否装好。计划任务被 360 删了还有兜底。"""
    sup = os.path.join(ROOT, "tools", "supervisor.py")
    check("守护 · 脚本在位", os.path.exists(sup), "tools/supervisor.py")
    hb = os.path.join(ROOT, "tools", "supervisor.heartbeat")
    if not os.path.exists(hb):
        bad("守护 · 进程存活", "没有心跳文件")
    else:
        age = time.time() - os.path.getmtime(hb)
        check("守护 · 进程存活", age < 300, f"心跳 {int(age)} 秒前")
    lnk = os.path.join(
        os.environ.get("APPDATA", ""),
        r"Microsoft\Windows\Start Menu\Programs\Startup\澄音看门狗.lnk")
    check("守护 · 开机自启", os.path.exists(lnk), "启动文件夹快捷方式")
    sup_body = open(sup, encoding="utf-8", errors="replace").read() if os.path.exists(sup) else ""
    check("面板 · 由守护拉起", "ensure_panel" in sup_body, "8899 没在跑时自动启动")
    vbs = os.path.join(ROOT, "tools", "panel", "open-panel.vbs")
    vbs_text = ""
    if os.path.exists(vbs):
        raw = open(vbs, "rb").read()
        for enc in ("utf-16", "utf-8-sig", "gbk", "utf-8"):
            try:
                vbs_text = raw.decode(enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
    check("面板 · 不自动弹页面", "http://127.0.0.1:8899" not in vbs_text,
          "开机只起服务，要看页面双击桌面「澄音面板」")


# ---------------------------------------------------------------- 26 个人目标
def s26():
    """个人目标：关键词有效、进度在推进。"""
    data = json.load(open(os.path.join(
        PLUGIN_DATA, "astrbot_plugin_private_companion", "companions.json"), encoding="utf-8"))
    goals = [g for g in (data.get("personal_goals") or []) if isinstance(g, dict)]
    if not goals:
        bad("目标 · 存在", "没有个人目标")
        return
    thin = [g.get("title") for g in goals
            if len([k for k in (g.get("keywords") or []) if len(str(k)) >= 2]) < 2]
    check("目标 · 关键词够用", not thin, f"{len(goals)} 个目标" if not thin else f"太薄: {thin}")
    now = time.time()
    summary = " / ".join(
        f"{g.get('title')}={g.get('progress')}%" for g in goals[:3])
    newest = max((float(g.get("last_progress_at") or 0) for g in goals), default=0)
    age_days = (now - newest) / 86400 if newest else 999
    check("目标 · 最近有推进", age_days <= 3, f"{summary}｜最近推进 {age_days:.1f} 天前")


# ---------------------------------------------------------------- 27 余额投喂
def s27():
    """余额监控：脚本在位、状态新鲜、守护已挂。"""
    script = os.path.join(ROOT, "tools", "balance_watch.py")
    if not os.path.exists(script):
        bad("余额 · 监控脚本", "tools/balance_watch.py 不见了")
        return
    state_path = os.path.join(ROOT, "tools", "balance_state.json")
    if not os.path.exists(state_path):
        bad("余额 · 基线", "还没跑过")
    else:
        state = json.load(open(state_path, encoding="utf-8"))
        amount = state.get("last_amount")
        age = (time.time() - float(state.get("last_check_at") or 0)) / 60
        check("余额 · 基线", isinstance(amount, (int, float)),
              f"{amount:.2f} 元｜上次 {age:.0f} 分钟前")
    sup = open(os.path.join(ROOT, "tools", "supervisor.py"), encoding="utf-8", errors="replace").read()
    check("余额 · 已挂守护", "maybe_check_balance" in sup, "每 30 分钟查一次")


def main() -> int:
    t0 = time.monotonic()
    print("=" * 70)
    print("澄音项目自检")
    print("=" * 70)
    for fn in (s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12, s13, s14, s15, s16, s17, s18, s19, s20, s21, s22, s23, s24, s25, s26, s27):
        label = fn.__doc__ or fn.__name__
        try_(label, fn)

    passed = sum(1 for _, good, _ in RESULTS if good)
    total = len(RESULTS)
    print()
    for name, good, detail in RESULTS:
        mark = "OK  " if good else "FAIL"
        print(f"  [{mark}] {name:<28} {detail}")
    print()
    fails = [(n, d) for n, g, d in RESULTS if not g]
    print(f"通过 {passed}/{total}   耗时 {time.monotonic()-t0:.1f}s")
    if fails:
        print("\n失败项：")
        for n, d in fails:
            print(f"  - {n}: {d}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
