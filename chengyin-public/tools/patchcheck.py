# -*- coding: utf-8 -*-
"""本地补丁清单与校验。

插件/框架一更新，local 改动就会被覆盖。这个模块把「今天改了什么」集中登记，
provide 一个 check_all() 给 verify_all.py 和 healthcheck.py 共用：
补丁丢了会明确说是哪一项，而不是笼统报错。

用法：
    from patchcheck import check_all
    for name, ok, detail in check_all():
        ...
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

ROOT = r"D:\chengyin"
PLUGINS = os.path.join(ROOT, "astrbot", "data", "plugins")
PLUGIN_DATA = os.path.join(ROOT, "astrbot", "data", "plugin_data")
CONFIGS = os.path.join(ROOT, "astrbot", "data", "config")

# 文件补丁：(名称, 相对 plugins 的路径, 必须出现的片段, 说明)
FILE_PATCHES: list[tuple[str, str, list[str], str]] = [
    (
        "B站 直读时长阈值",
        r"astrbot_plugin_bili_scroll\core\video.py",
        ["VIDEO_DIRECT_MAX_SECONDS", '"source": memory_source'],
        "≤5 分钟直读视频、超过抽帧；记忆里带上来源",
    ),
    (
        "B站 分享视频看完回评价",
        r"astrbot_plugin_bili_scroll\core\share.py",
        ["先看一遍再回评价", "_share_daily_bump"],
        "不再发固定模板卡片；每天最多解析 10 次",
    ),
    (
        "B站 视觉调用记账",
        r"astrbot_plugin_bili_scroll\core\vision.py",
        ["视觉调用也记账"],
        "MiniMax 等视觉调用写进 usage_log，日预算才算得准",
    ),
    (
        "B站 配置 schema 两个键",
        r"astrbot_plugin_bili_scroll\_conf_schema.json",
        ["VIDEO_DIRECT_MAX_SECONDS", "BILI_SHARE_PARSE_ANALYZE"],
        "两个关键阈值能真正写进配置，不再只靠代码默认值",
    ),
    (
        "陪伴 TTS 文字就好",
        r"astrbot_plugin_private_companion\tts_enhancement.py",
        ["用文字"],
        "说「用文字/别发语音」时这一轮不念",
    ),
    (
        "陪伴 GIF 抽帧复用",
        r"astrbot_plugin_private_companion\private_image.py",
        ["_private_image_gif_frame_memo"],
        "同一张动图不再抽两遍帧",
    ),
    (
        "陪伴 图片链清残留标签",
        r"astrbot_plugin_private_companion\private_image.py",
        ["meme_manager 不在这条合成链上"],
        "图片回合的 &&标签&& 不会漏成正文",
    ),
    (
        "陪伴 入站图片 7 天清理",
        r"astrbot_plugin_private_companion\private_image.py",
        ["_prune_private_inbound_images"],
        "私聊图片目录不会无限增长",
    ),
    (
        "余额上涨记伙食",
        r"tools\balance_watch.py",
        ["TARGET_GOAL_TITLE", "personal_goal/update", "MIN_CREDIT"],
        "DeepSeek 余额涨了就算主人改善伙食，推「等熊猫改善伙食」",
    ),
    (
        "主动消息 群聊通配",
        r"astrbot_plugin_proactive_chat\core\services\config_service.py",
        ['"*" in session_list'],
        "session_list 写 * 就能覆盖所有群，不用每加一个群手改",
    ),
    (
        "主动消息 通配展开",
        r"astrbot_plugin_proactive_chat\core\services\scheduler_service.py",
        ["_expanded_session_list", "want_group"],
        "启动时把 * 展开成已知群会话，否则 * 会被当成无效会话",
    ),
    (
        "记忆桥插件",
        r"astrbot_plugin_memory_companion\main.py",
        ["record_bot_personal_archive", "register_emotion_producer", "get_active_bridge"],
        "陪伴插件的 Bot Personal 归档接到 livingmemory，原来只能堆在出站队列",
    ),
    (
        "记忆桥能力探测",
        r"astrbot_plugin_memory_companion\main.py",
        ["probe_bot_personal_memory_capabilities", "ecf1d69406a8445d", "contract_revision"],
        "契约常量对齐，否则陪伴插件判定 capability_probe_missing 不投递",
    ),
    (
        "陪伴 schema 记忆桥开关",
        r"astrbot_plugin_private_companion\_conf_schema.json",
        ["enable_memory_companion_bridge"],
        "开关不在 schema 会被 AstrBot 裁掉，桥默认关闭",
    ),
    (
        "记忆出站队列有界",
        r"astrbot_plugin_private_companion\memory_companion_adapter.py",
        ["队列会无限长", "del queue[:-120]"],
        "记忆桥不可用时不让 bot_personal_outbox 无限增长",
    ),
    (
        "个人目标 中文单字关键词",
        r"astrbot_plugin_private_companion\daily_state.py",
        ["中文单字也算有效关键词", "def usable"],
        "允许「吃」「饭」「躺」这类单字关键词，否则目标永远不动",
    ),
    (
        "陪伴 戳一戳发送",
        r"astrbot_plugin_private_companion\proactive_message.py",
        ["OneBot 的 send_poke"],
        "aiocqhttp 客户端没有 group_poke，改走标准 send_poke",
    ),
    (
        "表情包 提示词注入优先级",
        r"meme_manager\main.py",
        ["on_llm_request(priority=-300000)"],
        "排在人格重写之后，否则表情提示词会被整段覆盖",
    ),
    (
        "戳一戳忍耐度 插件",
        r"astrbot_plugin_chengyin_poke_guard\main.py",
        ["_poke_back", "_generate_line", "send_group_msg", "poke_back_probability", "戳黑屋", "旧格式黑名单", "poke_back_cooldown_seconds", "POKE_LINES"],
        "反戳 + 越戳越烦 + 小黑屋 2 小时（自写插件）",
    ),
    (
        "戳一戳忍耐度 配置 schema",
        r"astrbot_plugin_chengyin_poke_guard\_conf_schema.json",
        ["poke_back_probability", "blackout_seconds", "enable_llm_lines"],
        "插件被重装时配置项还在",
    ),
]

# 配置值断言：(名称, 配置文件, 取值函数说明, 期望)
CONFIG_CHECKS: list[tuple[str, str, tuple[str, ...], Any, str]] = [
    ("B站 直读阈值", "astrbot_plugin_bili_scroll_config.json", ("VIDEO_DIRECT_MAX_SECONDS",), 300, "秒"),
    ("B站 分享分析", "astrbot_plugin_bili_scroll_config.json", ("BILI_SHARE_PARSE_ANALYZE",), True, ""),
    ("B站 分享解析开关", "astrbot_plugin_bili_scroll_config.json", ("ENABLE_BILI_SHARE_PARSE",), True, ""),
    ("B站 分享不发原视频", "astrbot_plugin_bili_scroll_config.json", ("BILI_SHARE_PARSE_SEND_VIDEO",), False, ""),
    ("B站 每日视频额度", "astrbot_plugin_bili_scroll_config.json", ("AUTONOMOUS_PROACTIVE_DAILY_MAX",), 20, "个"),
    ("陪伴 只发语音", "astrbot_plugin_private_companion_config.json",
     ("voice_action_config", "tts_delivery_mode"), "voice_only", ""),
    ("主动消息 群聊开关", "astrbot_plugin_proactive_chat_config.json",
     ("group_settings", "enable"), True, ""),
    ("主动消息 群聊会话", "astrbot_plugin_proactive_chat_config.json",
     ("group_settings", "session_list"), ["*"], "所有群"),
    ("群聊 兴趣唤醒概率", "astrbot_plugin_private_companion_config.json",
     ("group_wakeup_config", "group_wakeup_interest_probability"), 24, "%"),
    ("表情包 emotion-llm", "meme_manager_config.json",
     ("generation", "emotion", "llm", "enabled"), True, ""),
    ("表情包 发送概率", "meme_manager_config.json",
     ("generation", "emotion", "probability"), 50, "%"),
    ("群聊 触发词", "astrbot_plugin_group_chat_plus_config.json",
     ("trigger_keywords",), ["澄音"], ""),
    ("戳一戳 反戳概率", "astrbot_plugin_group_chat_plus_config.json",
     ("poke_reverse_on_poke_probability",), 0.7, ""),
    ("戳一戳 忍耐度-反戳概率", "astrbot_plugin_chengyin_poke_guard_config.json",
     ("poke_back_probability",), 0.7, ""),
    ("戳一戳 忍耐度-拉黑时长", "astrbot_plugin_chengyin_poke_guard_config.json",
     ("blackout_seconds",), 7200, "秒"),
    ("戳一戳 回戳冷却", "astrbot_plugin_chengyin_poke_guard_config.json",
     ("poke_back_cooldown_seconds",), 10, "秒"),
    ("戳一戳 回戳后说话", "astrbot_plugin_chengyin_poke_guard_config.json",
     ("poke_reply_enabled",), True, ""),
]


def _load(config_name: str) -> dict:
    path = os.path.join(CONFIGS, config_name)
    try:
        return json.load(open(path, encoding="utf-8-sig"))
    except Exception:
        return {}


def _dig(data: Any, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def check_all() -> list[tuple[str, bool, str]]:
    """校验全部本地补丁与关键配置。

    Returns:
        列表，元素为 (名称, 是否通过, 明细)。
    """
    results: list[tuple[str, bool, str]] = []

    for name, rel, markers, note in FILE_PATCHES:
        base = ROOT if rel.startswith("tools\\") else PLUGINS
        path = os.path.join(base, rel)
        if not os.path.exists(path):
            results.append((f"补丁 · {name}", False, f"文件没了：{rel}"))
            continue
        body = open(path, encoding="utf-8", errors="replace").read()
        missing = [marker for marker in markers if marker not in body]
        if missing:
            results.append((f"补丁 · {name}", False, f"丢了 {len(missing)} 处：{missing}"))
        else:
            results.append((f"补丁 · {name}", True, note))

    for name, config_name, keys, expected, unit in CONFIG_CHECKS:
        cfg = _load(config_name)
        if not cfg:
            results.append((f"配置 · {name}", False, f"读不到 {config_name}"))
            continue
        actual = _dig(cfg, keys)
        if actual == expected:
            results.append((f"配置 · {name}", True, f"{actual}{unit}"))
        else:
            results.append((f"配置 · {name}", False, f"现在是 {actual}，应为 {expected}{unit}"))

    return results


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = check_all()
    bad = [row for row in rows if not row[1]]
    for name, good, detail in rows:
        print(f"  [{'OK  ' if good else 'FAIL'}] {name:<26} {detail}")
    print(f"\n通过 {len(rows) - len(bad)}/{len(rows)}")
    raise SystemExit(0 if not bad else 1)
