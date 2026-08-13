"""群老婆/老公模块（GroupWifeModule）。

对应原 index.mjs 的 handleGroupWifeCommands（L503-L877）。

数据（BaiXuan/娱乐系统/今日老婆/）：
- 处理.json（类型：单群模式/全群模式、冷却、过滤本人、过滤人机）
- 群组模式/{分群模式}/{群号}/{日}/记录.json（QQ→老婆QQ）、记录2.json（来源）、记录3.json（类型）、冷却.json
- 群组模式/全群模式/{日}/缓存数据/{小时}.json（成员缓存，每小时刷新一次）

每日抽取一次，可换一次；更换冷却默认 30s（配置 group_wife_cooldown）。
全群模式用 get_group_member_list 遍历全部群，每 10 群停顿 2 秒限速。
"""
from __future__ import annotations

import re
import time
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger

WIFE_REL = "BaiXuan/娱乐系统/今日老婆/处理.json"


def _now() -> int:
    return int(time.time())


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _hour() -> str:
    return time.strftime("%Y-%m-%d-%H")


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


class GroupWifeModule:
    """群老婆 / 群老公。"""

    def __init__(self, star: Any) -> None:
        self.star = star

    # ==================== 工具 ====================

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
        except Exception as e:  # noqa: BLE001
            logger.error(f"授权判断异常: {e}")
            return False

    async def _draw(self, event: Any, 指定: str, 换人: bool) -> Any:
        """抽取逻辑：今日/我的 显示，更换/换群 重抽。"""
        gid = str(event.get_group_id())
        uid = str(event.get_sender_id())
        self_id = str(getattr(event.message_obj, "self_id", "") or "")
        类型 = str(await self.star.store.read_key(WIFE_REL, "类型", "单群模式") or "单群模式")
        读写路径 = f"BaiXuan/娱乐系统/今日老婆/群组模式/"
        if 类型 == "单群模式":
            读写路径 += f"分群模式/{gid}/"
        else:
            读写路径 += "全群模式/"
        今天 = _today()
        昨天 = _time_a("y-m-d", _now() - 86400)
        现在小时 = _hour()
        昨日老婆 = await self.star.store.read_key(f"{读写路径}{昨天}/记录.json", uid, 0)
        今日老婆 = await self.star.store.read_key(f"{读写路径}{今天}/记录.json", uid, 0)
        来源记录 = await self.star.store.read_key(f"{读写路径}{今天}/记录2.json", uid, 0)
        性别记录 = await self.star.store.read_key(f"{读写路径}{今天}/记录3.json", uid, 0)
        记录时间 = int(await self.star.store.read_key(f"{读写路径}{今天}/冷却.json", uid, 0) or 0)
        过滤人机 = str(await self.star.store.read_key(WIFE_REL, "过滤人机", "开启") or "开启")
        过滤本人 = str(await self.star.store.read_key(WIFE_REL, "过滤本人", "开启") or "开启")
        时长 = int(self.star.config.get("group_wife_cooldown", 30))
        if 换人 and (_now() - 记录时间) < 时长:
            倒计时 = 时长 - (_now() - 记录时间)
            return f"冷却时间要{时长}秒哟～\n再等{倒计时}秒再来吧～！"
        iii = 来源记录
        if str(来源记录) == gid:
            iii = "本群"
        if not 换人 and 今日老婆 != 0:
            return self._show_wife(event, 今日老婆, 性别记录, iii, "❌ 你今天已经抽过啦～\n你如果要更换的话请发「更换老婆」「更换老公」")
        if 换人 and 今日老婆 == 0:
            return "你今天好像还没抽过哎～？要不你先抽一下？"
        # 获取成员数据
        data: list[dict] = []
        cache_rel = f"{读写路径}{今天}/缓存数据/{现在小时}.json"
        try:
            cache = await self.star.store.read_json(cache_rel, [])
            if isinstance(cache, list) and cache:
                data = cache
        except Exception:  # noqa: BLE001
            cache = None
        if not data:
            if 类型 == "全群模式":
                groups = await self.star.api.get_group_list()
                if not groups:
                    return "好像获取群聊列表失败了唉？～"
                if len(groups) >= 15:
                    await self.star.sender.send_reply(event, "全群模式数量庞大，请耐心等一等哦～")
                数量锁 = 0
                for g in groups:
                    来自群 = str(g.get("group_id") or "")
                    if not 来自群:
                        continue
                    try:
                        members = await self.star.api.get_group_member_list(来自群)
                        for m in members or []:
                            data.append({
                                "来自": 来自群,
                                "QQ": str(m.get("user_id") or ""),
                                "昵称": m.get("card") or m.get("nickname", ""),
                                "机器人": bool(m.get("is_robot", False)),
                                "性别": m.get("sex", "unknown"),
                            })
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"获取群 {来自群} 成员失败: {e}")
                    数量锁 += 1
                    if len(groups) >= 20 and 数量锁 >= 10:
                        await asyncio_sleep(2)
                        数量锁 = 0
            else:
                members = await self.star.api.get_group_member_list(gid)
                if not members:
                    return "❌群聊模式获取失败：群成员列表获取失败！1"
                for m in members:
                    data.append({
                        "来自": gid,
                        "QQ": str(m.get("user_id") or ""),
                        "昵称": m.get("card") or m.get("nickname", ""),
                        "机器人": bool(m.get("is_robot", False)),
                        "性别": m.get("sex", "unknown"),
                    })
            if data:
                try:
                    await self.star.store.write_json(cache_rel, data)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"写成员缓存失败: {e}")
        total = len(data)
        if total == 0:
            return "全部群就获取到0个人？？？"
        历史老婆 = [str(昨日老婆), str(今日老婆)]
        可重复数 = 5
        错误累计 = 0
        for _ in range(1, total):
            idx = random_index(0, total - 1)
            member = data[idx]
            suijiQQ = str(member.get("QQ", ""))
            if not suijiQQ or suijiQQ in 历史老婆:
                错误累计 += 1
                if 错误累计 >= 可重复数:
                    return "我找了好几次都匹配不中唉？～要不待会再来？"
                continue
            if 过滤人机 == "开启" and member.get("机器人"):
                错误累计 += 1
                if 错误累计 >= 可重复数:
                    return "我找了好几次都匹配不中唉？～要不待会再来？"
                continue
            if 过滤本人 == "开启" and (suijiQQ == self_id or suijiQQ == uid):
                错误累计 += 1
                if 错误累计 >= 可重复数:
                    return "我找了好几次都匹配不中唉？～要不待会再来？"
                continue
            nana = "老婆"
            if 指定 == "老公":
                nana = "老公"
                if str(member.get("性别", "")) != "male":
                    错误累计 += 1
                    if 错误累计 >= 可重复数:
                        return "我找了好几次都匹配不中唉？～要不待会再来？"
                    continue
            lll = str(member.get("来自", ""))
            if lll == gid:
                lll = "本群"
            await self.star.store.write_key(f"{读写路径}{今天}/记录.json", uid, suijiQQ)
            await self.star.store.write_key(f"{读写路径}{今天}/记录2.json", uid, str(member.get("来自", "")))
            await self.star.store.write_key(f"{读写路径}{今天}/记录3.json", uid, nana)
            await self.star.store.write_key(f"{读写路径}{今天}/冷却.json", uid, _now())
            return self._show_wife(
                event, suijiQQ, nana, lll,
                f"✅成功获取新的群友{nana}啦～",
                nick=str(member.get("昵称", "")),
            )
        return "我找了好几次都匹配不中唉？～要不待会再来？"

    def _show_wife(self, event: Any, wife_qq: Any, 类型: Any, 来源: Any, title: str, nick: str = "") -> Any:
        try:
            lines = [title, "══════════════"]
            if nick:
                lines.append(f"[昵称]:{nick}")
            lines.append(f"[类型]:{类型}")
            lines.append(f"[来源]:{来源}")
            lines.append("══════════════")
            text = "\n".join(lines)
            return event.chain_result([
                Comp.Image.fromURL(f"https://q4.qlogo.cn/g?b=qq&nk={wife_qq}&s=5"),
                Comp.Plain(f"\n{text}"),
            ])
        except Exception as e:  # noqa: BLE001
            logger.error(f"老婆展示异常: {e}")
            return title

    # ==================== 指令方法 ====================

    async def today(self, event: Any):
        """今日老婆 / 今日老公。"""
        try:
            if not await self._gate(event):
                return None
            return await self._draw(event, self._wanted(event), False)
        except Exception as e:  # noqa: BLE001
            logger.error(f"今日老婆异常: {e}")
            return "今日老婆执行出错，请查看日志"

    async def mine(self, event: Any):
        """我的老婆 / 我的老公。"""
        try:
            if not await self._gate(event):
                return None
            return await self._draw(event, self._wanted(event), False)
        except Exception as e:  # noqa: BLE001
            logger.error(f"我的老婆异常: {e}")
            return "我的老婆执行出错，请查看日志"

    async def change(self, event: Any):
        """更换老婆 / 更换老公（带冷却）。"""
        try:
            if not await self._gate(event):
                return None
            return await self._draw(event, self._wanted(event), True)
        except Exception as e:  # noqa: BLE001
            logger.error(f"更换老婆异常: {e}")
            return "更换老婆执行出错，请查看日志"

    async def switch_group(self, event: Any):
        """换群老婆：与更换一致（带冷却，重新抽取）。"""
        try:
            if not await self._gate(event):
                return None
            return await self._draw(event, "老婆", True)
        except Exception as e:  # noqa: BLE001
            logger.error(f"换群老婆异常: {e}")
            return "换群老婆执行出错，请查看日志"

    def _wanted(self, event: Any) -> str:
        try:
            text = event.message_str or ""
            if "老公" in text:
                return "老公"
        except Exception:  # noqa: BLE001
            pass
        return "老婆"

    async def _gate(self, event: Any) -> bool:
        if not event.get_group_id():
            return False
        try:
            if not await self.star.deep_entertainment_enabled():
                return False
        except Exception:  # noqa: BLE001
            pass
        return await self._authorized(event)

    # ==================== legacy ====================

    async def legacy(self, event: Any, message: str) -> Any:
        """无前缀指令：群老婆菜单 / 范围 / 冷却 / 过滤开关。"""
        try:
            if message == "群老婆":
                return (
                    "══════════════\n"
                    "普通指令↓\n"
                    " - 我的老婆 / 我的老公\n"
                    " - 今日老婆 / 今日老公\n"
                    " - 更换老婆 / 更换老公\n"
                    "管理员指令↓\n"
                    " - 更改群老婆范围全群模式\n"
                    " - 更改群老婆范围单群模式\n"
                    " - 更改群老婆冷却[时长:秒]\n"
                    " - [开启|关闭]群老婆过滤官机\n"
                    " - [开启|关闭]群老婆过滤本人\n"
                    "══════════════"
                )
            m = re.match(r"^更改群老婆范围(单群模式|全群模式)$", message)
            if m:
                if not event.get_group_id() or not await self._authorized(event):
                    return None
                if not await self.star.perm.check_admin(event):
                    return None
                mode = m.group(1)
                old = str(await self.star.store.read_key(WIFE_REL, "类型", "单群模式") or "单群模式")
                if mode == old:
                    return "与原来的一样啦～！"
                await self.star.store.write_key(WIFE_REL, "类型", mode)
                return f"好哒～！这就把设置群老婆的范围改成 {mode}！"
            m = re.match(r"^更改群老婆冷却([0-9]+)$", message)
            if m:
                if not event.get_group_id() or not await self._authorized(event):
                    return None
                if not await self.star.perm.check_admin(event):
                    return None
                num = int(m.group(1))
                old = int(await self.star.store.read_key(WIFE_REL, "冷却", 30) or 30)
                if num == old:
                    return "与原来的一样啦～！"
                await self.star.store.write_key(WIFE_REL, "冷却", num)
                return f"好哒～！这就把设置群老婆的冷却改成 {num}秒！"
            m = re.match(r"^(开启|关闭)群老婆(过滤本人|过滤官机)$", message)
            if m:
                if not event.get_group_id() or not await self._authorized(event):
                    return None
                if not await self.star.perm.check_admin(event):
                    return None
                操作 = m.group(1)
                类型 = m.group(2)
                键 = "过滤本人" if 类型 == "过滤本人" else "过滤人机"
                开关 = str(await self.star.store.read_key(WIFE_REL, 键, "开启") or "开启")
                if 开关 == 操作:
                    return f"目前【{类型}】已经处于「{开关}」状态啦！不能再弄啦！！！"
                await self.star.store.write_key(WIFE_REL, 键, 操作)
                return f"好哒，这就把【{类型}】的开关改成「{操作}」"
            return None
        except Exception as e:  # noqa: BLE001
            logger.error(f"群老婆 legacy 异常: {e}")
            return None


def asyncio_sleep(seconds: float) -> Any:
    import asyncio
    return asyncio.sleep(seconds)


def random_index(a: int, b: int) -> int:
    import random
    return random.randint(a, b)
