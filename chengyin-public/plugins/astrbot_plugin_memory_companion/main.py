"""记忆桥：把陪伴插件的 Bot Personal 归档接到 livingmemory。

为什么需要它：`astrbot_plugin_private_companion` 只认特定名字的记忆插件
（astrbot_plugin_memory_companion / remember_you 等）。本项目装的是
`astrbot_plugin_livingmemory`，于是桥一直找不到，出站队列只能堆积。

这个插件只做适配：
    * 对外暴露 get_active_bridge()，被陪伴插件识别为记忆桥
    * record_bot_personal_archive() 把日程/日记写进 livingmemory
    * register_emotion_producer() 返回一个占位凭据（陪伴插件要求非空）
"""

from __future__ import annotations

import asyncio
from typing import Any

from astrbot.api import logger
from astrbot.api.star import Context, Star

# 陪伴插件用「能力探测」决定要不要认这座桥；这里逐字对齐它的契约常量
# （来源：astrbot_plugin_private_companion/bot_personal_contract.py）
CONTRACT_FINGERPRINT = "ecf1d69406a8445d"
CONTRACT_REVISION = 3
CAPABILITY_SCHEMA_VERSION = "1.3"
PAYLOAD_SCHEMA_VERSION = "1.0"
CANONICAL_SCHEMA_VERSION = 3
MEMORY_DOMAIN = "bot_self_schedule"
WINDOW_SLUGS = ("late_night", "morning", "noon", "afternoon", "evening")
MEMORY_TYPES = (
    "bot_schedule_plan", "bot_observed_activity", "bot_schedule_reconciliation",
    "bot_window_snapshot", "bot_daily_diary", "bot_creative_work", "bot_media_memory",
    "bot_subjective_memory", "bot_shared_activity", "bot_detail_fragment",
    "bot_calendar_event", "bot_proactive_message",
)

_ACTIVE_BRIDGE: "LivingMemoryBridge | None" = None


def get_active_bridge() -> "LivingMemoryBridge | None":
    """Return the live bridge instance (module-level lookup used by companions).

    Returns:
        The bridge, or None before the plugin is loaded.
    """
    return _ACTIVE_BRIDGE


def get_memory_companion_bridge() -> "LivingMemoryBridge | None":
    """Alias kept for callers that use the alternate getter name."""
    return _ACTIVE_BRIDGE


class LivingMemoryBridge:
    """Minimal MemoryCompanion-compatible bridge backed by livingmemory."""

    def __init__(self, context: Context) -> None:
        self.context = context
        self._engine: Any | None = None

    # ------------------------------------------------------------ 能力探测
    def probe_bot_personal_memory_capabilities(self) -> dict[str, Any]:
        """Declare the archive contract this bridge implements.

        The companion refuses a bridge whose probe does not match its own
        contract constants, so these values are copied verbatim from
        ``bot_personal_contract.py``.

        Returns:
            Capability dict understood by the companion.
        """
        return {
            "available": True,
            "contract_fingerprint": CONTRACT_FINGERPRINT,
            "contract_revision": CONTRACT_REVISION,
            "capability_schema_version": CAPABILITY_SCHEMA_VERSION,
            "payload_schema_version": PAYLOAD_SCHEMA_VERSION,
            "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
            "memory_domain": MEMORY_DOMAIN,
            "windows": list(WINDOW_SLUGS),
            "memory_types": list(MEMORY_TYPES),
        }

    # ------------------------------------------------------------ 生命周期
    def bridge_lifecycle_status(self) -> dict[str, Any]:
        """Report bridge health to the companion plugin.

        Returns:
            Dict with an ``active`` flag.
        """
        # 这里只回答"桥在不在"。engine 在真正写入时再找：
        # 若在此返回 False，陪伴插件会判定 bridge_inactive 并永不投递。
        return {"active": True}

    def register_emotion_producer(self, producer: Any) -> dict[str, str]:
        """Accept an emotion producer registration.

        livingmemory has no emotion pipeline, so this only satisfies the
        capability probe; the token is opaque to the caller.

        Args:
            producer: The producer object offered by the companion.

        Returns:
            A non-empty capability token.
        """
        return {"bridge": "livingmemory", "producer": type(producer).__name__}

    # ------------------------------------------------------------ 记忆写入
    async def record_bot_personal_archive(
        self,
        envelope: dict[str, Any],
        *,
        producer_capability: Any = None,
    ) -> dict[str, Any]:
        """Write one companion archive envelope into livingmemory.

        Args:
            envelope: Canonical record produced by the companion.
            producer_capability: Opaque token from register_emotion_producer.

        Returns:
            Result dict understood by the companion's outbox.
        """
        if not isinstance(envelope, dict):
            return {"ok": False, "state": "retry", "error_code": "invalid_envelope"}

        engine = self._engine_ref()
        if engine is None:
            return {"ok": False, "state": "retry", "error_code": "memory_engine_missing"}

        content = self._render(envelope)
        if not content:
            return {"ok": False, "state": "local_only", "error_code": "empty_content"}

        payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
        metadata = {
            "source": "private_companion",
            "memory_type": str(envelope.get("memory_type") or ""),
            "memory_domain": str(envelope.get("memory_domain") or ""),
            "idempotency_key": str(envelope.get("idempotency_key") or ""),
            "occurred_at": str(envelope.get("occurred_at") or ""),
            "date": str(envelope.get("date") or payload.get("date") or ""),
            "window": str(envelope.get("window") or payload.get("window") or ""),
            "subject": str(envelope.get("subject") or "bot_self"),
            "certainty": float(envelope.get("certainty") or 0.6),
            "evidence_level": str(envelope.get("evidence_level") or "L0"),
            "status": str(envelope.get("status") or "planned"),
            "bridge_record_id": str(envelope.get("record_id") or ""),
        }
        importance = 0.55 if metadata["memory_type"].startswith("bot_daily") else 0.5
        try:
            doc_id = await engine.add_memory(
                content=content,
                session_id="bot_self",
                persona_id=str(envelope.get("persona_id") or ""),
                importance=importance,
                metadata=metadata,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[记忆桥] 写入失败: %s", str(exc)[:160])
            return {
                "ok": False,
                "state": "retry",
                "error_code": type(exc).__name__,
            }
        logger.info(
            "[记忆桥] 已归档 %s → doc %s",
            metadata["memory_type"] or "record",
            doc_id,
        )
        return {
            "ok": True,
            "state": "sent",
            "record_id": str(doc_id),
            "version": int(envelope.get("version") or 1),
            "deduplicated": False,
        }

    async def drain_companion_outbox(self) -> int:
        """Ask the companion plugin to flush its own archive outbox.

        The companion normally flushes inside its agenda maintenance tick, but
        that tick can be delayed or blocked. Calling its own flush method keeps
        the delivery guarantee without touching its in-memory data ourselves.

        Returns:
            Number of delivered records reported by the companion.
        """
        companion = self._companion_instance()
        flush = getattr(companion, "_memory_companion_flush_bot_personal_outbox", None)
        logger.info(
            "[记忆桥] 巡检：companion=%s flush=%s",
            "有" if companion is not None else "无",
            "有" if callable(flush) else "无",
        )
        if not callable(flush):
            return 0
        try:
            results = flush(limit=24)
            if asyncio.iscoroutine(results) or hasattr(results, "__await__"):
                results = await results
        except Exception as exc:  # noqa: BLE001
            logger.warning("[记忆桥] 触发投递失败: %s", str(exc)[:160])
            return 0
        delivered = len([item for item in (results or []) if isinstance(item, dict) and item.get("ok")])
        if delivered:
            logger.info("[记忆桥] 本轮投递 %s 条", delivered)
        return delivered

    def _companion_instance(self) -> Any | None:
        """Locate the private companion plugin instance.

        Returns:
            The plugin instance, or None when it is not loaded.
        """
        try:
            stars = list(self.context.get_all_stars() or [])
        except Exception:  # noqa: BLE001
            stars = []
        for meta in stars:
            name = str(
                getattr(meta, "name", "") or getattr(meta, "root_dir_name", "") or ""
            ).lower()
            if "private_companion" not in name:
                continue
            instance = getattr(meta, "star_cls", None)
            if instance is not None:
                return instance
        return None

    # ------------------------------------------------------------ 内部工具
    def _engine_ref(self) -> Any | None:
        """Locate the livingmemory engine through AstrBot's star registry.

        Returns:
            The memory engine instance, or None when livingmemory is absent.
        """
        if self._engine is not None:
            return self._engine

        def engine_of(instance: Any) -> Any | None:
            """Pull the memory engine out of a livingmemory plugin instance."""
            initializer = getattr(instance, "initializer", None)
            return getattr(initializer, "memory_engine", None)

        getter = getattr(self.context, "get_registered_star", None)
        if callable(getter):
            try:
                meta = getter("astrbot_plugin_livingmemory")
            except Exception:  # noqa: BLE001
                meta = None
            engine = engine_of(getattr(meta, "star_cls", None))
            if engine is not None:
                self._engine = engine
                return engine
        try:
            stars = list(self.context.get_all_stars() or [])
        except Exception:  # noqa: BLE001
            stars = []
        for meta in stars:
            instance = getattr(meta, "star_cls", None)
            name = " ".join(
                str(getattr(meta, field, "") or "")
                for field in ("name", "root_dir_name", "module_path")
            ).lower()
            if "livingmemory" not in name and engine_of(instance) is None:
                continue
            engine = engine_of(instance)
            if engine is not None:
                self._engine = engine
                return engine
        return None

    @staticmethod
    def _render(envelope: dict[str, Any]) -> str:
        """Turn an envelope into plain text for long-term memory.

        Args:
            envelope: Companion archive record.

        Returns:
            A readable multi-line string.
        """
        payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
        date_text = str(envelope.get("date") or payload.get("date") or "").strip()
        summary = str(payload.get("summary") or "").strip()
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        body = "\n".join(f"- {str(item).strip()[:240]}" for item in items if str(item).strip())
        head = " ".join(part for part in (date_text, summary) if part)
        if not head and not body:
            return ""
        memory_type = str(envelope.get("memory_type") or "").strip()
        prefix = {"bot_schedule_plan": "那天的日程", "bot_daily_diary": "那天的日记"}.get(
            memory_type, "那天的记录"
        )
        return "\n".join(part for part in (f"{prefix}：{head}", body) if part)[:3000]


class MemoryCompanionBridgePlugin(Star):
    """Registers the bridge so the companion plugin can find it."""

    def __init__(self, context: Context, config: Any = None) -> None:
        super().__init__(context)
        global _ACTIVE_BRIDGE
        self.bridge = LivingMemoryBridge(context)
        _ACTIVE_BRIDGE = self.bridge
        self._drain_task: asyncio.Task | None = None
        engine = self.bridge._engine_ref()
        logger.info(
            "[记忆桥] 已注册，等待陪伴插件投递归档（memory_engine=%s）",
            "已找到" if engine is not None else "暂未找到",
        )
        self._drain_task = asyncio.create_task(self._drain_loop())

    async def _drain_loop(self) -> None:
        """Flush the companion outbox every few minutes."""
        await asyncio.sleep(10)
        while True:
            try:
                await self.bridge.drain_companion_outbox()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("[记忆桥] 定时投递异常: %s", str(exc)[:160])
            await asyncio.sleep(300)

    def get_active_bridge(self) -> LivingMemoryBridge:
        """Return this plugin's bridge instance.

        Returns:
            The bridge object.
        """
        return self.bridge

    async def terminate(self) -> None:
        """Stop the drain loop and clear the module-level bridge."""
        global _ACTIVE_BRIDGE
        if self._drain_task is not None:
            self._drain_task.cancel()
        _ACTIVE_BRIDGE = None
