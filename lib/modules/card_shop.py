from __future__ import annotations

import random
import re
import time
from typing import Any

from astrbot.api import logger

SHOP_REL = "BaiXuan/扩展功能/发卡系统"
STOCK_REL = f"{SHOP_REL}/库存"

def _code() -> str:

    letters = "".join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(3))
    return letters + str(random.randint(100000, 999999))

def _log_time() -> str:
    t = time.localtime()
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d} {t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"

class CardShopModule:

    def __init__(self, star: Any) -> None:
        self.star = star

    async def _authorized(self, event: Any) -> bool:
        try:
            if self.star.config.get("bypass_license", False):
                return True
            gid = event.get_group_id()
            rel = f"BaiXuan/授权系统/授权信息/{gid}.json" if gid else "BaiXuan/授权系统/授权信息/私聊.json"
            data = await self.star.store.read_json(rel, {}) or {}
            wj_time = int(data.get("授权时间", 0) or 0)
            wj_km = int(data.get("卡密时长", 0) or 0)
            return wj_time != 0 and wj_km != 0 and (int(time.time()) - wj_time) <= wj_km
        except Exception as e:
            logger.error(f"授权判断异常: {e}")
            return False

    def _code_of(self, data: dict, name: str) -> str:
        return str((data or {}).get(name, "") or "")

    async def _stock_lines(self, code: str) -> list[str]:
        text = await self.star.store.read_text(f"{STOCK_REL}/{code}.txt", "")
        return [ln for ln in text.splitlines() if ln.strip()]

    async def _stock_count(self, code: str) -> int:
        return len(await self._stock_lines(code))

    async def _take_from_stock(self, code: str, n: int) -> list[str] | None:

        text = await self.star.store.read_text(f"{STOCK_REL}/{code}.txt", "")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) < n:
            return None
        taken = lines[:n]
        rest = lines[n:]
        await self.star.store.write_text(f"{STOCK_REL}/{code}.txt", "\n".join(rest))
        return taken

    async def _money(self, uid: Any) -> int:
        return int(await self.star.store.read_key("BaiXuan/娱乐系统/游戏数据/归笺.json", str(uid), 0) or 0)

    async def shop(self, event: Any):

        try:
            if not await self._authorized(event):
                return None
            代号表 = await self.star.store.read_json(f"{SHOP_REL}/商品代号.json", {}) or {}
            价格表 = await self.star.store.read_json(f"{SHOP_REL}/商品价格.json", {}) or {}
            上下架表 = await self.star.store.read_json(f"{SHOP_REL}/商品上下架.json", {}) or {}
            全部名 = sorted(代号表.keys())
            if not 全部名:
                return "🛒 发卡商店\n══════════════\n暂无商品，请先添加发卡商品"
            在售 = [n for n in 全部名 if bool(上下架表.get(n, False))]
            if not 在售:
                return "🛒 发卡商店\n══════════════\n暂无在售商品（当前全部已下架，请主人执行 发卡商品上架）"
            lines = ["🛒 发卡商店（仅展示上架商品）", "══════════════"]
            for i, name in enumerate(在售):
                code = self._code_of(代号表, name)
                单价 = 价格表.get(name)
                价显 = f"{单价} 归笺" if 单价 is not None else "-"
                库存 = await self._stock_count(code)
                lines.append(f"📦 {name}\n💰 价格：{价显}\n📊 库存：{库存} 条")
                if i < len(在售) - 1:
                    lines.append("──────────────")
            lines.append("══════════════\n💡 购买：兑换商品 商品名 数量\n📖 完整说明：发卡系统")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"发卡商店异常: {e}")
            return "发卡商店执行出错，请查看日志"

    async def exchange(self, event: Any, args: str = ""):

        try:
            if not await self._authorized(event):
                return None
            parts = (args or "").strip().split()
            if len(parts) < 2 or not parts[1].isdigit():
                return "请按格式发送：\n兑换商品 商品名称 数量\n例：兑换商品 测试商品1 1"
            商品名 = " ".join(parts[:-1])
            数量 = int(parts[-1])
            if not 商品名 or 数量 < 1:
                return "商品名不能为空，数量须为≥1的整数"
            代号表 = await self.star.store.read_json(f"{SHOP_REL}/商品代号.json", {}) or {}
            代号 = self._code_of(代号表, 商品名)
            if not 代号:
                return f"商品「{商品名}」不存在"
            上下架表 = await self.star.store.read_json(f"{SHOP_REL}/商品上下架.json", {}) or {}
            if not bool(上下架表.get(商品名, False)):
                return f"商品「{商品名}」不存在"
            价格表 = await self.star.store.read_json(f"{SHOP_REL}/商品价格.json", {}) or {}
            单价 = 价格表.get(商品名)
            if 单价 is None:
                return f"商品「{商品名}」尚未定价，无法兑换"
            总价 = int(单价) * 数量
            uid = str(event.get_sender_id())
            当前归笺 = await self._money(uid)
            if 当前归笺 < 总价:
                return f"归笺不足：需要 {总价}，当前 {当前归笺}"
            库存 = await self._stock_count(代号)
            if 库存 < 数量:
                return f"库存不足（当前 {库存} 条，需要 {数量} 条）"
            await self.star.store.write_key("BaiXuan/娱乐系统/游戏数据/归笺.json", uid, 当前归笺 - 总价)
            取出 = await self._take_from_stock(代号, 数量)
            if 取出 is None:
                await self.star.store.write_key("BaiXuan/娱乐系统/游戏数据/归笺.json", uid, 当前归笺)
                return f"库存不足（已退回归笺）"
            兑换后货币 = 当前归笺 - 总价
            log_key = f"{int(time.time() * 1000)}_{uid}"
            await self.star.store.write_key(
                f"{SHOP_REL}/兑换日志.json", log_key,
                {
                    "时间戳毫秒": int(time.time() * 1000),
                    "时间年月日时分秒": _log_time(),
                    "QQ": uid,
                    "兑换前货币": 当前归笺,
                    "获得的卡密": 取出,
                    "兑换后货币": 兑换后货币,
                },
            )
            货文本 = "\n".join(f"{i + 1}. {line}" for i, line in enumerate(取出))
            私发 = (
                "✅ 兑换成功（发卡系统）\n══════════════\n"
                f"🛍️ {商品名} × {数量}\n💰 已扣 {总价} 归笺（单价 {单价}）\n"
                f"📬 卡密如下，请妥善保管：\n{货文本}\n══════════════\n"
                f"💠 当前剩余归笺：{兑换后货币}"
            )
            await self.star.sender.send_to_private(uid, 私发)
            if event.get_group_id():
                return (
                    f"✅ 兑换成功！卡密已通过私聊发送，请打开与机器人的私信查看。\n"
                    f"已扣 {总价} 归笺，剩余 {兑换后货币}"
                )
            return None
        except Exception as e:
            logger.error(f"兑换商品异常: {e}")
            return "兑换商品执行出错，请查看日志"

    async def add_product(self, event: Any, name: str = ""):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            name = (name or "").strip()
            if not name:
                return "请输入商品名称哦～"
            代号表 = await self.star.store.read_json(f"{SHOP_REL}/商品代号.json", {}) or {}
            if name in 代号表:
                return f"已经有过这个商品啦～\n专属代号{代号表[name]}"
            随机代号 = _code()
            await self.star.store.write_key(f"{SHOP_REL}/商品代号.json", name, 随机代号)
            return f"好啦！已经成功添加这个商品啦，专属代号为{随机代号}"
        except Exception as e:
            logger.error(f"添加发卡商品异常: {e}")
            return "添加发卡商品执行出错，请查看日志"

    async def fill_product(self, event: Any, args: str = ""):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            raw_lines = (args or "").strip("\n").splitlines()
            if len(raw_lines) < 2:
                return "请按格式发送：\n填充发卡商品 商品名\n内容1\n内容2..."
            商品名 = raw_lines[0].replace("填充发卡商品", "").strip()
            if not 商品名:
                return "请指定商品名称"
            新内容 = [ln.strip() for ln in raw_lines[1:] if ln.strip()]
            if not 新内容:
                return "没有有效内容"
            代号表 = await self.star.store.read_json(f"{SHOP_REL}/商品代号.json", {}) or {}
            代号 = self._code_of(代号表, 商品名)
            if not 代号:
                return f"商品「{商品名}」不存在，请先添加"
            现有行 = await self._stock_lines(代号)
            待添加: list[str] = []
            与库重复: list[str] = []
            批次内重复: list[str] = []
            批次已见: set = set()
            for item in 新内容:
                if item in 现有行:
                    与库重复.append(item)
                    continue
                if item in 批次已见:
                    批次内重复.append(item)
                    continue
                批次已见.add(item)
                待添加.append(item)
            if not 待添加:
                return "没有可添加的新数据（已全部在库中或本批重复）"
            await self.star.store.write_text(f"{STOCK_REL}/{代号}.txt", "\n".join(现有行 + 待添加))
            回复 = f"已向商品「{商品名}」添加 {len(待添加)} 条数据"
            if 与库重复:
                回复 += f"，跳过与库存重复 {len(与库重复)} 条：{'、'.join(与库重复)}"
            if 批次内重复:
                回复 += f"；跳过本批重复 {len(批次内重复)} 条：{'、'.join(批次内重复)}"
            return 回复
        except Exception as e:
            logger.error(f"填充发卡商品异常: {e}")
            return "填充发卡商品执行出错，请查看日志"

    async def set_price(self, event: Any, args: str = ""):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            m = re.match(r"^([\s\S]+?)\s+(\d+)$", (args or "").strip())
            if not m:
                return "请按格式发送：\n发卡商品定价 商品名称 价格数字\n例：发卡商品定价 测试商品1 500"
            商品名, 价格 = m.group(1).strip(), int(m.group(2))
            代号表 = await self.star.store.read_json(f"{SHOP_REL}/商品代号.json", {}) or {}
            if 商品名 not in 代号表:
                return f"商品「{商品名}」不存在，请先添加发卡商品"
            await self.star.store.write_key(f"{SHOP_REL}/商品价格.json", 商品名, 价格)
            return f"已为「{商品名}」设定价格：{价格} 归笺"
        except Exception as e:
            logger.error(f"发卡商品定价异常: {e}")
            return "发卡商品定价执行出错，请查看日志"

    async def shelf(self, event: Any, name: str = "", on: bool = True):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            name = (name or "").strip()
            if not name:
                return "请按格式发送：\n发卡商品上架 商品名称"
            代号表 = await self.star.store.read_json(f"{SHOP_REL}/商品代号.json", {}) or {}
            if name not in 代号表:
                return f"商品「{name}」不存在"
            await self.star.store.write_key(f"{SHOP_REL}/商品上下架.json", name, bool(on))
            action = "上架（商店展示，可兑换）" if on else "下架（商店不展示，用户无法兑换）"
            return f"已将「{name}」设为{action}"
        except Exception as e:
            logger.error(f"发卡商品上下架异常: {e}")
            return "发卡商品上下架执行出错，请查看日志"

    async def clear_product(self, event: Any, name: str = ""):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            name = (name or "").strip()
            if not name:
                return "请指定商品名称"
            代号表 = await self.star.store.read_json(f"{SHOP_REL}/商品代号.json", {}) or {}
            代号 = self._code_of(代号表, name)
            if not 代号:
                return f"商品「{name}」不存在"
            if await self._stock_count(代号) == 0:
                return f"商品「{name}」还没有数据，无需清空"
            await self.star.store.write_text(f"{STOCK_REL}/{代号}.txt", "")
            return f"已清空商品「{name}」的所有数据"
        except Exception as e:
            logger.error(f"清空发卡商品异常: {e}")
            return "清空发卡商品执行出错，请查看日志"

    async def legacy(self, event: Any, message: str) -> Any:

        try:
            if message == "发卡系统":
                if not await self._authorized(event):
                    return None
                return (
                    "🎴 发卡系统 · 菜单总览\n══════════════\n"
                    "👤 用户指令\n - 发卡商店\n - 兑换商品 商品名称 数量\n"
                    "🔐 管理员指令（仅主人）\n - 添加发卡商品 名称\n"
                    " - 修改发卡商品 原名->新名\n - 填充发卡商品（首行商品名，下列每行一条卡密）\n"
                    " - 清空发卡商品 名称\n - 删除发卡商品（首行商品名，下列为要删的卡密行）\n"
                    " - 发卡商品定价 名称 价格数字\n - 发卡商品上架 名称 / 发卡商品下架 名称\n"
                    " - 读取发卡库存条数 名称"
                )
            if not await self._authorized(event):
                return None
            m = re.match(r"^修改发卡商品([\s\S]*?)->([\s\S]*)$", message)
            if m:
                if not await self.star.perm.check_admin(event):
                    return None
                原名称, 新名称 = m.group(1).strip(), m.group(2).strip()
                if not 原名称 or not 新名称:
                    return "请按格式发送：修改发卡商品 原名称->新名称"
                if 原名称 == 新名称:
                    return "原名称和新名称相同，无需修改"
                代号表 = await self.star.store.read_json(f"{SHOP_REL}/商品代号.json", {}) or {}
                if 原名称 not in 代号表:
                    return f"商品「{原名称}」不存在，无法修改"
                if 新名称 in 代号表:
                    return f"商品「{新名称}」已存在，请使用其他名称"
                原代号 = 代号表[原名称]
                代号表[新名称] = 原代号
                del 代号表[原名称]
                await self.star.store.write_json(f"{SHOP_REL}/商品代号.json", 代号表)
                上下架表 = await self.star.store.read_json(f"{SHOP_REL}/商品上下架.json", {}) or {}
                if 原名称 in 上下架表:
                    上下架表[新名称] = 上下架表[原名称]
                    del 上下架表[原名称]
                    await self.star.store.write_json(f"{SHOP_REL}/商品上下架.json", 上下架表)
                价格表 = await self.star.store.read_json(f"{SHOP_REL}/商品价格.json", {}) or {}
                if 原名称 in 价格表:
                    价格表[新名称] = 价格表[原名称]
                    del 价格表[原名称]
                    await self.star.store.write_json(f"{SHOP_REL}/商品价格.json", 价格表)
                return f"已将商品「{原名称}」更名为「{新名称}」，专属代号仍为 {原代号}"
            if message.startswith("删除发卡商品"):
                if not await self.star.perm.check_admin(event):
                    return None
                lines = (message or "").splitlines()
                if len(lines) < 2:
                    return "请按格式发送：\n删除发卡商品 商品名\n内容1\n内容2..."
                商品名 = lines[0].replace("删除发卡商品", "").strip()
                if not 商品名:
                    return "请指定商品名称"
                待删除 = [ln.strip() for ln in lines[1:] if ln.strip()]
                if not 待删除:
                    return "请在下方输入要删除的内容，每行一条"
                代号表 = await self.star.store.read_json(f"{SHOP_REL}/商品代号.json", {}) or {}
                代号 = self._code_of(代号表, 商品名)
                if not 代号:
                    return f"商品「{商品名}」不存在，请先添加"
                现有行 = await self._stock_lines(代号)
                删除成功: list[str] = []
                未找到: list[str] = []
                for item in 待删除:
                    if item in 现有行:
                        现有行.remove(item)
                        删除成功.append(item)
                    else:
                        未找到.append(item)
                await self.star.store.write_text(f"{STOCK_REL}/{代号}.txt", "\n".join(现有行))
                回复 = f"已从商品「{商品名}」中删除 {len(删除成功)} 条数据"
                if 删除成功:
                    回复 += f"\n成功删除：{'、'.join(删除成功)}"
                if 未找到:
                    回复 += f"\n未找到：{'、'.join(未找到)}"
                return 回复
            m = re.match(r"^读取发卡库存条数([\s\S]*)$", message)
            if m:
                if not await self.star.perm.check_admin(event):
                    return None
                商品名 = m.group(1).strip()
                代号表 = await self.star.store.read_json(f"{SHOP_REL}/商品代号.json", {}) or {}
                代号 = self._code_of(代号表, 商品名)
                if not 代号:
                    return f"商品「{商品名}」不存在"
                库存 = await self._stock_count(代号)
                return f"商品「{商品名}」当前库存 {库存} 条"
            return None
        except Exception as e:
            logger.error(f"发卡系统 legacy 异常: {e}")
            return None
