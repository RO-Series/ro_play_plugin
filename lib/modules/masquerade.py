"""马甲系统模块（MasqueradeModule）。

对应原 index.mjs 的以下功能：
- L16625「设置马甲内容[内容]」（1-18 字，写入本群马甲前缀）。
- L16655「全员马甲[内容]」：机器人需群管理权限，遍历群成员
  以「前缀+原名」批量 set_group_card；人数 ≥10 时每人冷却 1 秒；
  跳过机器人（group_member_list 的 user_id 与 raw self_id 比对）与原名已一致者；
  结束后合并转发输出 有效/无效/跳过 汇总。
- L17355 被动自动马甲（消息内自动改名）由本模块提供 apply 供复用。

数据：BaiXuan/群管系统/马甲系统/{群号}.json（纯文本，默认「天宫☆」）。

命名替换：路径前缀「BaiXuan」→「BaiXuan」，MKbot → RO_Play。
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Optional

from astrbot.api import logger

_MASQ_REL = "BaiXuan/群管系统/马甲系统"


class MasqueradeModule:
    """马甲系统：设置前缀与全员改名。"""

    def __init__(self, star) -> None:
        self.star = star
        self.store = star.store

    @staticmethod
    def _validate_prefix(prefix: str) -> Optional[str]:
        n = len(prefix)
        if n == 0 or n >= 19:
            return "请将内容控制在1 - 18个字之间！"
        return None

    # ==================== 指令方法（main.py 调用） ====================

    async def set_prefix(self, event, prefix: str = "") -> Any:
        """设置马甲内容：/设置马甲内容 前缀（原 L16625）。"""
        try:
            if not await self.star.perm.check_admin(event):
                return None
            gid = str(event.get_group_id() or "")
            if not gid:
                return None
            prefix = (prefix or "").strip()
            err = self._validate_prefix(prefix)
            if err:
                return err
            rel = f"{_MASQ_REL}/{gid}.json"
            cur = (await self.store.read_text(rel, "天宫☆") or "天宫☆").strip()
            if cur == prefix:
                return "与原来的一样啦！不可以重复设置哦～"
            await self.store.write_text(rel, prefix)
            return f"已将本群的马甲前缀改成「{prefix}」啦！"
        except Exception as e:  # noqa: BLE001
            logger.error(f"设置马甲内容失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    async def apply_all(self, event, prefix: str = "") -> Any:
        """全员马甲：/全员马甲 前缀（原 L16655）。"""
        try:
            if not await self.star.perm.check_admin(event):
                return None
            gid = str(event.get_group_id() or "")
            if not gid:
                return None
            prefix = (prefix or "").strip()
            err = self._validate_prefix(prefix)
            if err:
                return err
            # 机器人权限检查（需群管理以上）
            self_id = getattr(getattr(event, "message_obj", None), "self_id", None)
            if not self_id:
                return "获取机器人身份失败～"
            self_info = await self.star.api.get_group_member_info(gid, self_id)
            role = (self_info or {}).get("role", "member")
            if role not in ("owner", "admin"):
                return "窝没有权限改名唉～！"
            members = await self.star.api.get_group_member_list(gid)
            if not members:
                return "获取群聊成员失败！1"
            cooldown = len(members) >= 10
            head = "正在执行改名，切勿把机器人的权限给下了！！！"
            if cooldown:
                head += f"\n由于本群人数已达10人，将采取冷却措施\n预计在{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() + len(members)))}执行完毕"
                await self.star.sender.send_reply(event, head)
            self_id_s = str(self_id)
            ok_list: list = []
            skip_list: list = []
            fail_list: list = []
            for i, m in enumerate(members or []):
                user_id = str(m.get("user_id") or "")
                is_robot = bool(m.get("is_robot")) or user_id == self_id_s
                nickname = str(m.get("nickname") or "")
                card = str(m.get("card") or "")
                wanted = prefix + nickname
                if card == wanted:
                    skip_list.append(user_id)
                elif is_robot or not user_id:
                    fail_list.append(user_id)
                else:
                    ok_flag = await self.star.api.call(
                        "set_group_card", group_id=gid, user_id=user_id, card=wanted
                    )
                    if ok_flag:
                        ok_list.append(user_id)
                    else:
                        fail_list.append(user_id)
                if cooldown:
                    await asyncio.sleep(1)
            await self.store.write_text(f"{_MASQ_REL}/{gid}.json", prefix)
            lines = [
                "「全员马甲」- 数据直接:",
                "══════════════",
                f"有效人次：{len(ok_list)}",
                f"无效人次：{len(fail_list)}",
                f"跳过人次：{len(skip_list)}",
            ]
            nodes = [
                self.star.sender.build_node("数据总结", event.get_sender_id(), "\n".join(lines)),
                self.star.sender.build_node("【有效人次 - 列表】", event.get_sender_id(),
                                           "1️⃣ - 有效列表\n══════════════" + "".join(f"\n{i + 1}.{uid}" for i, uid in enumerate(ok_list)) + "\n══════════════"),
                self.star.sender.build_node("【无效人次 - 列表】", event.get_sender_id(),
                                           "2️⃣ - 无效列表\n══════════════" + "".join(f"\n{i + 1}.{uid}" for i, uid in enumerate(fail_list)) + "\n══════════════"),
                self.star.sender.build_node("【跳过人次 - 列表】", event.get_sender_id(),
                                           "3️⃣ - 跳过列表\n══════════════" + "".join(f"\n{i + 1}.{uid}" for i, uid in enumerate(skip_list)) + "\n══════════════"),
            ]
            await self.star.sender.send_forward(event, nodes)
            return None
        except Exception as e:  # noqa: BLE001
            logger.error(f"全员马甲失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    # ==================== 无前缀 legacy ====================

    async def legacy(self, event, message: str) -> Any:
        """正则匹配无前缀马甲指令（原 L16625/L16655）。"""
        try:
            m = re.match(r"^设置马甲内容([\s\S]*)$", message)
            if m:
                return await self.set_prefix(event, m.group(1).strip())
            m = re.match(r"^全员马甲([\s\S]*)$", message)
            if m:
                return await self.apply_all(event, m.group(1).strip())
        except Exception as e:  # noqa: BLE001
            logger.error(f"马甲 legacy 异常: {e}")
        return None
