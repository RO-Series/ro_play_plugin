from __future__ import annotations

import random
import re
import time
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger

KM_TIME_TABLE: dict[str, int] = {
    "天": 86400,
    "周": 604800,
    "月": 2678400,
    "半年": 15724800,
    "年": 31622400,
    "永久": 311040000,
}

_CARD_RE = re.compile(r"^RO\w+$")
_GEN_RE = re.compile(r"^(天|周|月|半年|年|永久)(?:卡|)授权([0-9]*)$")
_ADD_RE = re.compile(r"^添加(天|周|月|半年|年|永久)(?:卡|)授权([0-9]*)$")
_USE_RE = re.compile(r"^使用卡密([\s\S]*)$")
_DEL_RE = re.compile(r"^(删除|清空)卡密([\s\S]*)$")
_CANCEL_RE = re.compile(r"^(删除|取消)授权([\s\S]*)$")

def _now() -> int:
    return int(time.time())

def _time_a(fmt: str, ts: int | None = None) -> str:

    t = time.localtime(_now() if ts is None else int(ts))
    table = {
        "y": f"{t.tm_year:04d}",
        "m": f"{t.tm_mon:02d}",
        "d": f"{t.tm_mday:02d}",
        "H": f"{t.tm_hour:02d}",
        "i": f"{t.tm_min:02d}",
        "s": f"{t.tm_sec:02d}",
    }
    out = fmt
    for k, v in table.items():
        out = out.replace(k, v)
    return out

def _time_b(fmt: str, seconds: int) -> str:

    remaining = int(seconds)
    units = {"y": 31536000, "m": 2678400, "d": 86400, "H": 3600, "i": 60, "s": 1}
    values: dict[str, int] = {}
    for k, sec in units.items():
        if k in fmt:
            values[k] = remaining // sec
            remaining %= sec
    out = fmt
    for k, v in values.items():
        out = out.replace(k, f"{v:02d}")
    return out

def _new_card() -> str:

    return f"RO{random.randint(100000, 999999)}{int(time.time())}"

class LicenseModule:

    def __init__(self, star: Any) -> None:
        self.star = star

    def _card_data_rel(self) -> str:
        return "BaiXuan/授权系统/卡密管理/卡密数据.json"

    def _info_rel(self, gid: str) -> str:
        return f"BaiXuan/授权系统/授权信息/{gid}.json"

    async def _target_info(self, event: Any, gid: str = "") -> tuple[str, str]:

        if gid:
            return f"群聊({gid})", self._info_rel(gid)
        group_id = event.get_group_id()
        if group_id:
            return f"群聊({group_id})", self._info_rel(str(group_id))
        return "私聊", self._info_rel("私聊")

    async def _license_data(self, rel: str) -> tuple[int, int]:
        data = await self.star.store.read_json(rel, {}) or {}
        wj_time = int(data.get("授权时间", 0) or 0)
        wj_km = int(data.get("卡密时长", 0) or 0)
        return wj_time, wj_km

    async def _authorized(self, event: Any) -> bool:

        try:
            if self.star.config.get("bypass_license", False):
                return True
            _, rel = await self._target_info(event)
            wj_time, wj_km = await self._license_data(rel)
            if wj_time == 0 or wj_km == 0:
                return False
            return (_now() - wj_time) <= wj_km
        except Exception as e:
            logger.error(f"授权判断异常: {e}")
            return False

    async def _forward_private(self, uid: Any, name: str, text: str) -> bool:

        try:
            node = self.star.sender.build_node(name, uid, text)
            return await self.star.api.call(
                "send_private_forward_msg", user_id=str(uid), messages=[node]
            )
        except Exception as e:
            logger.error(f"私聊合并转发失败: {e}")
            return False

    async def menu(self, event: Any):

        try:
            part1 = (
                "用户指令:\n"
                "══════════════\n"
                "授权判断\n"
                "授权判断[群号]\n"
                "使用卡密[卡密]\n"
                "══════════════"
            )
            part2 = (
                "后台指令:\n"
                "══════════════\n"
                " - 生成卡密\n"
                "生成天卡授权  生\n"
                "生成周卡授权  成\n"
                "生成月卡授权  卡\n"
                "生成半年授权  密\n"
                "生成年卡授权  授\n"
                "生成永久授权  权\n"
                "生成天卡授权[数量]（批量，上限100）\n"
                " - 添加到群聊\n"
                "添加天卡授权  / 添加天卡授权[群号]\n"
                " - 看列表的\n"
                "卡密列表\n"
                " - 删除卡密\n"
                "删除卡密[卡密] / 清空卡密\n"
                " - 取消授权\n"
                "删除授权 / 删除授权[群号]\n"
                "══════════════"
            )
            part3 = (
                "后记:\n"
                " - 该授权为插件授权\n"
                " - 授权时间数据纯本地文件的\n"
                " - 不需要授权系统的可以在后台开启「绕过授权」"
            )
            return [event.plain_result(part1), event.plain_result(part2), event.plain_result(part3)]
        except Exception as e:
            logger.error(f"授权系统菜单异常: {e}")
            return "菜单生成失败，请查看日志"

    async def check(self, event: Any, gid: str = ""):

        try:
            来源, rel = await self._target_info(event, gid.strip())
            wj_time, wj_km = await self._license_data(rel)
            xz_time = _now()
            jjjj = xz_time - wj_time
            lines = [f"{来源} - 授权数据", "══════════════"]
            if wj_time == 0 or wj_km == 0 or jjjj >= wj_km:
                lines.append(f"[授权时间]:{_time_a('y-m-d H:i:s', wj_time) if wj_time else '无'}")
                lines.append(f"[到期时间]:{_time_a('y-m-d H:i:s', wj_time + wj_km) if wj_km else '无'}")
                lines.append("[授权状态]:未授权")
            else:
                lines.append(f"[授权时间]:{_time_a('y-m-d H:i:s', wj_time)}")
                lines.append(f"[剩余时长]:{_time_b('d天H时i分s秒', wj_km - jjjj)}")
                lines.append(f"[到期时间]:{_time_a('y-m-d H:i:s', wj_time + wj_km)}")
                lines.append("[授权状态]:已授权")
            lines.append("══════════════")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"授权判断异常: {e}")
            return "授权判断执行出错，请查看日志"

    async def use_card(self, event: Any, card: str = ""):

        try:
            card = (card or "").strip()
            if not _CARD_RE.match(card):
                return "卡密无效！"
            data = await self.star.store.read_json(self._card_data_rel(), {}) or {}
            raw = data.get(card)
            if not isinstance(raw, dict):
                return "卡密无效！"
            卡密类型 = raw.get("类型")
            卡密时长 = raw.get("时长")
            try:
                卡密时长 = int(卡密时长)
            except (TypeError, ValueError):
                卡密时长 = 0
            if not 卡密类型 or 卡密时长 <= 0:
                return "卡密无效！"
            来源, rel = await self._target_info(event)
            xz_time = _now()
            wj_time, wj_km = await self._license_data(rel)
            jjjj = xz_time - wj_time
            if jjjj > wj_km:
                添加方式 = "重新添加授权"
                extime = xz_time + 卡密时长
                await self.star.store.write_key(rel, "授权时间", xz_time)
                await self.star.store.write_key(rel, "卡密时长", 卡密时长)
            else:
                添加方式 = "续期卡密时长"
                extime = xz_time + 卡密时长 + wj_km
                await self.star.store.write_key(rel, "卡密时长", 卡密时长 + wj_km)
            expire = _time_a("y-m-d H:i:s", extime)
            await self.star.store.delete_key(self._card_data_rel(), card)
            return (
                "══════════════\n"
                f"[使用目标]:{来源}\n"
                f"[增加模式]:{添加方式}\n"
                f"[卡密类型]:{卡密类型}卡\n"
                f"[新增时长]:{卡密时长}秒\n"
                f"[到期时间]:{expire}\n"
                "══════════════"
            )
        except Exception as e:
            logger.error(f"使用卡密异常: {e}")
            return "卡密使用处理出错，请查看日志"

    async def card_list(self, event: Any):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            data = await self.star.store.read_json(self._card_data_rel(), {}) or {}
            count = 0
            lines: list[str] = []
            counter = {"永久": 0, "年": 0, "半年": 0, "月": 0, "周": 0, "天": 0}
            for key, value in data.items():
                if not isinstance(value, dict):
                    continue
                typ = value.get("类型")
                dur = value.get("时长")
                if not typ or dur is None:
                    continue
                count += 1
                lines.append(f"{count}.[{typ}卡]:【{key}】")
                counter[typ] = counter.get(typ, 0) + 1
            if count == 0:
                return "目前没有卡密哦～"
            head = (
                f"共计【{count}】张卡密\n"
                "══════════════\n"
                f"[天卡]:{counter.get('天', 0)}\n"
                f"[周卡]:{counter.get('周', 0)}\n"
                f"[月卡]:{counter.get('月', 0)}\n"
                f"[半年]:{counter.get('半年', 0)}\n"
                f"[年卡]:{counter.get('年', 0)}\n"
                f"[永久]:{counter.get('永久', 0)}\n"
                "══════════════"
            )
            body = "\n".join(lines)
            uid = event.get_sender_id()
            await self.star.sender.send_reply(event, "已发给你的私聊啦，请查收～")
            await self._forward_private(uid, "[授权系统]", head + "\n" + body)
            return None
        except Exception as e:
            logger.error(f"卡密列表异常: {e}")
            return "卡密列表执行出错，请查看日志"

    async def generate(self, event: Any, args: str = ""):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            parts = (args or "").strip().split()
            if not parts:
                return "请按格式发送：生成卡密 类型 [数量]，类型为 天/周/月/半年/年/永久"
            typ = parts[0].replace("卡", "")
            count = 1
            if len(parts) >= 2:
                try:
                    count = int(parts[1])
                except ValueError:
                    return "请正常给我参数哦～"
            if typ not in KM_TIME_TABLE:
                return "请正常给我参数哦～"
            if count <= 0 or count >= 101:
                return "请正常给我参数哦～"
            km_time = KM_TIME_TABLE[typ]
            lines = [f"已生成【{count}】张【{typ}卡】"]
            for i in range(count):
                key = _new_card()
                await self.star.store.write_key(self._card_data_rel(), key, {"类型": typ, "时长": km_time})
                lines.append(f"【{i + 1}】{key}")
            uid = event.get_sender_id()
            await self.star.sender.send_reply(event, "已发给你的私聊啦，请查收～")
            text = "\n".join(lines)
            if count > 10:
                await self._forward_private(uid, "[新的卡密]", text)
            else:
                await self.star.sender.send_to_private(uid, text)
            return None
        except Exception as e:
            logger.error(f"生成卡密异常: {e}")
            return "卡密生成出错，请查看日志"

    async def delete_card(self, event: Any, card: str = ""):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            card = (card or "").strip()
            if not card:
                return "请提供卡密哦～"
            if card == "清空全部" or card == "清空":
                await self.star.store.write_json(self._card_data_rel(), {})
                return "已清空现在有的全部卡密啦～！"
            if not await self.star.store.has_key(self._card_data_rel(), card):
                return "卡密不存在！"
            await self.star.store.delete_key(self._card_data_rel(), card)
            return f"已删除卡密【{card}】"
        except Exception as e:
            logger.error(f"删除卡密异常: {e}")
            return "卡密删除出错，请查看日志"

    async def add_license(self, event: Any, args: str = ""):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            parts = (args or "").strip().split()
            if not parts:
                return "请按格式发送：添加授权 类型 [群号]，类型为 天/周/月/半年/年/永久"
            typ = parts[0].replace("卡", "")
            gid = parts[1] if len(parts) >= 2 else ""
            if typ not in KM_TIME_TABLE:
                return "出现未知类型报错"
            km_time = KM_TIME_TABLE[typ]
            _, rel = await self._target_info(event, gid)
            xz_time = _now()
            wj_time, wj_km = await self._license_data(rel)
            jjjj = xz_time - wj_time
            if jjjj > wj_km:
                添加方式 = "重新添加授权"
                extime = xz_time + km_time
                await self.star.store.write_key(rel, "授权时间", xz_time)
                await self.star.store.write_key(rel, "卡密时长", km_time)
            else:
                添加方式 = "续期卡密时长"
                extime = xz_time + km_time + wj_km
                await self.star.store.write_key(rel, "卡密时长", km_time + wj_km)
            return (
                "══════════════\n"
                f"已{添加方式}\n"
                f"[卡密类型]:{typ}卡\n"
                f"[新增时长]:{km_time}秒\n"
                f"[到期时间]:{_time_a('y-m-d H:i:s', extime)}\n"
                "══════════════"
            )
        except Exception as e:
            logger.error(f"添加授权异常: {e}")
            return "授权添加出错，请查看日志"

    async def remove_license(self, event: Any, gid: str = ""):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            mub, rel = await self._target_info(event, (gid or "").strip())
            await self.star.store.write_key(rel, "授权时间", 0)
            await self.star.store.write_key(rel, "卡密时长", 0)
            return f"我这就去把【{mub}】的授权状态给bian了！"
        except Exception as e:
            logger.error(f"删除授权异常: {e}")
            return "授权删除出错，请查看日志"

    async def legacy(self, event: Any, message: str) -> Any:

        try:
            if message == "授权系统":
                return await self.menu(event)
            if _GEN_RE.match(message):
                m = _GEN_RE.match(message)
                return await self.generate(event, f"{m.group(1)} {m.group(2) or 1}")
            if _ADD_RE.match(message):
                m = _ADD_RE.match(message)
                return await self.add_license(event, f"{m.group(1)} {m.group(2) or ''}".strip())
            if message.startswith("授权判断"):
                return await self.check(event, message[4:])
            if _USE_RE.match(message):
                return await self.use_card(event, _USE_RE.match(message).group(1))
            if _DEL_RE.match(message):
                m = _DEL_RE.match(message)
                if m.group(1) == "清空":
                    return await self.delete_card(event, "清空")
                return await self.delete_card(event, m.group(2))
            if message == "卡密列表":
                return await self.card_list(event)
            if _CANCEL_RE.match(message):
                m = _CANCEL_RE.match(message)
                return await self.remove_license(event, m.group(2))
            return None
        except Exception as e:
            logger.error(f"授权系统 legacy 异常: {e}")
            return None
