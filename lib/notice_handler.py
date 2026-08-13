from __future__ import annotations

import time
from typing import Any

from astrbot.api import logger

class NoticeHandler:

    def __init__(self, star: Any) -> None:
        self.star = star

    async def dispatch(self, event: Any, raw: dict) -> None:

        ntype = raw.get("notice_type")
        sub = raw.get("sub_type")
        try:
            if ntype == "group_increase":
                await self._on_group_increase(event, raw)
            elif ntype == "group_decrease":
                await self._on_group_decrease(event, raw)
            elif ntype == "group_ban":
                await self._on_group_ban(event, raw)
            elif sub == "poke":
                await self._on_poke(event, raw)
            elif ntype == "friend_add":
                logger.info(f"新好友: {raw.get('user_id')}")
        except Exception as e:
            logger.error(f"notice 事件处理异常 ({ntype}): {e}")

    async def dispatch_request(self, event: Any, raw: dict) -> None:

        try:
            if raw.get("request_type") == "group":
                if raw.get("sub_type") == "invite":
                    await self._on_group_invite(event, raw)
                else:
                    await self._on_group_add_request(event, raw)
        except Exception as e:
            logger.error(f"request 事件处理异常: {e}")

    async def _on_group_increase(self, event: Any, raw: dict) -> None:
        gid = str(raw.get("group_id"))
        uid = str(raw.get("user_id"))
        self_id = str(raw.get("self_id"))
        if uid == self_id:
            return

        if await self.star.group_event_enabled(gid, "blacklist"):
            mod = self.star.modules.get("blacklist")
            if mod and await mod.is_blacklisted(gid, uid):
                await self.star.api.call("set_group_kick", group_id=gid, user_id=uid)
                return

        if await self.star.group_event_enabled(gid, "join_verify"):
            mod = self.star.modules.get("join_review")
            if mod:
                await mod.on_group_increase(event, raw)
                return

        if await self.star.group_event_enabled(gid, "welcome"):
            mod = self.star.modules.get("join_review")
            if mod:
                await mod.send_welcome(event, raw)

    async def _on_group_decrease(self, event: Any, raw: dict) -> None:
        gid = str(raw.get("group_id"))
        uid = str(raw.get("user_id"))
        sub = raw.get("sub_type", "")
        if uid == str(raw.get("self_id")):
            return

        if sub in ("leave", "kick") and await self.star.group_event_enabled(gid, "leave_blacklist"):
            mod = self.star.modules.get("blacklist")
            if mod:
                await mod.add_blacklist(gid, uid)

        if await self.star.group_event_enabled(gid, "leave_notice"):
            mod = self.star.modules.get("join_review")
            if mod:
                await mod.send_leave_notice(event, raw)

    async def _on_group_ban(self, event: Any, raw: dict) -> None:
        gid = str(raw.get("group_id"))
        if not await self.star.group_event_enabled(gid, "ban_notice"):
            return
        duration = raw.get("duration", 0)
        uid = raw.get("user_id")
        operator = raw.get("operator_id")
        if int(duration or 0) > 0:
            text = f"用户 {uid} 被禁言 {duration} 秒（操作者 {operator}）"
        else:
            text = f"用户 {uid} 被解除禁言（操作者 {operator}）"
        await self.star.sender.send_to_group(gid, text)

    async def _on_poke(self, event: Any, raw: dict) -> None:
        if not self.star.config.get("poke_reply_enabled", True):
            return
        gid = str(raw.get("group_id") or "")
        uid = str(raw.get("user_id") or "")
        if not uid:
            return
        key = "BaiXuan/事件系统/戳一戳/记录.json"
        data = await self.star.store.read_json(key, {})
        day = time.strftime("%Y-%m-%d")
        slot = f"{gid}_{uid}" if gid else f"f_{uid}"
        rec = data.get(slot) or {}
        if rec.get("day") != day:
            rec = {"day": day, "count": 0}
        rec["count"] = int(rec.get("count", 0)) + 1
        data[slot] = rec
        await self.star.store.write_json(key, data)
        max_poke = int(self.star.config.get("poke_reply_max", 15))
        if rec["count"] >= max_poke:
            await self.star.api.call("friend_poke", user_id=uid)
            data[slot] = {"day": day, "count": 0}
            await self.star.store.write_json(key, data)

    async def _on_group_add_request(self, event: Any, raw: dict) -> None:

        gid = str(raw.get("group_id"))
        if not await self.star.group_event_enabled(gid, "join_review"):
            return
        mod = self.star.modules.get("join_review")
        if mod:
            await mod.on_group_add_request(event, raw)

    async def _on_group_invite(self, event: Any, raw: dict) -> None:

        accept = await self.star.global_event_enabled("受邀入群同意")
        await self.star.api.call(
            "set_group_add_request",
            flag=raw.get("flag", ""),
            sub_type="invite",
            approve=accept,
            reason="",
        )
