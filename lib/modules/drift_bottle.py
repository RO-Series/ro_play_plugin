from __future__ import annotations

import re
import time
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger

from lib.cqcode import cq_image

BOTTLE_ROOT = "BaiXuan/娱乐系统/漂流瓶"

def _now() -> int:
    return int(time.time())

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

class DriftBottleModule:

    def __init__(self, star: Any) -> None:
        self.star = star

    async def _gate(self, event: Any) -> bool:
        try:
            if not await self.star.deep_entertainment_enabled():
                return False
        except Exception:
            pass
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

    def _image_urls(self, event: Any) -> list[str]:
        urls: list[str] = []
        try:
            for seg in event.get_messages() or []:
                if isinstance(seg, Comp.Image):
                    u = str(getattr(seg, "url", "") or getattr(seg, "file", "") or "")
                    if u:
                        urls.append(u)
        except Exception:
            pass
        return urls

    def _text(self, event: Any) -> str:
        parts = []
        try:
            for seg in event.get_messages() or []:
                if isinstance(seg, Comp.Plain):
                    parts.append(str(getattr(seg, "text", "")))
        except Exception:
            pass
        return "".join(parts)

    def _bottle_text(self, 数据: dict) -> str:

        文本 = str(数据.get("瓶子内容", "") or "")
        图片数据 = 数据.get("图片数据", []) or []
        msg = 文本
        for u in 图片数据:
            if u:
                msg += cq_image(str(u))
        return msg

    async def _count(self) -> int:
        return int(await self.star.store.read_key(f"{BOTTLE_ROOT}/总数据.json", "总数量", 0) or 0)

    async def menu(self, event: Any):

        try:
            if not await self._gate(event):
                return None
            return (
                "══════════════\n"
                "抛瓶子[内容]/[图片]\n"
                "捞瓶子\n"
                "我的瓶子\n"
                "查瓶子[ID]\n"
                "删瓶子[ID]\n"
                "赞此瓶子/踩此瓶子\n"
                "══════════════"
            )
        except Exception as e:
            logger.error(f"漂流瓶菜单异常: {e}")
            return "漂流瓶菜单执行出错，请查看日志"

    async def throw_bottle(self, event: Any, content: str = ""):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            text = (content or "").strip()
            images = self._image_urls(event)
            text_count = len(text)
            line_count = len(text.split("\n"))
            if text == "" and len(images) == 0:
                return None
            if text_count < 3 and len(images) == 0:
                return "请包含至少三个字！"
            if line_count > 11 or len(images) > 5 or text_count > 500:
                return "请将内容控制在11行，500字，5图片范围内！"
            数据: dict = {"扔的人": uid, "瓶子内容": text, "扔出时间": _now()}
            if images:
                数据["图片数据"] = images
            总数 = await self._count()
            new_id = 总数 + 1
            await self.star.store.write_key(f"{BOTTLE_ROOT}/总数据.json", "总数量", new_id)
            await self.star.store.write_json(f"{BOTTLE_ROOT}/瓶子数据/{new_id}.json", 数据)
            return f"抛成功啦～！\n你的瓶子ID是:{new_id}"
        except Exception as e:
            logger.error(f"抛瓶子异常: {e}")
            return "抛瓶子执行出错，请查看日志"

    async def pick_bottle(self, event: Any):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            总数 = await self._count()
            if 总数 < 2:
                return "瓶子数量不足以运行本功能？"
            错误次数 = 0
            最大错误次数 = 5
            for _ in range(总数):
                if 错误次数 >= 最大错误次数:
                    break
                bid = random_bottle(1, 总数)
                状态 = await self.star.store.read_key(f"{BOTTLE_ROOT}/删除的.json", str(bid), "正常")
                if 状态 != "正常":
                    错误次数 += 1
                    continue
                数据 = await self.star.store.read_json(f"{BOTTLE_ROOT}/瓶子数据/{bid}.json", {}) or {}
                文本 = str(数据.get("瓶子内容", "") or "")
                if len(文本) < 3 and not 数据.get("图片数据"):
                    错误次数 += 1
                    continue
                被捞次数 = int(await self.star.store.read_key(f"{BOTTLE_ROOT}/被打捞次数.json", str(bid), 0) or 0)
                上传者 = str(数据.get("扔的人", "") or "")
                扔出时间 = _time_a("y-m-d H:i:s", int(数据.get("扔出时间", _now()) or _now()))
                赞 = int(await self.star.store.read_key(f"{BOTTLE_ROOT}/赞踩/{bid}.json", "赞", 0) or 0)
                踩 = int(await self.star.store.read_key(f"{BOTTLE_ROOT}/赞踩/{bid}.json", "踩", 0) or 0)
                await self.star.store.write_key(f"{BOTTLE_ROOT}/被打捞次数.json", str(bid), 被捞次数 + 1)
                await self.star.store.write_key(f"{BOTTLE_ROOT}/赞踩/正在进行.json", uid, str(bid))
                body = self._bottle_text(数据)
                return (
                    f"{body}\n══════════════\n"
                    f"[来自]:{上传者}\n[时间]:{扔出时间}\n-----------------\n"
                    f"[被捞]:{被捞次数 + 1}次\n[赞]:{赞}      [踩]:{踩}\n══════════════"
                )
            return "多次打捞都找不到～(∩ᵒ̴̶̷̤⌔ᵒ̴̶̷̤∩)"
        except Exception as e:
            logger.error(f"捞瓶子异常: {e}")
            return "捞瓶子执行出错，请查看日志"

    async def my_bottles(self, event: Any):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            总数 = await self._count()
            if 总数 == 0:
                return None
            有效数量 = 0
            lines: list[str] = []
            for i in range(总数):
                bid = i + 1
                数据 = await self.star.store.read_json(f"{BOTTLE_ROOT}/瓶子数据/{bid}.json", {}) or {}
                状态 = await self.star.store.read_key(f"{BOTTLE_ROOT}/删除的.json", str(bid), "正常")
                if str(数据.get("扔的人", "")) != uid or 状态 != "正常":
                    continue
                有效数量 += 1
                被捞次数 = int(await self.star.store.read_key(f"{BOTTLE_ROOT}/被打捞次数.json", str(bid), 0) or 0)
                扔出时间 = _time_a("y-m-d H:i:s", int(数据.get("扔出时间", _now()) or _now()))
                赞 = int(await self.star.store.read_key(f"{BOTTLE_ROOT}/赞踩/{bid}.json", "赞", 0) or 0)
                踩 = int(await self.star.store.read_key(f"{BOTTLE_ROOT}/赞踩/{bid}.json", "踩", 0) or 0)
                lines.append(f"【{bid}】\n - [浏览] : {被捞次数}次\n - [时间] : {扔出时间}\n - [赞]:{赞}      [踩]:{踩}\n")
            if 有效数量 == 0:
                return "窝好像没有找到你的瓶子哎～"
            head = f"你共有「{有效数量}」个瓶子\n══════════════"
            tail = "══════════════"
            return head + "\n" + "\n".join(lines) + tail
        except Exception as e:
            logger.error(f"我的瓶子异常: {e}")
            return "我的瓶子执行出错，请查看日志"

    async def query_bottle(self, event: Any, bottle_id: str = ""):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            bid = (bottle_id or "").strip()
            if not bid.isdigit():
                return "好像没有这个ID叭～？"
            总数 = await self._count()
            if int(bid) == 0 or int(bid) > 总数:
                return "好像没有这个ID叭～？"
            数据 = await self.star.store.read_json(f"{BOTTLE_ROOT}/瓶子数据/{bid}.json", {}) or {}
            上传者 = str(数据.get("扔的人", "") or "")
            权限 = 上传者 == uid
            if not 权限:
                try:
                    权限 = await self.star.perm.check_admin(event)
                except Exception:
                    权限 = False
            if not 权限:
                return "这个瓶子好像不是你的吧～？"
            状态 = await self.star.store.read_key(f"{BOTTLE_ROOT}/删除的.json", str(bid), "正常")
            if 状态 != "正常":
                return "这个瓶子好像本来就没了吧～？"
            文本 = str(数据.get("瓶子内容", "") or "")
            if len(文本) < 3 and not 数据.get("图片数据"):
                return "配置数据异常！"
            被捞次数 = int(await self.star.store.read_key(f"{BOTTLE_ROOT}/被打捞次数.json", str(bid), 0) or 0)
            扔出时间 = _time_a("y-m-d H:i:s", int(数据.get("扔出时间", _now()) or _now()))
            body = self._bottle_text(数据)
            return (
                f"{body}\n══════════════\n"
                f"[来自]:{上传者}\n[时间]:{扔出时间}\n-----------------\n"
                f"[次数]:{被捞次数}\n══════════════"
            )
        except Exception as e:
            logger.error(f"查瓶子异常: {e}")
            return "查瓶子执行出错，请查看日志"

    async def delete_bottle(self, event: Any, bottle_id: str = ""):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            bid = (bottle_id or "").strip()
            if not bid.isdigit():
                return "好像没有这个ID叭～？"
            总数 = await self._count()
            if int(bid) == 0 or int(bid) > 总数:
                return "好像没有这个ID叭～？"
            数据 = await self.star.store.read_json(f"{BOTTLE_ROOT}/瓶子数据/{bid}.json", {}) or {}
            上传者 = str(数据.get("扔的人", "") or "")
            权限 = 上传者 == uid
            if not 权限:
                try:
                    权限 = await self.star.perm.check_admin(event)
                except Exception:
                    权限 = False
            if not 权限:
                return "这个瓶子好像不是你的吧～？"
            状态 = await self.star.store.read_key(f"{BOTTLE_ROOT}/删除的.json", str(bid), "正常")
            if 状态 != "正常":
                return "这个瓶子好像本来就没了吧～？"
            总删除 = int(await self.star.store.read_key(f"{BOTTLE_ROOT}/删除的.json", "总删除", 0) or 0)
            await self.star.store.write_key(f"{BOTTLE_ROOT}/删除的.json", "总删除", 总删除 + 1)
            await self.star.store.write_key(f"{BOTTLE_ROOT}/删除的.json", str(bid), "异常")
            return f"耗的，这就把【{bid}】的瓶子给抹除了！"
        except Exception as e:
            logger.error(f"删瓶子异常: {e}")
            return "删瓶子执行出错，请查看日志"

    async def _vote(self, event: Any, 赞踩: str):

        try:
            if not await self._gate(event):
                return None
            uid = str(event.get_sender_id())
            mub = await self.star.store.read_key(f"{BOTTLE_ROOT}/赞踩/正在进行.json", uid, "无")
            if mub == "无":
                return "请你先捞一下瓶子再弄好嘛？"
            状态 = await self.star.store.read_key(f"{BOTTLE_ROOT}/赞踩/投票状态/{uid}.json", mub, "未")
            if 状态 == "已":
                return "这个瓶子你已经操作过啦～！"
            值 = int(await self.star.store.read_key(f"{BOTTLE_ROOT}/赞踩/{mub}.json", 赞踩, 0) or 0)
            await self.star.store.write_key(f"{BOTTLE_ROOT}/赞踩/{mub}.json", 赞踩, 值 + 1)
            await self.star.store.write_key(f"{BOTTLE_ROOT}/赞踩/投票状态/{uid}.json", mub, "已")
            return f"已对瓶子【{mub}】进行投票啦～！"
        except Exception as e:
            logger.error(f"瓶子投票异常: {e}")
            return "瓶子投票执行出错，请查看日志"

    async def like_bottle(self, event: Any, bottle_id: str = ""):

        return await self._vote(event, "赞")

    async def dislike_bottle(self, event: Any, bottle_id: str = ""):

        return await self._vote(event, "踩")

    async def legacy(self, event: Any, message: str) -> Any:

        try:
            if message == "漂流瓶":
                return await self.menu(event)
            if message in ("捞瓶子", "捡瓶子"):
                return await self.pick_bottle(event)
            if message == "我的瓶子":
                return await self.my_bottles(event)
            m = re.match(r"^抛瓶子([\s\S]*)$", message)
            if m:
                text = self._text(event).replace("抛瓶子", "", 1).strip()
                if not text:
                    return await self.throw_bottle(event, m.group(1).strip())
                return await self.throw_bottle(event, text)
            m = re.match(r"^(查|删)瓶子([0-9]+)$", message)
            if m:
                if m.group(1) == "查":
                    return await self.query_bottle(event, m.group(2))
                return await self.delete_bottle(event, m.group(2))
            if message == "赞此瓶子":
                return await self.like_bottle(event)
            if message == "踩此瓶子":
                return await self.dislike_bottle(event)
            return None
        except Exception as e:
            logger.error(f"漂流瓶 legacy 异常: {e}")
            return None

def random_bottle(a: int, b: int) -> int:
    import random
    return random.randint(a, b)
