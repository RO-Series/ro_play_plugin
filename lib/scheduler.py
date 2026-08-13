from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

from astrbot.api import logger

HOURS = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22]

class Scheduler:

    def __init__(self, star: Any) -> None:
        self.star = star
        self._running = True

    def stop(self) -> None:
        self._running = False

    async def run_hourly(self) -> None:

        while self._running:
            now = datetime.now()
            await asyncio.sleep((3600 - now.minute * 60 - now.second) % 3600)
            try:
                await self.hourly_tick()
            except Exception as e:
                logger.error(f"整点任务异常: {e}")

    async def run_broadcast(self) -> None:

        while self._running:
            try:
                await self.broadcast_tick()
            except Exception as e:
                logger.warning(f"广播 tick 异常: {e}")
            await asyncio.sleep(1)

    async def hourly_tick(self) -> None:
        hour = datetime.now().hour
        tasks = [
            self._group_firekeep(),
            self._friend_firekeep(),
        ]
        if 7 <= hour <= 23:
            tasks.append(self._hourly_chime())
        if self.star.config.get("backup_enabled", False):
            tasks.append(self._auto_backup())

        tasks.append(self._group_sign())
        tasks.append(self._auto_like())
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _group_firekeep(self) -> None:

        try:
            groups = await self.star.api.get_group_list()
            today = time.strftime("%Y-%m-%d")
            for g in groups:
                gid = str(g.get("group_id"))
                if not await self.star.group_event_enabled(gid, "group_fire"):
                    continue
                if await self.star.store.has_key("BaiXuan/事件系统/状态数据/群聊/{}.json".format(today), gid):
                    continue
                text = await self.star.store.read_text("BaiXuan/扩展功能/续火功能/续火内容/文本.txt", "愿君安心")
                await self.star.sender.send_to_group(gid, text)
                await self.star.store.write_key(
                    "BaiXuan/事件系统/状态数据/群聊/{}.json".format(today), gid, True
                )
        except Exception as e:
            logger.error(f"群聊续火失败: {e}")

    async def _friend_firekeep(self) -> None:

        try:
            if not await self.star.global_event_enabled("好友续火"):
                return
            today = time.strftime("%Y-%m-%d")
            switch = await self.star.store.read_json("BaiXuan/扩展功能/续火功能/状态数据/好友/开关.json", {})
            for uid, enabled in (switch or {}).items():
                if not enabled:
                    continue
                if await self.star.store.has_key(
                    "BaiXuan/事件系统/状态数据/好友/{}.json".format(today), uid
                ):
                    continue
                text = await self.star.store.read_text(
                    "BaiXuan/扩展功能/续火功能/续火内容/文本.txt", "愿君安心"
                )
                await self.star.sender.send_to_private(uid, text)
                await self.star.store.write_key(
                    "BaiXuan/事件系统/状态数据/好友/{}.json".format(today), uid, True
                )
        except Exception as e:
            logger.error(f"好友续火失败: {e}")

    async def _hourly_chime(self) -> None:

        try:
            hour = datetime.now().hour
            groups = await self.star.api.get_group_list()
            text = await self.star.store.read_text("BaiXuan/扩展功能/整点报时/文案.txt", "")
            if not text:
                text = f"现在是北京时间 {hour:02d}:00"
            for g in groups:
                gid = str(g.get("group_id"))
                if await self.star.group_event_enabled(gid, "hourly_chime"):
                    await self.star.sender.send_to_group(gid, text)
        except Exception as e:
            logger.error(f"整点报时失败: {e}")

    async def _group_sign(self) -> None:

        try:
            groups = await self.star.api.get_group_list()
            today = time.strftime("%Y-%m-%d")
            for g in groups:
                gid = str(g.get("group_id"))
                if not await self.star.group_event_enabled(gid, "group_sign"):
                    continue
                if await self.star.store.has_key(
                    "BaiXuan/扩展功能/全群打卡/打卡状态/{}.json".format(today), gid
                ):
                    continue
                await self.star.api.call("send_group_sign", group_id=gid)
                await self.star.store.write_key(
                    "BaiXuan/扩展功能/全群打卡/打卡状态/{}.json".format(today), gid, True
                )
        except Exception as e:
            logger.error(f"全群打卡失败: {e}")

    async def _auto_like(self) -> None:

        try:
            if not self.star.config.get("auto_like_enabled", False):
                return
            today = time.strftime("%Y-%m-%d")
            mode = await self.star.store.read_key("BaiXuan/扩展功能/自动点赞/模式.json", "mode", "all")
            times = int(self.star.config.get("auto_like_times", 20))
            targets: list = []
            if mode == "all":
                friends = await self.star.api.get_friend_list()
                targets = [f.get("user_id") for f in friends]
            else:
                targets = list(
                    (await self.star.store.read_json("BaiXuan/扩展功能/自动点赞/名单.json", {}) or {}).keys()
                )
            for uid in targets:
                if await self.star.store.has_key(
                    "BaiXuan/扩展功能/自动点赞/点赞记录/{}.json".format(today), str(uid)
                ):
                    continue
                await self.star.api.call("send_like", user_id=uid, times=times)
                await self.star.store.write_key(
                    "BaiXuan/扩展功能/自动点赞/点赞记录/{}.json".format(today), str(uid), True
                )
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"自动点赞失败: {e}")

    async def _auto_backup(self) -> None:

        try:
            hour = datetime.now().hour
            times = [int(x.strip()) for x in str(self.star.config.get("backup_time", "12")).split(",") if x.strip().isdigit()]
            target_qq = str(self.star.config.get("backup_qq", ""))
            if not target_qq or hour not in times:
                return
            import io
            import zipfile

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in self.star.data_path.rglob("*"):
                    if p.is_file() and ".tmp" not in p.name:
                        zf.write(p, p.relative_to(self.star.data_path))
            buf.seek(0)
            await self.star.api.call("upload_private_file", user_id=target_qq, name="ro_play_backup.zip", data=base64_encode(buf.getvalue()))
        except Exception as e:
            logger.error(f"自动备份失败: {e}")

    async def broadcast_tick(self) -> None:

        conf = await self.star.store.read_json(
            "BaiXuan/扩展功能/群发系统/定时CQ.json",
            {"enabled": False, "mode": "interval", "intervalSec": 3600, "atAll": False, "calendarRules": []},
        )
        if not conf.get("enabled"):
            return
        now = time.time()
        last_key = "BaiXuan/扩展功能/群发系统/上次触发.json"
        last = await self.star.store.read_key(last_key, "ts", 0)
        fire = False
        mode = conf.get("mode", "interval")
        if mode == "interval":
            sec = max(int(conf.get("intervalSec", 3600)), 10)
            if now - float(last or 0) >= sec:
                fire = True
        else:
            for rule in conf.get("calendarRules", []) or []:
                if self._match_calendar(rule, now):
                    fire = True
                    break
        if not fire:
            return
        content = conf.get("content", "")
        targets = conf.get("targets", []) or []
        for gid in targets:
            msg = content
            if conf.get("atAll"):
                from lib.cqcode import cq_at_all
                msg = cq_at_all() + " " + content
            await self.star.sender.send_to_group(gid, msg)
        await self.star.store.write_key(last_key, "ts", now)

    @staticmethod
    def _match_calendar(rule: dict, now: float) -> bool:

        try:
            rtype = rule.get("type", "once")
            if rtype == "once":
                return now >= float(rule.get("ts", 0))
            if rtype == "daily":
                today = time.strftime("%Y-%m-%d")
                return rule.get("day") == today and now >= float(rule.get("ts", 0))
            if rtype == "hourly":
                return int(datetime.now().strftime("%H")) == int(rule.get("hour", -1))
        except (TypeError, ValueError):
            pass
        return False

def base64_encode(data: bytes) -> str:

    import base64
    return "base64://" + base64.b64encode(data).decode("utf-8")
