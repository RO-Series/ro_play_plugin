from __future__ import annotations

import datetime
import re
from typing import Any

from astrbot.api import logger

class TalkStatsModule:

    def __init__(self, star) -> None:
        self.star = star
        self.store = star.store

    @staticmethod
    def _day_str(offset_days: int = 0) -> str:
        return (datetime.date.today() + datetime.timedelta(days=offset_days)).strftime("%Y-%m-%d")

    def _stats_dir(self, gid: str) -> str:
        return f"BaiXuan/扩展功能/发言统计/{gid}/次数统计"

    async def count(self, event) -> None:

        try:
            gid = str(event.get_group_id() or "")
            if not gid:
                return
            uid = str(event.get_sender_id())
            today = self._day_str()
            rel = f"{self._stats_dir(gid)}/{today}.json"
            num = int(await self.store.read_key(rel, uid, 0) or 0)
            await self.store.write_key(rel, uid, num + 1)
        except Exception as e:
            logger.error(f"发言统计失败: {e}")

    async def legacy(self, event, message: str) -> Any:

        try:
            m = re.match(r"^发言排行(今日|昨日|七日|本月|个人)榜$", message)
            if not m:
                return None
            gid = str(event.get_group_id() or "")
            if not gid:
                return None
            kind = m.group(1)
            if kind == "今日":
                return await self._rank_single(event, gid, self._day_str(), "今日")
            if kind == "昨日":
                return await self._rank_single(event, gid, self._day_str(-1), "昨日")
            if kind == "七日":
                return await self._rank_range(event, gid, self._day_str(-6), self._day_str(), "七日")
            if kind == "本月":
                first = self._day_str()[0:8] + "01"
                return await self._rank_range(event, gid, first, self._day_str(), "本月")
            if kind == "个人":
                return await self._rank_personal(event, gid)
        except Exception as e:
            logger.error(f"发言排行 legacy 异常: {e}")
        return None

    async def _rank_single(self, event, gid: str, day: str, label: str) -> Any:
        rel = f"{self._stats_dir(gid)}/{day}.json"
        data = await self.store.read_json(rel, {}) or {}
        ranking = sorted(data.items(), key=lambda kv: int(kv[1] or 0), reverse=True)
        if not ranking:
            return f"{label}暂无数据！" if label != "今日" else "好像木有获取到数据哎！？"
        total = sum(int(v or 0) for _, v in ranking)
        lines = [f"共计有【{len(ranking)}】人，消息总数:{total}", "══════════════"]
        lines += [f"【{i + 1}】{qq} : {cnt}条" for i, (qq, cnt) in enumerate(ranking)]
        text = "\n".join(lines)
        if len(ranking) >= 15:
            nodes = [self.star.sender.build_node(f"[{label}发言统计]", event.get_sender_id(), text)]
            await self.star.sender.send_forward(event, nodes)
            return None
        return text

    async def _rank_range(self, event, gid: str, start: str, end: str, label: str) -> Any:
        files = await self.store.list_files(self._stats_dir(gid))
        agg: dict = {}
        for name in files:
            day = name[:-5] if name.endswith(".json") else name
            if start <= day <= end:
                data = await self.store.read_json(f"{self._stats_dir(gid)}/{name}", {}) or {}
                for qq, cnt in (data or {}).items():
                    agg[str(qq)] = int(agg.get(str(qq), 0)) + int(cnt or 0)
        ranking = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)
        if not ranking:
            return f"最近{label}暂无数据！"
        total = sum(v for _, v in ranking)
        lines = [f"共计有【{len(ranking)}】人，消息总数:{total}", "══════════════"]
        lines += [f"【{i + 1}】{qq} : {cnt}条" for i, (qq, cnt) in enumerate(ranking)]
        text = "\n".join(lines)
        if len(ranking) >= 15:
            nodes = [self.star.sender.build_node(f"[{label}发言统计]", event.get_sender_id(), text)]
            await self.star.sender.send_forward(event, nodes)
            return None
        return text

    async def _rank_personal(self, event, gid: str) -> Any:
        files = await self.store.list_files(self._stats_dir(gid))
        if not files:
            return "获取数据失败了唉！"
        uid = str(event.get_sender_id())
        today = self._day_str()
        yesterday = self._day_str(-1)
        now = datetime.date.today()
        monday = now - datetime.timedelta(days=now.weekday())
        last_monday = monday - datetime.timedelta(days=7)
        last_sunday = monday - datetime.timedelta(days=1)
        month_first = today[0:8] + "01"
        year_first = f"{now.year}-01-01"
        prev_month_end = (now.replace(day=1) - datetime.timedelta(days=1))
        prev_month_first = prev_month_end.replace(day=1)
        today_cnt = yesterday_cnt = week_cnt = last_week_cnt = month_cnt = last_month_cnt = year_cnt = total = 0
        for name in files:
            day = name[:-5] if name.endswith(".json") else name
            cnt = int(await self.store.read_key(f"{self._stats_dir(gid)}/{name}", uid, 0) or 0)
            if cnt <= 0:
                continue
            total += cnt
            if day == today:
                today_cnt += cnt
            if day == yesterday:
                yesterday_cnt += cnt
            if monday.strftime("%Y-%m-%d") <= day <= today:
                week_cnt += cnt
            if last_monday.strftime("%Y-%m-%d") <= day <= last_sunday.strftime("%Y-%m-%d"):
                last_week_cnt += cnt
            if month_first <= day <= today:
                month_cnt += cnt
            if prev_month_first.strftime("%Y-%m-%d") <= day <= prev_month_end.strftime("%Y-%m-%d"):
                last_month_cnt += cnt
            if year_first <= day <= today:
                year_cnt += cnt
        return (
            "我的发言:\n"
            f"今日: {today_cnt}\n"
            f"本周: {week_cnt}\n"
            f"本月: {month_cnt}\n"
            f"本年: {year_cnt}\n"
            "--------------\n"
            f"昨日: {yesterday_cnt}\n"
            f"上周: {last_week_cnt}\n"
            f"上月: {last_month_cnt}\n"
            f"总次: {total}"
        )
