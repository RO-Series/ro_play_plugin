from __future__ import annotations

import math
import random
import re
import time
from typing import Any

import aiofiles
import astrbot.api.message_components as Comp
from astrbot.api import logger

SHOP_ITEMS: list[dict] = [
    {"道具": "诱饵", "原价": 100, "限购": {"模式": "个人", "数量": 20}},
]

STREAK_REWARDS: list[tuple[int, int, str]] = [
    (7, 520, "7"), (14, 1000, "14"), (30, 2000, "30"), (60, 10000, "60"),
]

FESTIVALS: list[dict] = [
    {"dates": ["0501", "0502", "0503", "0504", "0505", "0506"], "归笺": 1000, "诱饵": 15, "name": "劳动节"},
    {"dates": ["0601"], "归笺": 3333, "诱饵": 33, "name": "六一"},
    {"dates": ["0619"], "归笺": 1200, "诱饵": 10, "name": "端午"},
]

MONEY_REL = "BaiXuan/娱乐系统/游戏数据/归笺.json"
BAIT_REL = "BaiXuan/娱乐系统/钓鱼玩法/道具/诱饵.json"
BANK_MONEY_REL = "BaiXuan/娱乐系统/游戏数据/银行系统/银行归笺.json"
BANK_TIME_REL = "BaiXuan/娱乐系统/游戏数据/银行系统/储存时间.json"
SIGN_ROOT = "BaiXuan/娱乐系统/签到数据"

def _now() -> int:
    return int(time.time())

def _today() -> str:
    return time.strftime("%Y-%m-%d")

def _today_md() -> str:
    return time.strftime("%m%d")

def _time_a(fmt: str, ts: int | None = None) -> str:
    t = time.localtime(_now() if ts is None else int(ts))
    table = {
        "y": f"{t.tm_year:04d}", "m": f"{t.tm_mon:02d}", "d": f"{t.tm_mday:02d}",
        "H": f"{t.tm_hour:02d}", "i": f"{t.tm_min:02d}", "s": f"{t.tm_sec:02d}",
    }
    out = fmt
    for k, v in table.items():
        out = out.replace(k, v)
    return out

def rand_int(a: int, b: int) -> int:
    return random.randint(int(a), int(b))

def rand_float(a: float, b: float) -> float:
    return round(random.uniform(float(a), float(b)), 2)

def money_a(number: Any) -> str:

    n = float(number or 0)
    erci = math.ceil(n)
    if erci == 0:
        return f"{erci}归笺"
    yl = math.floor(n / 100000)
    yj = math.floor(n % 100000 / 1000)
    gj = math.floor(n % 1000)
    out = ""
    if yl != 0:
        out += f"{yl}玉令"
    if yj != 0:
        out += f"{yj}玉笺"
    out += f"{gj}归笺"
    return out

class EntertainmentModule:

    def __init__(self, star: Any) -> None:
        self.star = star

    async def _ent(self) -> bool:
        try:
            return await self.star.deep_entertainment_enabled()
        except Exception as e:
            logger.error(f"深度娱乐开关读取异常: {e}")
            return True

    async def _authorized(self, event: Any) -> bool:
        try:
            if self.star.config.get("bypass_license", False):
                return True
            gid = event.get_group_id()
            rel = f"BaiXuan/授权系统/授权信息/{gid}.json" if gid else "BaiXuan/授权系统/授权信息/私聊.json"
            data = await self.star.store.read_json(rel, {}) or {}
            wj_time = int(data.get("授权时间", 0) or 0)
            wj_km = int(data.get("卡密时长", 0) or 0)
            return wj_time != 0 and wj_km != 0 and (_now() - wj_time) <= wj_km
        except Exception as e:
            logger.error(f"授权判断异常: {e}")
            return False

    async def _gate(self, event: Any) -> bool:

        if not await self._ent():
            return False
        return await self._authorized(event)

    async def _money(self, uid: Any) -> int:
        return int(await self.star.store.read_key(MONEY_REL, str(uid), 0) or 0)

    async def _add_money(self, uid: Any, amount: int) -> int:
        cur = await self._money(uid)
        await self.star.store.write_key(MONEY_REL, str(uid), cur + amount)
        return cur + amount

    async def _add_bait(self, uid: Any, amount: int) -> int:
        cur = int(await self.star.store.read_key(BAIT_REL, str(uid), 0) or 0)
        await self.star.store.write_key(BAIT_REL, str(uid), cur + amount)
        return cur + amount

    async def _load_fish_pool(self, name: str) -> dict:

        p = self.star.data_path / "templates" / "text" / name
        try:
            async with aiofiles.open(p, "r", encoding="utf-8") as f:
                text = await f.read()
            return json_loads(text) if text else {}
        except Exception as e:
            logger.error(f"读取鱼池 {name} 失败: {e}")
            return {}

    async def _render_image(self, event: Any, template: str, data: dict, width: int = 750) -> Any | None:

        try:
            if not self.star.config.get("html_render_enabled", False):
                return None
            url = await self.star.render.render_html(template, data, width=width)
            if url:
                return event.image_result(url)
        except Exception as e:
            logger.warning(f"渲染 {template} 失败: {e}")
        return None

    async def sign_in(self, event: Any):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            今天 = _today()
            星期 = time.localtime().tm_wday
            今日人数 = int(await self.star.store.read_key(f"{SIGN_ROOT}/全服记录数量.json", 今天, 0) or 0)
            累计次数 = int(await self.star.store.read_key(f"{SIGN_ROOT}/累计次数.json", uid, 0) or 0)
            检测 = await self.star.store.read_key(f"{SIGN_ROOT}/日期记录/{今天}/检测.json", uid, "未知")
            if 检测 != "未知":
                签到排名 = await self.star.store.read_key(f"{SIGN_ROOT}/日期记录/{今天}/排名.json", uid, "未知")
                签到详细时间 = await self.star.store.read_key(f"{SIGN_ROOT}/日期记录/{今天}/详细时间.json", uid, "未知")
                连签数量 = int(await self.star.store.read_key(f"{SIGN_ROOT}/连签记录/连签数量.json", uid, 0) or 0)
                lines = [
                    "❌ 你今天签到过啦～就算再怎么发我也不会多给你哒！",
                    "════════════",
                    f"[名次]: 第{签到排名}名",
                    f"[时间]: {签到详细时间}",
                    f"[累计]: {累计次数}天",
                    f"[连签]: {连签数量}天",
                    "════════════",
                ]
                content = "\n".join(lines)
                render = await self._render_image(
                    event, "checkin.html",
                    {
                        "themeClass": "theme-night",
                        "avatarUrl": f"https://q4.qlogo.cn/g?b=qq&nk={uid}&s=5",
                        "userName": self._nickname(event),
                        "userId": uid,
                        "rankText": f"第{签到排名}名",
                        "statusText": "",
                        "contentHtml": '<div class="signed-big-text">已签到</div>',
                        "totalDays": f"{累计次数}天",
                        "streakText": f"连续 {连签数量} 天",
                        "eventsHtml": "",
                    },
                )
                return render if render else content
            本次序号 = 今日人数 + 1
            if 本次序号 <= 3:
                增加归笺 = rand_int(90, 125) if 本次序号 == 1 else (rand_int(75, 89) if 本次序号 == 2 else rand_int(50, 74))
                增加诱饵 = rand_int(4, 8)
            else:
                增加归笺 = rand_int(15, 49)
                增加诱饵 = rand_int(1, 8)
            周末触发 = 星期 in (5, 6)
            if 周末触发:
                增加归笺 = math.floor(增加归笺 * 1.5)
                增加诱饵 = math.floor(增加诱饵 * 1.5)
            节日触发 = False
            节日感言 = ""
            for festival in FESTIVALS:
                if _today_md() in festival["dates"]:
                    增加归笺 += festival["归笺"]
                    增加诱饵 += festival["诱饵"]
                    节日触发 = True
                    节日感言 += f"【{festival['name']}礼包:{festival['归笺']}归笺 {festival['诱饵']}诱饵】"
                    break
            当前时间 = _time_a("y-m-d H:i:s")
            当前时间戳 = _now()
            原归笺 = await self._money(uid)
            原诱饵 = int(await self.star.store.read_key(BAIT_REL, uid, 0) or 0)
            await self.star.store.write_key(MONEY_REL, uid, 原归笺 + 增加归笺)
            await self.star.store.write_key(BAIT_REL, uid, 原诱饵 + 增加诱饵)
            await self.star.store.write_key(f"{SIGN_ROOT}/累计次数.json", uid, 累计次数 + 1)
            await self.star.store.write_key(f"{SIGN_ROOT}/全服记录数量.json", 今天, 本次序号)
            await self.star.store.write_key(f"{SIGN_ROOT}/日期记录/{今天}/检测.json", uid, "已签到")
            await self.star.store.write_key(f"{SIGN_ROOT}/日期记录/{今天}/排名.json", uid, 本次序号)
            await self.star.store.write_key(f"{SIGN_ROOT}/日期记录/{今天}/详细时间.json", uid, 当前时间)

            总榜 = await self.star.store.read_json(f"{SIGN_ROOT}/每日总榜/{今天}.json", []) or []
            if isinstance(总榜, list):
                总榜.append({"QQ": uid, "排名": 本次序号, "获取归笺": 增加归笺, "签到时间": 当前时间})
                await self.star.store.write_json(f"{SIGN_ROOT}/每日总榜/{今天}.json", 总榜)

            上次签到时间 = int(await self.star.store.read_key(f"{SIGN_ROOT}/连签记录/上次签到/详细时间.json", uid, 0) or 0)
            时间差 = 当前时间戳 - 上次签到时间
            if 时间差 > 129600 or 上次签到时间 == 0:
                连签数量 = 1
                streak显示 = "1天，继续保持哦～" if 上次签到时间 else "中断啦！又要重新计算了～"
            else:
                连签数量 = int(await self.star.store.read_key(f"{SIGN_ROOT}/连签记录/连签数量.json", uid, 0) or 0) + 1
                streak显示 = f"连续 {连签数量} 天，继续保持哟～"
            await self.star.store.write_key(f"{SIGN_ROOT}/连签记录/连签数量.json", uid, 连签数量)
            await self.star.store.write_key(f"{SIGN_ROOT}/连签记录/上次签到/详细时间.json", uid, 当前时间戳)

            连签触发 = False
            连签感言 = ""
            for days, reward, key in STREAK_REWARDS:
                if 连签数量 >= days:
                    已领 = await self.star.store.read_key(f"{SIGN_ROOT}/连签记录/连签奖励_{key}.json", uid, False)
                    if not 已领:
                        增加归笺 += reward
                        连签触发 = True
                        连签感言 += f"【连签{days}天奖励:{reward}归笺】"
                        await self.star.store.write_key(f"{SIGN_ROOT}/连签记录/连签奖励_{key}.json", uid, True)

            事件列表: list[dict] = []
            if 周末触发:
                事件列表.append({"text": "【周末翻倍×1.5】", "bonus": False})
            if 节日触发:
                事件列表.append({"text": 节日感言, "bonus": True})
            if 连签触发:
                事件列表.append({"text": 连签感言, "bonus": True})
            events_html = ""
            if 事件列表:
                events_html = "".join(
                    f'<div class="event-tag {"bonus" if it["bonus"] else ""}" style="animation-delay: {i * 0.1}s">{it["text"]}</div>'
                    for i, it in enumerate(事件列表)
                )
            content_html = (
                '<div class="points-display"><div class="points-row">'
                f'<div class="point-item"><span class="point-prefix">归笺</span><span class="point-value">+{增加归笺}</span></div>'
                f'<div class="point-item"><span class="point-prefix">诱饵</span><span class="point-value">+{增加诱饵}</span></div>'
                "</div></div>"
            )
            render = await self._render_image(
                event, "checkin.html",
                {
                    "themeClass": "theme-day",
                    "avatarUrl": f"https://q4.qlogo.cn/g?b=qq&nk={uid}&s=5",
                    "userName": self._nickname(event),
                    "userId": uid,
                    "rankText": f"第{本次序号}名",
                    "statusText": "",
                    "contentHtml": content_html,
                    "totalDays": f"{累计次数 + 1}天",
                    "streakText": streak显示,
                    "eventsHtml": events_html,
                },
            )
            if render:
                return render
            lines = [
                "✅ 签到成功啦～！",
                "════════════",
                f"[归笺] +{增加归笺}",
                f"[诱饵] +{增加诱饵}",
                "----------------",
                f"[名次]: 第{本次序号}名",
                f"[时间]: {当前时间}",
                f"[累计]: {累计次数 + 1}天",
                f"[连签]: {streak显示}",
            ]
            if 周末触发 or 节日触发 or 连签触发:
                triggers = []
                if 周末触发:
                    triggers.append("【周末翻倍×1.5】")
                if 节日触发:
                    triggers.append(节日感言)
                if 连签触发:
                    triggers.append(连签感言)
                lines.append("---------------\n[触发]: " + "".join(triggers))
            lines.append("════════════")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"签到异常: {e}")
            return "签到执行出错，请查看日志"

    async def sign_rank(self, event: Any):

        try:
            if not await self._gate(event):
                return None
            今天 = _today()
            data = await self.star.store.read_json(f"{SIGN_ROOT}/每日总榜/{今天}.json", []) or []
            if not isinstance(data, list) or len(data) == 0:
                return "好像木有排名数据耶～？"
            count = len(data)
            uid = str(event.get_sender_id())
            本人排名 = "无"
            lines = [f"共计有 {count} 位签到用户", "仅展示前10位用户", f"你的排名 : {本人排名}", ""]
            for i, item in enumerate(data[:10]):
                lines.append(f"═════第{item.get('排名', i + 1)}名═════")
                lines.append(f"[名次] : 第{item.get('排名', i + 1)}名")
                lines.append(f"[用户] : {item.get('QQ', '')}")
                lines.append(f"[获得归笺] : {item.get('获取归笺', 0)}")
                lines.append(f"[签到时间] : {item.get('签到时间', '')}")
                if str(item.get("QQ", "")) == uid:
                    本人排名 = item.get("排名", i + 1)
            if 本人排名 != "无":
                lines[2] = f"你的排名 : {本人排名}"
            lines.append("══════════════")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"签到排行榜异常: {e}")
            return "签到排行榜执行出错，请查看日志"

    async def fishing(self, event: Any, times: int = 1):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            times = max(1, min(int(times), 100))
            诱饵数 = int(await self.star.store.read_key(BAIT_REL, uid, 0) or 0)
            if 诱饵数 < times:
                return "你的诱饵不足！可以通过「签到」获得哦～！"
            await self.star.store.write_key(BAIT_REL, uid, 诱饵数 - times)
            普通鱼池 = await self._load_fish_pool("fish_pool_1.json")
            高级鱼池 = await self._load_fish_pool("fish_pool_2.json")
            普通池 = list(普通鱼池.items())
            高级池 = list(高级鱼池.items())
            混合池 = 普通池 + 高级池
            if not 混合池:
                await self.star.store.write_key(BAIT_REL, uid, 诱饵数)
                return "鱼池数据为空：请确认 templates/text/fish_pool_1.json、fish_pool_2.json 存在！"
            累计 = 0
            lines = ["🎣 结果如下:", "══════════════"]
            for _ in range(times):
                本次抽取 = 普通池
                鱼池类型 = "普通"
                幸运值 = rand_int(0, 1000)
                if 501 < 幸运值 < 521:
                    鱼池类型 = "高级"
                    本次抽取 = 高级池
                if 666 < 幸运值 < 700:
                    鱼池类型 = "混合"
                    本次抽取 = 混合池
                if not 本次抽取:
                    本次抽取 = 混合池
                    鱼池类型 = "混合"
                if not 本次抽取:
                    continue
                鱼名, 基础 = 本次抽取[rand_int(0, len(本次抽取) - 1)]
                if not isinstance(基础, dict) or 基础.get("价格") is None or 基础.get("重量") is None:
                    continue
                基础价格 = float(基础["价格"])
                基础重量 = float(基础["重量"])
                最高重量 = float(await self.star.store.read_key(
                    "BaiXuan/娱乐系统/钓鱼玩法/全服数据/最高重量.json", 鱼名, 基础重量
                ) or 基础重量)
                幸运值2 = rand_int(1, 100)
                鱼重量 = rand_float(0.02, 最高重量)
                是否突破 = False
                if 80 < 幸运值2 < 85:
                    浮度 = math.floor(最高重量 + rand_float(0.5, 2))
                    鱼重量 = rand_float(最高重量, max(浮度, 最高重量 + 0.01))
                    是否突破 = True
                    await self.star.store.write_key(
                        "BaiXuan/娱乐系统/钓鱼玩法/全服数据/最高重量.json", 鱼名, 鱼重量
                    )
                最终价格 = max(1, round(鱼重量 / 基础重量 * 基础价格))
                lines.append(f"🐟 钓到 :【{鱼名}】({鱼重量}kg)" + ("🔥新记录" if 是否突破 else ""))
                lines.append(f"✨ 价格 ：{最终价格} 归笺\n")
                累计 += 最终价格
                key = f"{鱼名}({鱼重量}kg)"
                数量 = int(await self.star.store.read_key(f"BaiXuan/娱乐系统/钓鱼玩法/用户数据/{uid}.json", key, 0) or 0)
                await self.star.store.write_key(f"BaiXuan/娱乐系统/钓鱼玩法/用户数据/{uid}.json", key, 数量 + 1)
            lines.append("══════════════")
            lines.append("【总结】")
            lines.append(f"获得 {累计} 归笺")
            lines.append("发送 我的鱼获 可查询")
            text = "\n".join(lines)
            if times > 10:
                node = self.star.sender.build_node("[🎣本次钓鱼结果]", uid, text)
                await self.star.sender.send_forward(event, [node])
                return None
            return text
        except Exception as e:
            logger.error(f"钓鱼异常: {e}")
            return "钓鱼执行出错，请查看日志"

    async def my_fish(self, event: Any):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            普通鱼池 = await self._load_fish_pool("fish_pool_1.json")
            高级鱼池 = await self._load_fish_pool("fish_pool_2.json")
            用户数据 = await self.star.store.read_json(f"BaiXuan/娱乐系统/钓鱼玩法/用户数据/{uid}.json", {}) or {}
            if not 用户数据:
                return "🎣 你还没有任何鱼获，快去钓鱼吧！"
            总数量 = 0
            总价格 = 0
            列表: list[dict] = []
            for 鱼信息, 数量 in 用户数据.items():
                m = re.match(r"^(.*)\((.*)kg\)$", str(鱼信息))
                if not m:
                    continue
                鱼名, 重量 = m.group(1), float(m.group(2))
                单条 = 0
                if 鱼名 in 普通鱼池:
                    单条 = round(重量 / float(普通鱼池[鱼名]["重量"]) * float(普通鱼池[鱼名]["价格"]))
                elif 鱼名 in 高级鱼池:
                    单条 = round(重量 / float(高级鱼池[鱼名]["重量"]) * float(高级鱼池[鱼名]["价格"]))
                if 单条 <= 0:
                    continue
                数量 = int(数量)
                总数量 += 数量
                总价格 += 单条 * 数量
                列表.append({"鱼名": 鱼名, "重量": 重量, "数量": 数量, "单条价格": 单条, "总价格": 单条 * 数量})
            列表.sort(key=lambda x: x["重量"], reverse=True)
            lines = [
                f"🎣 鱼获统计\n══════════════\n总数量: {总数量} 条\n总价值: {money_a(总价格)}\n══════════════",
                "详细鱼获:\n══════════════",
            ]
            for i, fish in enumerate(列表):
                lines.append(f"{i + 1}. {fish['鱼名']}({fish['重量']}kg) × {fish['数量']} = {fish['总价格']} 归笺")
            lines.append("══════════════")
            lines.append("出售例子:")
            lines.append("出售 全部鱼")
            lines.append("出售 海龙(999kg)")
            lines.append("出售 海龙(999kg) 3")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"我的鱼获异常: {e}")
            return "我的鱼获执行出错，请查看日志"

    async def sell_fish(self, event: Any, args: str = ""):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            args = (args or "").strip()
            if not args:
                return "🎣 指令格式错误！\n使用方式:\n出售 鱼名(重量kg) 数量\n出售 鱼名(重量kg)\n出售 全部鱼"
            普通鱼池 = await self._load_fish_pool("fish_pool_1.json")
            高级鱼池 = await self._load_fish_pool("fish_pool_2.json")
            user_rel = f"BaiXuan/娱乐系统/钓鱼玩法/用户数据/{uid}.json"
            if args == "全部鱼":
                用户数据 = await self.star.store.read_json(user_rel, {}) or {}
                总数量 = 0
                总收入 = 0
                for 鱼信息, 数量 in 用户数据.items():
                    m = re.match(r"^(.*)\((.*)kg\)$", str(鱼信息))
                    if not m:
                        continue
                    鱼名, 重量 = m.group(1), float(m.group(2))
                    单条 = 0
                    if 鱼名 in 普通鱼池:
                        单条 = round(重量 / float(普通鱼池[鱼名]["重量"]) * float(普通鱼池[鱼名]["价格"]))
                    elif 鱼名 in 高级鱼池:
                        单条 = round(重量 / float(高级鱼池[鱼名]["重量"]) * float(高级鱼池[鱼名]["价格"]))
                    if 单条 <= 0:
                        continue
                    数量 = int(数量)
                    总数量 += 数量
                    总收入 += 单条 * 数量
                if 总数量 == 0:
                    return "🎣 没有可出售的鱼获！"
                await self.star.store.write_json(user_rel, {})
                await self._add_money(uid, 总收入)
                return (
                    "🎣 出售全部鱼获成功！\n══════════════\n"
                    f"出售数量: {总数量} 条\n获得收入: {总收入} 归笺\n══════════════"
                )
            m = re.match(r"^([^\(]+\([0-9]+(\.[0-9]+)?kg\))\s*(\d*)$", args)
            if not m:
                return "🎣 指令格式错误！\n使用方式:\n出售 鱼名(重量kg) 数量\n出售 鱼名(重量kg)\n出售 全部鱼"
            鱼信息 = m.group(1).strip()
            指定数量 = int(m.group(3)) if m.group(3) else None
            m2 = re.match(r"^([^\(]+)\(([0-9]+(\.[0-9]+)?)kg\)$", 鱼信息)
            if not m2:
                return "🎣 鱼的信息格式不正确，请使用：鱼名(重量kg)"
            鱼名, 重量 = m2.group(1), float(m2.group(2))
            用户数据 = await self.star.store.read_json(user_rel, {}) or {}
            拥有数量 = int(用户数据.get(鱼信息, 0) or 0)
            if 拥有数量 <= 0:
                return "🎣 你没有这条鱼哦～"
            单条 = 0
            if 鱼名 in 普通鱼池:
                单条 = round(重量 / float(普通鱼池[鱼名]["重量"]) * float(普通鱼池[鱼名]["价格"]))
            elif 鱼名 in 高级鱼池:
                单条 = round(重量 / float(高级鱼池[鱼名]["重量"]) * float(高级鱼池[鱼名]["价格"]))
            else:
                return f"🎣 错误：无法找到【{鱼名}】的价格信息！"
            if 指定数量 is None:
                出售数量 = 拥有数量
            else:
                if 指定数量 > 拥有数量:
                    return f"🎣 数量不足！你只有 {拥有数量} 条【{鱼信息}】，无法出售 {指定数量} 条！"
                出售数量 = 指定数量
            总收入 = 单条 * 出售数量
            剩余 = 拥有数量 - 出售数量
            if 剩余 > 0:
                await self.star.store.write_key(user_rel, 鱼信息, 剩余)
            else:
                await self.star.store.delete_key(user_rel, 鱼信息)
            await self._add_money(uid, 总收入)
            lines = ["🎣 出售成功！", "══════════════", f"🌐鱼种: {鱼信息}", f"💠出售数量: {出售数量} 条",
                     f"💰单价: {单条} 归笺", f"💹获得收入: {总收入} 归笺"]
            if 剩余 > 0:
                lines.append(f"🛑剩余数量: {剩余} 条")
            lines.append("══════════════")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"出售鱼异常: {e}")
            return "出售鱼执行出错，请查看日志"

    async def bank_menu(self, event: Any):

        try:
            if not await self._gate(event):
                return None
            return (
                "══════════════\n"
                "存款[数量]\n"
                "取出[数量]\n"
                "全部存款 全部取出\n"
                "转移归笺#[QQ]#[数量]\n"
                "--------------------\n"
                "打劫[艾特别人]\n"
                "══════════════"
            )
        except Exception as e:
            logger.error(f"银行菜单异常: {e}")
            return "银行菜单执行出错，请查看日志"

    async def bank_deposit(self, event: Any, amount: str = ""):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            amount = (amount or "").strip()
            归笺 = await self._money(uid)
            if amount == "全部":
                要存 = 归笺
            elif amount.isdigit():
                要存 = int(amount)
            else:
                return "请提供存款数量：/存款 数量 或 /全部存款"
            if 要存 <= 0:
                return "你是0吗？"
            if 要存 > 归笺:
                return "你现有的归笺好像没有这么多叭～？"
            银行 = int(await self.star.store.read_key(BANK_MONEY_REL, uid, 0) or 0)
            await self.star.store.write_key(MONEY_REL, uid, 归笺 - 要存)
            await self.star.store.write_key(BANK_MONEY_REL, uid, 银行 + 要存)
            储存时间 = int(await self.star.store.read_key(BANK_TIME_REL, uid, 0) or 0)
            if 储存时间 == 0:
                await self.star.store.write_key(BANK_TIME_REL, uid, _now())
            return (
                "存款成功啦～！\n══════════════\n"
                f"[存入]:{money_a(要存)}\n[总共]:{money_a(银行 + 要存)}\n══════════════"
            )
        except Exception as e:
            logger.error(f"存款异常: {e}")
            return "存款执行出错，请查看日志"

    @staticmethod
    def _bank_profit(本金: float, 储存时间: int) -> tuple[float, float]:

        now = _now()
        总秒数 = max(0, now - 储存时间)
        总小时 = 总秒数 / 3600
        总天数 = 总秒数 / 86400
        if 储存时间 <= 0 or 总秒数 <= 0:
            return 0.0, 总小时
        剩余小时数 = math.floor(总小时 / 2)
        if 剩余小时数 <= 0:
            return 0.0, 总小时
        rate = 0.00025
        if 总天数 >= 3:
            rate = 0.0008
        if 总天数 >= 7:
            rate = 0.001
        if 总天数 >= 14:
            rate = 0.0015
        if 总天数 >= 30:
            rate = 0.0019
        return math.ceil(本金 * 剩余小时数 * rate), 总小时

    async def bank_withdraw(self, event: Any, amount: str = ""):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            amount = (amount or "").strip()
            储存时间 = int(await self.star.store.read_key(BANK_TIME_REL, uid, 0) or 0)
            银行 = int(await self.star.store.read_key(BANK_MONEY_REL, uid, 0) or 0)
            if 储存时间 == 0:
                return "你好像没有储存过哎～我这里都找不到记录～"
            if amount == "全部":
                要取 = 银行
            elif amount.isdigit():
                要取 = int(amount)
            else:
                return "请提供取款数量：/取款 数量 或 /全部取款"
            if 要取 <= 0:
                return "你是0吗？"
            if 要取 > 银行:
                return "你好像没有这么多叭～？"
            利润, 总小时 = self._bank_profit(银行, 储存时间)
            归笺 = await self._money(uid)
            await self.star.store.write_key(MONEY_REL, uid, 归笺 + 利润 + 要取)
            await self.star.store.write_key(BANK_MONEY_REL, uid, 银行 - 要取)
            await self.star.store.write_key(BANK_TIME_REL, uid, _now())
            return (
                "取款成功啦～！\n══════════════\n"
                f"[取出]:{money_a(要取)}\n-------------------\n"
                f"[利润]:{money_a(利润)}\n[时长]:{round(总小时, 2)}小时\n══════════════"
            )
        except Exception as e:
            logger.error(f"取款异常: {e}")
            return "取款执行出错，请查看日志"

    async def transfer(self, event: Any, args: str = ""):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            parts = re.split(r"[#\s]+", (args or "").strip())
            parts = [p for p in parts if p]
            if len(parts) < 2:
                return "请按格式发送：转移归笺 #QQ #数量"
            目标, 数量 = parts[0], int(parts[1])
            if len(str(目标)) > 15 or len(str(数量)) > 15:
                return None
            if 数量 <= 0 or 数量 > await self._money(uid):
                return "这数量不对吧～？"
            if 目标 == uid:
                return "不阔以转给自己哟！"
            你归笺 = await self._money(目标)
            await self.star.store.write_key(MONEY_REL, 目标, 你归笺 + 数量)
            await self.star.store.write_key(MONEY_REL, uid, await self._money(uid) - 数量)
            return f"归笺转移成功～！\n目标:#{目标}\n数量:#{数量}"
        except Exception as e:
            logger.error(f"转移归笺异常: {e}")
            return "转移归笺执行出错，请查看日志"

    async def bank_rank(self, event: Any):

        try:
            if not await self._gate(event):
                return None
            shuju = await self.star.store.read_json(BANK_MONEY_REL, {}) or {}
            if not shuju:
                return "无数据"
            rows = []
            for 人, 本金 in shuju.items():
                本金 = max(0, int(本金))
                储存时间 = int(await self.star.store.read_key(BANK_TIME_REL, 人, 0) or 0)
                利润, _ = self._bank_profit(本金, 储存时间)
                rows.append({"QQ": 人, "总额": 本金 + 利润})
            rows.sort(key=lambda x: x["总额"], reverse=True)
            uid = str(event.get_sender_id())
            lines = [f"存款归笺排行榜(含利润) - 共【{len(rows)}】人", f"你的排名 : {self._rank_of(rows, uid)}", "══════════════"]
            for i, row in enumerate(rows):
                mark = "🟢" if row["QQ"] == uid else ""
                lines.append(f"{i + 1}.【{row['QQ']}】: {money_a(row['总额'])}{mark}")
            lines.append("══════════════")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"存款排行榜异常: {e}")
            return "存款排行榜执行出错，请查看日志"

    async def money_rank(self, event: Any):

        try:
            if not await self._gate(event):
                return None
            shuju = await self.star.store.read_json(MONEY_REL, {}) or {}
            rows = sorted(((人, max(0, int(值))) for 人, 值 in shuju.items()), key=lambda x: x[1], reverse=True)
            if not rows:
                return "无数据"
            uid = str(event.get_sender_id())
            lines = [f"归笺排行榜 - 共【{len(rows)}】人", f"你的排名 : {self._rank_of(rows, uid)}", "══════════════"]
            for i, (人, 值) in enumerate(rows):
                mark = "🟢" if 人 == uid else ""
                lines.append(f"{i + 1}.【{人}】: {money_a(值)}{mark}")
            lines.append("══════════════")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"归笺排行榜异常: {e}")
            return "归笺排行榜执行出错，请查看日志"

    @staticmethod
    def _rank_of(rows: list, uid: str) -> Any:
        for i, row in enumerate(rows):
            if row[0] == uid:
                return i + 1
        return "无"

    async def roulette(self, event: Any, amount: str = ""):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            amount = (amount or "").strip()
            if not amount.isdigit() or int(amount) <= 0:
                return "该玩法需要携带归笺哦～\n[使用例子]:幸运轮盘30"
            数值 = int(amount)
            文件 = int(await self.star.store.read_key("BaiXuan/娱乐系统/幸运轮盘/轮盘信息.json", "货币", 100) or 100)
            文件 = max(0, 文件)
            归笺 = await self._money(uid)
            上限 = math.floor(文件 * 0.3)
            if 数值 > 归笺 or 归笺 == 0:
                return "不儿，你有这么多归笺吗？"
            if 数值 > 上限:
                return f"数值异常！当前允许范围为「1 - {上限}」归笺！\n目前奖池为「{文件}」"
            if random.random() <= 0.01:
                原归笺 = await self._money(uid)
                await self.star.store.write_key(MONEY_REL, uid, 原归笺 + 文件)
                await self.star.store.write_key("BaiXuan/娱乐系统/幸运轮盘/轮盘信息.json", "货币", 100)
                return (
                    "概率爆爆爆！\n幸运大转盘成功命中！\n══════════════\n"
                    f"[获得]:{文件}归笺\n[目前]:{原归笺 + 文件}归笺\n══════════════\n"
                    "奖池已重置～欢迎继续体验！"
                )
            原归笺 = await self._money(uid)
            await self.star.store.write_key(MONEY_REL, uid, 原归笺 - 数值)
            await self.star.store.write_key("BaiXuan/娱乐系统/幸运轮盘/轮盘信息.json", "货币", 文件 + 数值)
            return (
                "可惜了....运气差了点.....\n══════════════\n"
                f"[奖池增加]:{数值}归笺\n[目前奖池]:{文件 + 数值}归笺\n══════════════\n"
                "不中时会把归笺融入奖池哦～"
            )
        except Exception as e:
            logger.error(f"幸运轮盘异常: {e}")
            return "幸运轮盘执行出错，请查看日志"

    def _at_targets(self, event: Any) -> list[str]:
        targets: list[str] = []
        try:
            for seg in event.get_messages() or []:
                if isinstance(seg, Comp.At):
                    qq = str(getattr(seg, "qq", "") or "")
                    if qq and qq != "all":
                        targets.append(qq)
        except Exception:
            pass
        return targets

    async def rob(self, event: Any):

        try:
            if not await self._gate(event):
                return None
            if not event.get_group_id():
                return None
            uid = str(event.get_sender_id())
            ats = self._at_targets(event)
            if len(ats) != 1:
                return None
            target = ats[0]
            self_id = str(getattr(event.message_obj, "self_id", "") or "")
            if target == self_id:
                return "补药打劫窝～五五五......"
            if target == uid:
                return None
            我归笺 = await self._money(uid)
            你归笺 = await self._money(target)
            if 我归笺 < 100:
                return "你的归笺不足哦～我可不会让你们空手套白狼～！"
            if 你归笺 < 100:
                return "他都剩下不到100的归笺了，放过他吧～"
            时间戳秒 = _now()
            冷却秒数 = 120
            保护时间 = 600
            文件记录_我 = int(await self.star.store.read_key("BaiXuan/娱乐系统/游戏数据/打劫冷却.json", uid, 0) or 0)
            文件记录_你 = int(await self.star.store.read_key("BaiXuan/娱乐系统/游戏数据/呜呜呜呜.json", target, 0) or 0)
            过去秒数_我 = 时间戳秒 - 文件记录_我
            过去秒数_你 = 时间戳秒 - 文件记录_你
            if 过去秒数_我 < 冷却秒数:
                return (
                    "══════════════\n"
                    " - 这位盆悠不要这么急哟！\n - 你可以看下面这个\n - 左边数字跟右边一样就好了\n"
                    f" - Tiem: {过去秒数_我}/{冷却秒数}\n══════════════"
                )
            if 过去秒数_你 < 保护时间:
                return (
                    "══════════════\n"
                    " - 对方处于保护期哦~\n"
                    f" - 你还需要等待 {保护时间 - 过去秒数_你}/{保护时间} 秒哦\n══════════════"
                )
            await self.star.store.write_key("BaiXuan/娱乐系统/游戏数据/打劫冷却.json", uid, 时间戳秒)
            await self.star.store.write_key("BaiXuan/娱乐系统/游戏数据/呜呜呜呜.json", target, 时间戳秒)
            if rand_int(1, 2) == 1:
                获取方式 = rand_int(1, 3)
                if 获取方式 == 1:
                    获取 = math.floor(你归笺 * 0.03)
                elif 获取方式 == 2:
                    获取 = rand_int(15, 100)
                else:
                    获取 = rand_int(20, 80)
                await self.star.store.write_key(MONEY_REL, uid, await self._money(uid) + 获取)
                await self.star.store.write_key(MONEY_REL, target, max(0, await self._money(target) - 获取))
                return (
                    "══════════════\n - 打劫成功！\n"
                    f" - 获得【{获取}】归笺\n - 运气值「{获取方式}」"
                )
            惩罚方式 = rand_int(1, 3)
            if 惩罚方式 == 1:
                惩罚 = math.floor(我归笺 * 0.1)
                时间 = 0
            elif 惩罚方式 == 2:
                惩罚 = rand_int(15, 100)
                时间 = rand_int(2, 5)
            else:
                惩罚 = rand_int(25, 80)
                时间 = 0
            禁言状态 = False
            gid = event.get_group_id()
            if 时间 > 0 and gid:

                try:
                    bot_self = str(getattr(event.message_obj, "self_id", "") or "")
                    bot_info = await self.star.api.get_group_member_info(gid, bot_self) if bot_self else None
                    bot_level = {"owner": 3, "admin": 2, "member": 1}.get((bot_info or {}).get("role", "member"), 1)
                    target_info = await self.star.api.get_group_member_info(gid, target)
                    target_level = {"owner": 3, "admin": 2, "member": 1}.get((target_info or {}).get("role", "member"), 1)
                    if bot_level > target_level or bot_level == 3:
                        await self.star.api.call("set_group_ban", group_id=gid, user_id=uid, duration=时间 * 60)
                        禁言状态 = True
                except Exception as e:
                    logger.warning(f"打劫失败禁言异常: {e}")
            await self.star.store.write_key(MONEY_REL, uid, max(0, await self._money(uid) - 惩罚))
            await self.star.store.write_key(MONEY_REL, target, await self._money(target) + 惩罚)
            lines = ["══════════════", " - 五五五～打劫失败了......", f" - 被没收了【{惩罚}】归笺"]
            if 禁言状态:
                lines.append(f" - 还被关禁闭「{时间}」分钟")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"打劫异常: {e}")
            return "打劫执行出错，请查看日志"

    async def fortune(self, event: Any):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            今天 = _today()
            try:
                数据 = await self._read_json_text("fortune.json")
                图片数据 = await self._read_json_text("url.json")
            except Exception as e:
                logger.error(f"运势资源读取失败: {e}")
                数据, 图片数据 = [], []
            rng = random.Random(f"{uid}_{今天}")
            数据_count = len(数据) if isinstance(数据, list) else 0
            图片_count = len(图片数据) if isinstance(图片数据, list) else 0
            if 数据_count == 0:
                return "运势数据加载失败！"
            key = f"{uid}_{今天}"
            saved = await self.star.store.read_key(f"BaiXuan/娱乐系统/今日运势/{今天}.json", key, None)
            if isinstance(saved, dict) and "文本" in saved:
                序号 = int(saved.get("文本", 0) or 0) % 数据_count
                图片序号 = int(saved.get("图片", 0) or 0) % max(图片_count, 1)
            else:
                序号 = rng.randint(0, 数据_count - 1)
                图片序号 = rng.randint(0, max(图片_count - 1, 0))
                await self.star.store.write_key(
                    f"BaiXuan/娱乐系统/今日运势/{今天}.json", key, {"文本": 序号, "图片": 图片序号}
                )
            entry = 数据[序号]
            标题 = str(entry.get("Sorte", ""))
            星数 = str(entry.get("Estrelas", ""))
            附言 = str(entry.get("signText", ""))
            细附 = str(entry.get("unSignText", ""))
            背景图 = 图片数据[图片序号] if 图片_count else ""
            bg = ""
            if isinstance(背景图, dict):
                bg = str(背景图.get("url") or 背景图.get("remote") or 背景图.get("link") or "")
            elif isinstance(背景图, str):
                bg = 背景图
            render = await self._render_image(
                event, "fortune.html",
                {
                    "qq": uid,
                    "time": _time_a("y-m-d H:i:s"),
                    "Sorte": 标题,
                    "Estrelas": 星数,
                    "signText": 附言,
                    "unSignText": 细附,
                    "backgroundImageCSS": f"url({bg})" if bg else "none",
                    "image_name": "",
                },
            )
            if render:
                return render
            return f"🜲 今日运势 🜲\n══════════════\n[运势]:{标题} {星数}\n[附言]:{附言}\n[细附]:{细附}\n══════════════"
        except Exception as e:
            logger.error(f"今日运势异常: {e}")
            return "今日运势执行出错，请查看日志"

    async def _read_json_text(self, name: str) -> Any:

        p = self.star.data_path / "templates" / "text" / name
        try:
            async with aiofiles.open(p, "r", encoding="utf-8") as f:
                text = await f.read()
            return json_loads(text) if text else []
        except Exception as e:
            logger.error(f"读取模板 {name} 失败: {e}")
            return []

    async def my_info(self, event: Any):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            归笺 = await self._money(uid)
            银行归笺 = int(await self.star.store.read_key(BANK_MONEY_REL, uid, 0) or 0)
            累计签到 = int(await self.star.store.read_key(f"{SIGN_ROOT}/累计次数.json", uid, 0) or 0)
            连签 = int(await self.star.store.read_key(f"{SIGN_ROOT}/连签记录/连签数量.json", uid, 0) or 0)
            诱饵 = int(await self.star.store.read_key(BAIT_REL, uid, 0) or 0)
            text = (
                "══════════════\n"
                f"[现有]:{money_a(归笺)}\n"
                f"[储存]:{money_a(银行归笺)}\n"
                f"[诱饵]:{诱饵}个\n"
                "---------------\n"
                f"[累签]:{累计签到}天\n"
                f"[连签]:{连签}天"
            )
            render = await self._render_image(
                event, "my_info.html",
                {
                    "qq": uid,
                    "time": _time_a("y-m-d H:i:s"),
                    "title": "我的信息",
                    "currentMoney": money_a(归笺),
                    "bankMoney": money_a(银行归笺),
                    "baitCount": str(诱饵),
                    "signTotal": str(累计签到),
                    "signStreak": str(连签),
                },
                width=1080,
            )
            return render if render else text
        except Exception as e:
            logger.error(f"我的信息异常: {e}")
            return "我的信息执行出错，请查看日志"

    async def shop(self, event: Any):

        try:
            if not await self._gate(event):
                return None
            今天 = _today()
            lines: list[str] = []
            for item in SHOP_ITEMS:
                名字 = item["道具"]
                原价 = int(item.get("原价", 100))
                限购模式 = item["限购"].get("模式", "个人")
                限购数量 = int(item["限购"].get("数量", 10))
                rel_float = f"BaiXuan/娱乐系统/商店系统/价格配置/浮动{今天}.json"
                rel_dir = f"BaiXuan/娱乐系统/商店系统/价格配置/升降{今天}.json"
                浮动 = await self.star.store.read_key(rel_float, 名字, "无")
                if 浮动 == "无":
                    if random.random() <= 0.3:
                        浮动 = round(random.uniform(0.05, 0.7), 2)
                        升降 = "降"
                    else:
                        浮动 = round(random.uniform(0.1, 0.5), 2)
                        升降 = "升"
                    await self.star.store.write_key(rel_float, 名字, 浮动)
                    await self.star.store.write_key(rel_dir, 名字, 升降)
                else:
                    浮动 = float(浮动)
                    升降 = str(await self.star.store.read_key(rel_dir, 名字, "升") or "升")
                if 升降 == "升":
                    现价 = math.floor(原价 + 原价 * 浮动)
                else:
                    现价 = max(1, math.floor(原价 - 原价 * 浮动))
                个人已买 = int(await self.star.store.read_key(
                    f"BaiXuan/娱乐系统/商店系统/限购数据/{名字}_{event.get_sender_id()}.json", 今天, 0
                ) or 0)
                全服已买 = int(await self.star.store.read_key(
                    f"BaiXuan/娱乐系统/商店系统/限购数据/{名字}_AAA全服.json", 今天, 0
                ) or 0)
                if 限购模式 == "个人":
                    可买 = "售空" if 个人已买 >= 限购数量 else 限购数量 - 个人已买
                else:
                    可买 = "售空" if 全服已买 >= 限购数量 else 限购数量 - 全服已买
                lines.append(
                    "══════════════\n"
                    f"道具名字【{名字}】\n今日价格【{现价}】\n"
                    f"{限购模式}限购【{限购数量}】\n可买次数【{可买}】\n══════════════"
                )
                await self.star.store.write_key(f"BaiXuan/娱乐系统/商店系统/每日数据/{今天}.json", 名字 + "_价格", 现价)
                await self.star.store.write_key(f"BaiXuan/娱乐系统/商店系统/每日数据/{今天}.json", 名字 + "_模式", 限购模式)
                await self.star.store.write_key(f"BaiXuan/娱乐系统/商店系统/每日数据/{今天}.json", 名字 + "_数量", 限购数量)
            return "\n".join(lines) or "商店数据加载异常！"
        except Exception as e:
            logger.error(f"商店异常: {e}")
            return "商店执行出错，请查看日志"

    async def buy(self, event: Any, args: str = ""):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            parts = re.split(r"[#\s]+", (args or "").strip())
            parts = [p for p in parts if p]
            if len(parts) < 2:
                return "请按格式发送：买 #名称 #数量"
            名字, 数数 = parts[0], int(parts[1])
            if len(名字) >= 25 or not (1 <= 数数 < 1000000):
                return None
            今天 = _today()
            daily_rel = f"BaiXuan/娱乐系统/商店系统/每日数据/{今天}.json"
            价格 = await self.star.store.read_key(daily_rel, 名字 + "_价格", "无")
            if 价格 == "无" or not 价格:
                return f"今日商品货架未显示有【{名字}】，请先发送【商店】刷新今日道具商店！"
            模式 = str(await self.star.store.read_key(daily_rel, 名字 + "_模式", "个人") or "个人")
            数量 = int(await self.star.store.read_key(daily_rel, 名字 + "_数量", 10) or 10)
            个人已买 = int(await self.star.store.read_key(
                f"BaiXuan/娱乐系统/商店系统/限购数据/{名字}_{uid}.json", 今天, 0
            ) or 0)
            全服已买 = int(await self.star.store.read_key(
                f"BaiXuan/娱乐系统/商店系统/限购数据/{名字}_AAA全服.json", 今天, 0
            ) or 0)
            if 模式 == "个人":
                if 个人已买 + 数数 > 数量:
                    return f"当前商品【{名字}】已{'超' if 个人已买 > 数数 else '达'}今日购买上限！{'明天再来吧～' if 个人已买 > 数数 else ''}"
            else:
                if 全服已买 + 数数 > 数量:
                    return f"当前商品【{名字}】已{'超' if 全服已买 > 数数 else '达'}今日全服购买上限！"
            归笺 = await self._money(uid)
            计算价格 = math.floor(int(价格) * 数数)
            if 归笺 < 计算价格:
                return f"你的归笺貌似不够哟～还差「{计算价格 - 归笺}」呢"
            await self.star.store.write_key(MONEY_REL, uid, 归笺 - 计算价格)
            if 模式 == "个人":
                await self.star.store.write_key(f"BaiXuan/娱乐系统/商店系统/限购数据/{名字}_{uid}.json", 今天, 个人已买 + 数数)
            else:
                await self.star.store.write_key(f"BaiXuan/娱乐系统/商店系统/限购数据/{名字}_AAA全服.json", 今天, 全服已买 + 数数)
            if 名字 == "诱饵":
                await self._add_bait(uid, 数数)
            return (
                "══════════════\n"
                "♻️购买成功\n"
                f"✳️购买道具【{名字}】\n"
                f"💹购买数量【{数数}】\n"
                f"💠消耗归笺【{计算价格}】\n"
                "══════════════"
            )
        except Exception as e:
            logger.error(f"购买道具异常: {e}")
            return "购买道具执行出错，请查看日志"

    def _nickname(self, event: Any) -> str:
        try:
            return str(getattr(event.message_obj.sender, "nickname", "") or "未知")
        except Exception:
            return "未知"

    async def legacy(self, event: Any, message: str) -> Any:

        try:
            if message in ("签到", "打卡"):
                return await self.sign_in(event)
            if message == "签到排行榜":
                return await self.sign_rank(event)
            if message in ("我的鱼获", "我的鱼篓"):
                return await self.my_fish(event)
            m = re.match(r"^钓鱼(一次|五次|十次|二十次|五十次|一百次|)$", message)
            if m:
                times = {"五次": 5, "十次": 10, "二十次": 20, "五十次": 50, "一百次": 100}.get(m.group(1), 1)
                return await self.fishing(event, times)
            m = re.match(r"^出售\s+(.+)$", message)
            if m:
                return await self.sell_fish(event, m.group(1))
            if message == "银行系统":
                return await self.bank_menu(event)
            m = re.match(r"^(全部|)(存款|存入)([0-9]+|)$", message)
            if m:
                if m.group(1) == "全部":
                    return await self.bank_deposit(event, "全部")
                if m.group(3):
                    return await self.bank_deposit(event, m.group(3))
            m = re.match(r"^(全部|)(取出|取款)([0-9]+|)$", message)
            if m:
                if m.group(1) == "全部":
                    return await self.bank_withdraw(event, "全部")
                if m.group(3):
                    return await self.bank_withdraw(event, m.group(3))
            m = re.match(r"^转移归笺#([0-9]+)#([0-9]+)$", message)
            if m:
                return await self.transfer(event, f"{m.group(1)} {m.group(2)}")
            if message in ("存款排行榜", "银行归笺排行榜"):
                return await self.bank_rank(event)
            if message == "归笺排行榜":
                return await self.money_rank(event)
            m = re.match(r"^幸运轮盘([0-9]+|)$", message)
            if m:
                return await self.roulette(event, m.group(1))
            if message.startswith("打劫"):
                return await self.rob(event)
            if message == "今日运势":
                return await self.fortune(event)
            if message in ("我的信息", "我的货币", "我的归笺"):
                return await self.my_info(event)
            if message == "商店":
                return await self.shop(event)
            m = re.match(r"^买#(.*) #([0-9]+)$", message)
            if m:
                return await self.buy(event, f"{m.group(1)} {m.group(2)}")
            return None
        except Exception as e:
            logger.error(f"娱乐 legacy 异常: {e}")
            return None

def json_loads(text: str) -> Any:
    import json
    try:
        return json.loads(text)
    except Exception:
        return None
