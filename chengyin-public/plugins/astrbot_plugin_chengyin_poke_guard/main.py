"""澄音·戳一戳忍耐度：反戳、越戳越烦、最后关小黑屋。

Behaviour:
    - The bot's own poke echoes are ignored.
    - Owner ids are always exempt.
    - Poke 1..``warn_count - 1``: she pokes back deterministically.
    - ``warn_count`` / ``angry_count``: she complains and stops the event.
    - ``blackout_count`` and later: the sender is blacklisted for
      ``blackout_seconds``; every poke, @ and chat message from that user is
      dropped silently until the timer expires.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

WARN_LINES = (
    "别戳啦，有点痒…",
    "唔，你手是不是有点闲呀",
    "戳一下就够了嘛",
)
ANGRY_LINES = (
    "说了别戳了！再戳我真生气了",
    "最后警告一次喔，手拿开",
    "你再来一下试试",
)
POKE_LINES = (
    "干嘛呀，戳我一下就跑",
    "在呢在呢，手轻点嘛",
    "戳一下意思意思就好啦",
)
FINAL_LINES = (
    "不理你了。两小时后再来找我。",
    "行，那这两个小时我不认识你。",
    "关小黑屋，两小时，自己反省。",
)


class ChengyinPokeGuard(Star):
    """Handles pokes, escalating annoyance and temporary blacklists."""

    def __init__(self, context: Context, config: dict | None = None) -> None:
        """Initialize the guard and load persisted blacklist entries.

        Args:
            context: AstrBot plugin context.
            config: Plugin configuration mapping.
        """
        super().__init__(context)
        self.config: dict[str, Any] = config or {}
        self.window_seconds = self._int("window_seconds", 300, 10, 3600)
        self.warn_count = self._int("warn_count", 3, 2, 50)
        self.angry_count = max(self.warn_count + 1, self._int("angry_count", 4, 2, 60))
        self.blackout_count = max(self.angry_count + 1, self._int("blackout_count", 5, 2, 80))
        self.blackout_seconds = self._int("blackout_seconds", 7200, 60, 86400)
        owner_raw = self.config.get("owner_ids") or ["1000000001"]
        if isinstance(owner_raw, str):
            owner_raw = [owner_raw]
        self.owner_ids = {str(item).strip() for item in owner_raw if str(item).strip()}
        # {(scope, sender): [poke_ts, ...]}
        self._pokes: dict[str, list[float]] = {}
        # {sender: 上次回戳的 ts}，用于回戳冷却
        self._last_poke_back: dict[str, float] = {}
        # {sender: expire_ts}  —— 黑名单跨群跨私聊生效
        self._blackout: dict[str, float] = {}
        self._state_path = self._resolve_state_path()
        self._load_state()

    # ---------------------------------------------------------------- config
    def _int(self, key: str, default: int, low: int, high: int) -> int:
        """Read an integer config value clamped into range.

        Args:
            key: Configuration key.
            default: Value used when missing or invalid.
            low: Minimum allowed value.
            high: Maximum allowed value.

        Returns:
            The clamped integer value.
        """
        try:
            value = int(self.config.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(low, min(high, value))

    def _resolve_state_path(self) -> Path:
        """Return the JSON path used to persist blacklist entries.

        Returns:
            Path under the plugin data directory, or the plugin folder as a fallback.
        """
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

            base = Path(get_astrbot_plugin_data_path())
        except Exception:  # pragma: no cover - depends on host version
            base = Path(__file__).resolve().parent / "data"
        target = base / "astrbot_plugin_chengyin_poke_guard"
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            target = Path(__file__).resolve().parent
        return target / "state.json"

    def _load_state(self) -> None:
        """Load persisted blacklist entries, dropping expired ones."""
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:
            return
        now = time.time()
        blackout = data.get("blackout") if isinstance(data, dict) else None
        if isinstance(blackout, dict):
            self._blackout = {
                str(key): float(value)
                for key, value in blackout.items()
                if isinstance(value, (int, float))
                and float(value) > now
                and ":" not in str(key)  # 旧版「群:人」格式，新逻辑按人记
            }
            if len(self._blackout) != len(blackout):
                self._save_state()
                logger.info(
                    "[戳一戳忍耐度] 已清理旧格式黑名单记录：%s → %s",
                    len(blackout),
                    len(self._blackout),
                )

    def _save_state(self) -> None:
        """Persist current blacklist entries; failures never break the chat."""
        try:
            self._state_path.write_text(
                json.dumps({"blackout": self._blackout}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[戳一戳忍耐度] 保存状态失败: %s", exc)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _raw_payload(event: AstrMessageEvent) -> Mapping[str, Any]:
        """Return the adapter's raw payload for the event.

        Args:
            event: Incoming message event.

        Returns:
            The raw payload mapping, or an empty mapping when unavailable.
        """
        message_obj = getattr(event, "message_obj", None)
        raw = getattr(message_obj, "raw_message", None)
        return raw if isinstance(raw, Mapping) else {}

    @staticmethod
    def _is_poke(raw: Mapping[str, Any]) -> bool:
        """Return whether the raw payload is a OneBot poke notice.

        Args:
            raw: Adapter raw payload.

        Returns:
            True for ``notice/notify/poke`` payloads.
        """
        return (
            str(raw.get("post_type") or "").strip().lower() == "notice"
            and str(raw.get("notice_type") or "").strip().lower() == "notify"
            and str(raw.get("sub_type") or "").strip().lower() == "poke"
        )

    @staticmethod
    def _action(event: AstrMessageEvent):
        """Return the OneBot ``call_action`` callable bound to this event.

        Args:
            event: Incoming event carrying the platform client.

        Returns:
            The callable, or None when the adapter exposes no API handle.
        """
        client = getattr(event, "bot", None)
        return getattr(getattr(client, "api", None), "call_action", None)

    async def _generate_line(
        self, event: AstrMessageEvent, stage: str, count: int
    ) -> str:
        """Ask the configured chat model for one in-character complaint line.

        Args:
            event: Incoming poke-notice event used to resolve the session model.
            stage: One of ``warn`` / ``angry`` / ``final``.
            count: How many pokes happened inside the window.

        Returns:
            A single short line, or an empty string when generation is disabled
            or fails (caller then falls back to the built-in lines).
        """
        if not bool(self.config.get("enable_llm_lines", True)):
            return ""
        provider_id = str(self.config.get("llm_provider_id") or "").strip()
        if not provider_id:
            try:
                provider = self.context.get_using_provider(
                    umo=getattr(event, "unified_msg_origin", None)
                )
                if provider is not None:
                    provider_id = str(provider.provider_config.get("id") or "").strip()
            except Exception as exc:  # noqa: BLE001
                logger.debug("[戳一戳忍耐度] 取会话模型失败: %s", exc)
        if not provider_id:
            return ""
        mood = {
            "poke": "被人戳了一下，随口应一句，语气轻松带点嫌弃",
            "warn": "有点烦，还愿意理人，只是嘴上嫌弃",
            "angry": "真的生气了，语气冲一点，但还没彻底断",
            "final": "气到不想理他了，扔下一句就拉黑",
        }.get(stage, "有点烦")
        style = str(
            self.config.get("style_prompt")
            or "你是澄音，住在电脑机箱里的蓝发小女仆，爱吃大白饭，说话口语化、短句，"
            "句尾常带「嘛/喔/呀/啦」，不用表情符号，不解释、不列点。"
        ).strip()
        prompt = (
            f"同一个人连续戳了你第 {count} 次（5 分钟内）。你现在{mood}。"
            "只回一句不超过 18 个字的中文口语，符合你的人设，不要引号、不要说明、不要换行。"
        )
        try:
            response = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    system_prompt=style,
                    max_tokens=int(self.config.get("llm_max_tokens", 400) or 400),
                ),
                timeout=float(self.config.get("llm_timeout_seconds", 8) or 8),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[戳一戳忍耐度] 生成台词失败，用固定句: %s", exc)
            return ""
        text = str(getattr(response, "completion_text", "") or "").strip()
        text = text.replace("\n", " ").strip().strip('"“”「」')
        if len(text) > 40:
            text = text[:40]
        logger.info("[戳一戳忍耐度] 生成台词(%s): %s", stage, text)
        return text

    async def _send_group_text(
        self, event: AstrMessageEvent, chat_id: str, text: str
    ) -> None:
        """Send one plain message through the OneBot API.

        ``event.send`` drops payloads on notice events, so the adapter client is
        called directly; failure falls back to the normal result channel.

        Args:
            event: Incoming poke-notice event.
            chat_id: Target group id, or empty for a private chat.
            text: Message text to send.
        """
        action = self._action(event)
        if callable(action):
            try:
                if chat_id:
                    await action("send_group_msg", group_id=int(chat_id), message=text)
                else:
                    await action(
                        "send_private_msg",
                        user_id=int(event.get_sender_id()),
                        message=text,
                    )
                logger.info("[戳一戳忍耐度] 已发送: %s", text)
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("[戳一戳忍耐度] 直发失败，改用事件通道: %s", exc)
        try:
            await event.send(event.plain_result(text))
        except Exception as exc:  # noqa: BLE001
            logger.error("[戳一戳忍耐度] 兜底发送也失败: %s", exc)

    async def _poke_back(
        self, event: AstrMessageEvent, sender: str, chat_id: str
    ) -> None:
        """Poke the given user back through the OneBot API.

        Args:
            event: Incoming poke-notice event.
            sender: QQ id of the user who poked.
            chat_id: Group id, or empty for a private chat.
        """
        action = self._action(event)
        if not callable(action):
            logger.warning("[戳一戳忍耐度] 没有可用的 OneBot 接口，无法反戳")
            return
        payload: dict[str, Any] = {"user_id": int(sender)}
        if chat_id:
            payload["group_id"] = int(chat_id)
        try:
            await action("send_poke", **payload)
            logger.info(
                "[戳一戳忍耐度] 已反戳: group=%s user=%s", chat_id or "私聊", sender
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[戳一戳忍耐度] 反戳失败: %s", exc)

    # ---------------------------------------------------------------- handler
    @filter.event_message_type(filter.EventMessageType.ALL, priority=100000)
    async def guard(self, event: AstrMessageEvent) -> None:
        """Apply poke tolerance rules to pokes and blacklisted users.

        Args:
            event: Incoming message or poke-notice event.
        """
        try:
            raw = self._raw_payload(event)
            sender = str(raw.get("user_id") or event.get_sender_id() or "").strip()
            self_id = str(event.get_self_id() or "").strip()
            if not sender or sender == self_id or sender in self.owner_ids:
                return  # own echo, empty sender, or the owner

            chat_id = str(raw.get("group_id") or event.get_group_id() or "").strip()
            scope = f"group:{chat_id}" if chat_id else "private"
            now = time.time()

            expired = [item for item, until in self._blackout.items() if until <= now]
            for item in expired:
                self._blackout.pop(item, None)
            if expired:
                self._save_state()

            if self._blackout.get(sender, 0.0) > now:
                logger.info(
                    "[戳一戳忍耐度] 小黑屋拦截: scope=%s user=%s", scope, sender
                )
                event.stop_event()
                return

            if not self._is_poke(raw):
                return

            key = f"{scope}:{sender}"
            stamps = [item for item in self._pokes.get(key, []) if now - item <= self.window_seconds]
            stamps.append(now)
            self._pokes[key] = stamps
            count = len(stamps)
            logger.info(
                "[戳一戳忍耐度] %s user=%s 窗口内第 %s 次", scope, sender, count
            )

            if count < self.warn_count:
                cooldown = float(self.config.get("poke_back_cooldown_seconds", 10) or 0)
                last = self._last_poke_back.get(sender, 0.0)
                if cooldown > 0 and now - last < cooldown:
                    logger.info(
                        "[戳一戳忍耐度] 回戳冷却中（%.0f 秒内已回过），本次只计数",
                        cooldown,
                    )
                    event.stop_event()
                    return
                self._last_poke_back[sender] = now
                if random.random() < float(self.config.get("poke_back_probability", 0.7) or 0):
                    await self._poke_back(event, sender, chat_id)
                else:
                    logger.info("[戳一戳忍耐度] 本轮不回戳（概率未命中）")
                if bool(self.config.get("poke_reply_enabled", True)):
                    line = await self._generate_line(event, "poke", count) or random.choice(POKE_LINES)
                    await self._send_group_text(event, chat_id, line)
                event.stop_event()
                return

            if count == self.warn_count:
                line = await self._generate_line(event, "warn", count) or random.choice(WARN_LINES)
                await self._send_group_text(event, chat_id, line)
            elif count == self.angry_count:
                line = await self._generate_line(event, "angry", count) or random.choice(ANGRY_LINES)
                await self._send_group_text(event, chat_id, line)
            else:
                self._blackout[sender] = now + self.blackout_seconds
                self._save_state()
                self._pokes.pop(key, None)
                logger.info(
                    "[戳一戳忍耐度] 关小黑屋: user=%s 时长=%ss",
                    sender,
                    self.blackout_seconds,
                )
                line = await self._generate_line(event, "final", count) or random.choice(FINAL_LINES)
                await self._send_group_text(event, chat_id, line)
            event.stop_event()
        except Exception as exc:  # noqa: BLE001
            logger.error("[戳一戳忍耐度] 处理失败: %s", exc)

    @filter.command("戳黑屋", alias={"黑屋", "查黑屋", "pokehut"})
    async def poke_blackout_command(self, event: AstrMessageEvent):
        """Owner-only helper to inspect or clear the poke blacklist.

        Args:
            event: Command message event.

        Yields:
            One short status line.
        """
        sender = str(event.get_sender_id() or "").strip()
        if sender not in self.owner_ids:
            return
        args = str(getattr(event, "message_str", "") or "").split()
        action = args[1].strip() if len(args) > 1 else ""
        if action in ("清空", "clear", "reset"):
            count = len(self._blackout)
            self._blackout.clear()
            self._pokes.clear()
            self._save_state()
            logger.info("[戳一戳忍耐度] 主人清空了黑名单，原有 %s 人", count)
            yield event.plain_result(f"黑名单清空了（原来 {count} 人），计数也归零了喔")
            return
        if not self._blackout:
            yield event.plain_result("现在没人被关小黑屋")
            return
        lines = []
        for uid, until in list(self._blackout.items())[:5]:
            left = max(0, int(until - time.time()))
            lines.append(f"{uid} 还剩 {left // 60} 分钟")
        yield event.plain_result("小黑屋里：" + "；".join(lines))

    async def terminate(self) -> None:
        """Persist state before the plugin unloads."""
        self._save_state()
