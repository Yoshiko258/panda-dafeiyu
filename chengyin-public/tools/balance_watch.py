# -*- coding: utf-8 -*-
"""余额上涨 = 主人改善伙食。

为什么单独写一个脚本：插件自带的「余额感知」有三道闸（分组配置、被动任务子集、
12 小时退避），实测一直不触发。这里用最小路径做同一件事：

    1. 定时问 DeepSeek 余额接口
    2. 和上次记录的金额比，涨了 ≥ 阈值就调插件自己的 /personal_goal/update 接口
    3. 把「等熊猫改善伙食」推进一格，并留一条证据

状态存 tools/balance_state.json，日志写 logs/balance_watch.log。
由 tools/supervisor.py 每 30 分钟调一次（--once 模式）。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

ROOT = r"D:\chengyin"
STATE = os.path.join(ROOT, "tools", "balance_state.json")
LOG = os.path.join(ROOT, "logs", "balance_watch.log")
COMPANIONS = os.path.join(
    ROOT, "astrbot", "data", "plugin_data",
    "astrbot_plugin_private_companion", "companions.json")
CMD_CONFIG = os.path.join(ROOT, "astrbot", "data", "cmd_config.json")
CREDS = os.path.join(ROOT, "我的信息.txt")
BASE = "http://127.0.0.1:6185"
PLUGIN = "astrbot_plugin_private_companion"

MIN_CREDIT = 1.0      # 涨这么多才算投喂（元）
GOAL_TERMS = ("伙食", "投喂", "加餐")   # 标题里带这些词就算伙食目标
TARGET_GOAL_TITLE = "等熊猫改善伙食"   # 优先精确匹配这个目标


def log(message: str) -> None:
    """Append one timestamped line to the watcher log.

    Args:
        message: Text to record.
    """
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except OSError:
        pass


def load_state() -> dict:
    """Load the previous balance snapshot.

    Returns:
        Dict with at least ``last_amount`` (float) when known.
    """
    try:
        with open(STATE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    """Persist the current balance snapshot.

    Args:
        state: Dict to write.
    """
    try:
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False)
    except OSError as exc:
        log(f"状态保存失败: {exc}")


def deepseek_key() -> str:
    """Read the DeepSeek API key from the AstrBot provider sources.

    Returns:
        The key string, or empty when unavailable.
    """
    try:
        with open(CMD_CONFIG, encoding="utf-8-sig") as fh:
            config = json.load(fh)
    except (OSError, ValueError):
        return ""
    for source in config.get("provider_sources") or []:
        if not isinstance(source, dict):
            continue
        if str(source.get("id") or "") != "deepseek_source":
            continue
        raw = source.get("key")
        if isinstance(raw, list):
            return next((str(item).strip() for item in raw if str(item or "").strip()), "")
        return str(raw or "").strip()
    return ""


def fetch_balance(key: str) -> float | None:
    """Query the DeepSeek balance endpoint.

    Args:
        key: API key.

    Returns:
        Remaining balance in CNY, or None on failure.
    """
    request = urllib.request.Request("https://api.deepseek.com/user/balance")
    request.add_header("Authorization", f"Bearer {key}")
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            payload = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001
        log(f"余额查询失败: {str(exc)[:120]}")
        return None
    infos = payload.get("balance_infos") if isinstance(payload, dict) else None
    if not isinstance(infos, list) or not infos:
        log("余额返回格式异常")
        return None
    try:
        return float(infos[0].get("total_balance"))
    except (TypeError, ValueError):
        log("余额字段解析失败")
        return None


def login_token() -> str:
    """Log in to the AstrBot dashboard and return a bearer token.

    Returns:
        Token string, or empty when login fails.
    """
    try:
        with open(CREDS, encoding="utf-8-sig") as fh:
            text = fh.read()
    except OSError:
        return ""
    import re

    user = re.search(r"账号[:：]\s*(\S+)", text)
    password = re.search(r"密码[:：]\s*(\S+)", text)
    if not user or not password:
        return ""
    body = json.dumps({"username": user.group(1), "password": password.group(1)}).encode()
    request = urllib.request.Request(BASE + "/api/auth/login", data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            payload = json.loads(resp.read().decode())
        return str((payload.get("data") or {}).get("token") or "")
    except Exception as exc:  # noqa: BLE001
        log(f"登录后台失败: {str(exc)[:120]}")
        return ""


def credit_goal(token: str, increase: float, new_amount: float) -> bool:
    """Advance the food goal through the plugin's own page API.

    Args:
        token: Dashboard bearer token.
        increase: Balance increase in CNY.
        new_amount: Current balance.

    Returns:
        True when a goal was updated.
    """
    try:
        with open(COMPANIONS, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return False

    goal = None
    active = [
        item for item in (data.get("personal_goals") or [])
        if isinstance(item, dict)
        and str(item.get("status") or "active").strip().lower() == "active"
    ]
    # 1) 标题完全一致
    goal = next((it for it in active if str(it.get("title") or "") == TARGET_GOAL_TITLE), None)
    # 2) 标题含「伙食/投喂/加餐」
    if goal is None:
        goal = next(
            (it for it in active
             if any(term in str(it.get("title") or "") for term in GOAL_TERMS)),
            None,
        )
    # 3) 最后才退回关键词匹配
    if goal is None:
        goal = next(
            (it for it in active
             if any(term in " ".join(str(k) for k in (it.get("keywords") or []))
                    for term in GOAL_TERMS)),
            None,
        )
    if not goal:
        log("没找到伙食类目标，跳过")
        return False

    old = max(0, min(100, int(goal.get("progress") or 0)))
    step = max(1, min(50, int(goal.get("auto_step") or 5)))
    new = min(100, old + step)
    if new <= old:
        log(f"目标「{goal.get('title')}」已经 {old}%，满了")
        return False

    payload = {
        "id": goal.get("id"),
        "title": goal.get("title"),
        "progress": new,
        "note": f"余额 +{increase:.2f} 元（主人改善伙食）",
    }
    url = f"{BASE}/api/v1/plugins/extensions/{PLUGIN}/page/personal_goal/update"
    body = json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            result = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001
        log(f"更新目标失败: {str(exc)[:140]}")
        return False

    if str(result.get("status") or "") == "error":
        log(f"插件拒绝了更新: {result.get('message')}")
        return False
    log(
        f"余额 {increase:+.2f} 元（现 {new_amount:.2f}）→ "
        f"「{goal.get('title')}」{old}% → {new}%"
    )
    return True


def main() -> int:
    """Run one balance check cycle.

    Returns:
        Process exit code.
    """
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    state = load_state()
    key = deepseek_key()
    if not key:
        log("没有 DeepSeek key，跳过")
        return 1
    amount = fetch_balance(key)
    if amount is None:
        return 1

    previous = state.get("last_amount")
    state["last_amount"] = amount
    state["last_check_at"] = time.time()
    if isinstance(previous, (int, float)):
        increase = amount - float(previous)
        state["last_increase"] = round(increase, 2)
        if increase >= MIN_CREDIT:
            token = login_token()
            if token:
                credit_goal(token, increase, amount)
            else:
                log("没有登录凭据，无法更新目标")
        else:
            log(f"余额 {amount:.2f}（变化 {increase:+.2f}，未达 {MIN_CREDIT} 元）")
    else:
        log(f"记录初始余额 {amount:.2f}")
    save_state(state)
    print(f"余额 {amount:.2f} 元")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
