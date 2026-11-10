# -*- coding: utf-8 -*-
"""澄音工程体检：一条命令看现状对不对。

    python healthcheck.py

检查人格八处结构、成长/诉求与状态是否同步、几个关键开关、关系档案数量。
退出码 0 = 全过，1 = 有 Fail。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:6185"
PERSONA_ID = "澄音"
CRED = r"D:\chengyin\我的信息.txt"
COMPANIONS = r"D:\chengyin\astrbot\data\plugin_data\astrbot_plugin_private_companion\companions.json"
PLUGIN_CFG = r"D:\chengyin\astrbot\data\config\astrbot_plugin_private_companion_config.json"
GROWTH = r"D:\chengyin\tools\growth\growth.json"
WANTS = r"D:\chengyin\tools\growth\wants_state.json"
PLUGIN_DIR = r"D:\chengyin\astrbot\data\plugins\astrbot_plugin_private_companion"
BILI_DIR = r"D:\chengyin\astrbot\data\plugins\astrbot_plugin_bili_scroll"

# B 站视频分流补丁的标记（插件更新会冲掉，要能发现）
BILI_PATCHES = (
    'direct_ok = fmt != "none"',
    'VIDEO_DIRECT_MAX_SECONDS',
)

# 我们自己加进插件的补丁，升级会冲掉，所以每次体检都验一遍
TTS_PATCHES = (
    r'r"(用|直接|改成|换成|发|回).{0,4}(文字|文本|打字)"',
    r'r"(文字|文本|打字).{0,4}(就好|就行|吧|回复|回我|发我|说一下)"',
    r'r"(别|不要|不用|甭).{0,6}(念|读)(?!错)"',
)

SECTION10 = "## 十、成长履历"
SECTION11 = "## 十一、想要但还没有的"
REQUIRED = [
    "一、 身份与背景", "二、 性格特征", "三、内在动机", "四、 语言风格",
    "五、 对待不同人", "六、 行为准则", "七、 语感参考示例",
    "## 八、生活锚点", "## 九、几条落地纪律", SECTION10, SECTION11,
]

results: list[tuple[bool, str]] = []


def check(ok: bool, msg: str) -> None:
    results.append((ok, msg))


def api(method: str, path: str, payload=None, token: str | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def login() -> str:
    cache = os.path.join(tempfile.gettempdir(), "dsh_astrbot_token.json")
    try:
        rec = json.load(open(cache, encoding="utf-8"))
        if rec.get("base") == BASE and float(rec.get("exp") or 0) > time.time() + 60:
            return str(rec["token"])
    except Exception:
        pass
    text = open(CRED, encoding="utf-8-sig").read()
    u = re.search(r"账号[:：]\s*(\S+)", text).group(1)
    p = re.search(r"密码[:：]\s*(\S+)", text).group(1)
    token = api("POST", "/api/auth/login", {"username": u, "password": p})["data"]["token"]
    try:
        import base64
        payload = token.split(".")[1] + "=="
        exp = float(json.loads(base64.urlsafe_b64decode(payload)).get("exp") or time.time() + 1800)
    except Exception:
        exp = time.time() + 1800
    try:
        json.dump({"base": BASE, "token": token, "exp": exp}, open(cache, "w", encoding="utf-8"))
    except Exception:
        pass
    return token


def bullets(section: str) -> list[str]:
    return [l for l in section.splitlines() if l.startswith("- ")]


def main() -> int:
    try:
        token = login()
        persona = api("GET", "/api/v1/personas/by-id?persona_id=" + urllib.parse.quote(PERSONA_ID),
                      token=token)["data"]["system_prompt"]
    except Exception as exc:
        print(f"连不上后台（AstrBot 没在跑？）：{exc}")
        return 1

    print(f"人格总长 {len(persona)} 字")
    for head in REQUIRED:
        check(head in persona, f"结构 · {head}")
    check(persona.count("主人") == 0, f"称呼 · 「主人」残留 {persona.count('主人')} 处（应为 0）")
    print(f"称呼 · 「主人」{persona.count('主人')} 处")

    sec10 = persona[persona.index(SECTION10):persona.index(SECTION11)] if SECTION10 in persona and SECTION11 in persona else ""
    sec11 = persona[persona.index(SECTION11):] if SECTION11 in persona else ""
    n10, n11 = len(bullets(sec10)), len(bullets(sec11))

    if os.path.exists(GROWTH):
        entries = json.load(open(GROWTH, encoding="utf-8")).get("entries") or []
        expect10 = min(len(entries), 12)
        check(n10 == expect10, f"第十节 · 人格 {n10} 条 / 成长库 {len(entries)} 条（进 prompt 上限 12）")
    else:
        check(False, "第十节 · 找不到 growth.json")

    if os.path.exists(WANTS):
        items = json.load(open(WANTS, encoding="utf-8")).get("items") or []
        check(n11 == len(items), f"第十一节 · 人格 {n11} 条 / 状态 {len(items)} 条")
    else:
        check(n11 == 0, f"第十一节 · 无状态文件，人格 {n11} 条（应为 0）")

    try:
        cfg = json.load(open(PLUGIN_CFG, encoding="utf-8-sig"))
        tts = cfg["voice_action_config"].get("tts_trigger_probability", cfg.get("tts_trigger_probability"))
        check(tts == 15, f"开关 · TTS 触发概率 {tts}%（设定 15）")
        inj = cfg["skill_growth_config"].get("enable_skill_growth_passive_injection", cfg.get("enable_skill_growth_passive_injection"))
        check(bool(inj), f"开关 · 技能注入 {inj}（应为 True）")
    except Exception as exc:
        check(False, f"开关 · 读配置失败 {exc}")

    # 本地补丁自检：插件升级/重装会覆盖代码文件，补丁掉了这里会立刻报警
    tts_file = os.path.join(PLUGIN_DIR, "tts_enhancement.py")
    if os.path.exists(tts_file):
        body = open(tts_file, encoding="utf-8", errors="replace").read()
        missing = [p for p in TTS_PATCHES if p not in body]
        check(not missing, f"补丁 · 要文字就别念语音的识别（缺 {len(missing)} 条）")
    else:
        check(False, "补丁 · 找不到 tts_enhancement.py")

    # B 站视频：短视频直读 / 长视频抽帧 的分流补丁
    bili_video = os.path.join(BILI_DIR, r"core\video.py")
    if os.path.exists(bili_video):
        vbody = open(bili_video, encoding="utf-8", errors="replace").read()
        missing = [p for p in BILI_PATCHES if p not in vbody]
        check(not missing, f"补丁 · B站视频直读按时长分流（缺 {len(missing)} 条）")
    else:
        check(False, "补丁 · 找不到 bili_scroll 的 video.py")

    share_file = os.path.join(BILI_DIR, r"core\share.py")
    if os.path.exists(share_file):
        sbody = open(share_file, encoding="utf-8", errors="replace").read()
        check("先看一遍再回评价" in sbody, "补丁 · 分享视频看完回评价（不是固定模板）")
        check("_share_daily_bump" in sbody, "补丁 · 分享解析每天上限")
        img_file = os.path.join(PLUGIN_DIR, "private_image.py")
        if os.path.exists(img_file):
            ibody = open(img_file, encoding="utf-8", errors="replace").read()
            check("meme_manager 不在这条合成链上" in ibody, "补丁 · 私聊图片链清残留表情标签")
    else:
        check(False, "补丁 · 找不到 bili_scroll 的 share.py")

    prov = os.path.join(PLUGIN_DIR, r"..\..\cmd_config.json")
    try:
        core = json.load(open(prov, encoding="utf-8-sig"))
        tts_prov = next((p for p in (core.get("provider") or [])
                         if p.get("id") == "澄音语音-豆包"), {})
        prob = tts_prov.get("seed_audio_reply_probability")
        check(prob == 0, f"补丁 · 整条语音概率 {prob}（应为 0，否则文字会被音频吃掉）")
    except Exception as exc:
        check(False, f"补丁 · 读 TTS provider 失败 {exc}")

    try:
        data = json.load(open(COMPANIONS, encoding="utf-8"))
        mp = data.get("worldbook_member_profiles") or {}
        gp = data.get("worldbook_group_profiles") or {}
        check(len(mp) >= 2, f"关系档案 · 成员 {len(mp)} 个 / 群 {len(gp)} 个")
        goals = [g for g in (data.get("personal_goals") or []) if isinstance(g, dict)]
        print(f"个人目标 · {len(goals)} 个")
    except Exception as exc:
        check(False, f"关系档案 · 读取失败 {exc}")

    try:
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, _root)
        from patchcheck import check_all as _check_patches

        _rows = _check_patches()
        _bad = [name for name, good, _ in _rows if not good]
        check(not _bad, f"补丁 · 本地改动 {len(_rows)} 项完整" if not _bad
              else f"补丁 · 丢了 {len(_bad)} 项：" + "、".join(_bad[:4]))
    except Exception as _exc:
        check(False, f"补丁 · 清单加载失败: {str(_exc)[:60]}")

    fails = [m for ok, m in results if not ok]
    print()
    for ok, msg in results:
        print(("  [OK]   " if ok else "  [FAIL] ") + msg)
    print()
    print(f"通过 {len(results) - len(fails)} / {len(results)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
