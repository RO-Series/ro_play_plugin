"""续火系统模块（FirekeepModule）。

对应原 index.mjs 的以下功能：
- L13876「设置续火内容[内容]」、L13895「设置续火模式[文案|图片]」。
- L13912「(开启|关闭)(好友续火|群聊续火|全部好友续火|全部群聊续火)[目标]」。
- L13998「管理续火」——统计全部群聊 / 好友的续火开关状态并合并转发展示。

数据：
- BaiXuan/扩展功能/续火功能/续火内容/文本.txt（续火文案）
- BaiXuan/扩展功能/续火功能/续火方式/方式.txt（文案|图片）
- BaiXuan/扩展功能/续火功能/状态数据/好友/开关.json（{QQ: bool}）
- BaiXuan/事件系统/全局.json（好友续火总开关）
- 群聊续火开关经 star.group_event_enabled / star.set_group_event(gid, "group_fire", bool)
  读写 BaiXuan/事件系统/{群号}.json。

命名替换：路径前缀「筱筱吖」→「BaiXuan」，MKbot → RO_Play。
"""
from __future__ import annotations

import re
from typing import Any

from astrbot.api import logger

_TEXT_REL = "BaiXuan/扩展功能/续火功能/续火内容/文本.txt"
_MODE_REL = "BaiXuan/扩展功能/续火功能/续火方式/方式.txt"
_FRIEND_SWITCH_REL = "BaiXuan/扩展功能/续火功能/状态数据/好友/开关.json"


class FirekeepModule:
    """续火系统：设置内容 / 模式、开关管理与状态总览。"""

    def __init__(self, star) -> None:
        self.star = star
        self.store = star.store

    # ==================== 指令方法（main.py 调用） ====================

    async def set_content(self, event, content: str = "") -> Any:
        """设置续火内容：/设置续火内容 内容（原 L13876）。"""
        try:
            if not await self.star.perm.check_owner(event):
                return "你不是主人哦～"
            content = (content or "").strip()
            if not content:
                return "至少要一个字哦～！"
            await self.store.write_text(_TEXT_REL, content)
            return f"好哒！这就把续火的内容改成:\n{content}"
        except Exception as e:  # noqa: BLE001
            logger.error(f"设置续火内容失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    async def set_mode(self, event, mode: str = "") -> Any:
        """设置续火模式：/设置续火模式 文案|图片（原 L13895）。"""
        try:
            if not await self.star.perm.check_owner(event):
                return "你不是主人哦～"
            mode = (mode or "").strip()
            if mode not in ("文案", "图片"):
                return "模式仅支持【文案】或【图片】哦～"
            cur = (await self.store.read_text(_MODE_REL, "文案") or "文案").strip()
            if cur == mode:
                return f"现在的续火已经是【{mode}】模式啦～！"
            await self.store.write_text(_MODE_REL, mode)
            return f"好哒！这就把续火的发送方式改成【{mode}】哦！～"
        except Exception as e:  # noqa: BLE001
            logger.error(f"设置续火模式失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    async def manage(self, event) -> Any:
        """续火状态总览：/管理续火（原 L13998）。"""
        try:
            groups = await self.star.api.get_group_list()
            friends = await self.star.api.get_friend_list()
            g_on, g_off = [], []
            for g in groups or []:
                gid = str(g.get("group_id") or "")
                if await self.star.group_event_enabled(gid, "group_fire"):
                    g_on.append(f"{g.get('group_name', '')}({gid})✅")
                else:
                    g_off.append(f"{g.get('group_name', '')}({gid})❌")
            f_on, f_off = [], []
            switch = await self.store.read_json(_FRIEND_SWITCH_REL, {}) or {}
            for f in friends or []:
                uid = str(f.get("user_id") or "")
                if switch.get(uid):
                    f_on.append(f"{f.get('nickname', '')}({uid})✅")
                else:
                    f_off.append(f"{f.get('nickname', '')}({uid})❌")
            block0 = "══════════════\n相关事件【群聊续火】\n相关事件【好友续火】\n\n「全局共同」\n - 设置续火内容[内容]\n - 设置续火模式[文案|图片]\n\n「开关控制」\n - [开启|关闭]好友续火[QQ号]\n - [开启|关闭]群聊续火[群号]\n - [开启|关闭]全部好友续火\n - [开启|关闭]全部群聊续火\n══════════════"
            block1 = f"共计有【{len(groups)}】个群聊\n其中有【{len(g_on)}】个群聊为「开启」\n══════════════" + "\n".join(
                f"{i + 1}. {x}" for i, x in enumerate(g_on)
            )
            block2 = f"反之有【{len(g_off)}】个群聊为「关闭」\n══════════════" + "\n".join(
                f"{i + 1}. {x}" for i, x in enumerate(g_off)
            )
            block3 = f"共计有【{len(friends)}】个好友\n其中有【{len(f_on)}】个好友为「开启」\n══════════════" + "\n".join(
                f"{i + 1}. {x}" for i, x in enumerate(f_on)
            )
            block4 = f"反之有【{len(f_off)}】个好友为「关闭」\n══════════════" + "\n".join(
                f"{i + 1}. {x}" for i, x in enumerate(f_off)
            )
            nodes = [
                self.star.sender.build_node("[管理续火]", event.get_sender_id(), block0),
                self.star.sender.build_node("[管理续火]", event.get_sender_id(), block1),
                self.star.sender.build_node("[管理续火]", event.get_sender_id(), block2),
                self.star.sender.build_node("[管理续火]", event.get_sender_id(), block3),
                self.star.sender.build_node("[管理续火]", event.get_sender_id(), block4),
            ]
            await self.star.sender.send_forward(event, nodes)
            return None
        except Exception as e:  # noqa: BLE001
            logger.error(f"管理续火失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    # ==================== 无前缀 legacy ====================

    async def legacy(self, event, message: str) -> Any:
        """正则匹配无前缀续火指令（原 L13876/L13912/L13998）。"""
        try:
            if not await self.star.perm.check_owner(event):
                return None
            m = re.match(r"^设置(续火)内容([\s\S]*)$", message)
            if m:
                return await self.set_content(event, m.group(2).strip())
            m = re.match(r"^设置(续火)模式(文案|图片)$", message)
            if m:
                return await self.set_mode(event, m.group(2))
            if message == "管理续火":
                return await self.manage(event)
            m = re.match(r"^(开启|关闭)(好友续火|群聊续火|全部好友续火|全部群聊续火)([0-9]+|)$", message)
            if m:
                return await self._switch(event, m.group(1), m.group(2), m.group(3))
        except Exception as e:  # noqa: BLE001
            logger.error(f"续火 legacy 异常: {e}")
        return None

    async def _switch(self, event, operation: str, kind: str, target: str) -> Any:
        """开关处理：单个目标 或 全部目标（原 L13912）。"""
        enable = operation == "开启"
        if kind == "好友续火":
            if not target or len(target) <= 3:
                return "好友续火需要携带 QQ 号哦～"
            switch = await self.store.read_json(_FRIEND_SWITCH_REL, {}) or {}
            if bool(switch.get(target)) == enable:
                return f"目前「{target}」已经是【{operation}】状态的啦！"
            switch[target] = enable
            await self.store.write_json(_FRIEND_SWITCH_REL, switch)
            return f"好哒！这就把「{target}」的续🔥开关给【{operation}】"
        if kind == "群聊续火":
            if not target or len(target) <= 3:
                return "群聊续火需要携带群号哦～"
            if await self.star.group_event_enabled(target, "group_fire") == enable:
                return f"目前「{target}」已经是【{operation}】状态的啦！"
            await self.star.set_group_event(target, "group_fire", enable)
            return f"好哒！这就把「{target}」的续🔥开关给【{operation}】"
        # 全部
        if kind == "全部好友续火":
            friends = await self.star.api.get_friend_list()
            if not friends:
                return "获取【好友】列表失败！"
            switch = await self.store.read_json(_FRIEND_SWITCH_REL, {}) or {}
            lines = [f"已将【{len(friends)}】位好友统一设为「{operation}」"]
            for i, f in enumerate(friends, 1):
                uid = str(f.get("user_id") or "")
                if bool(switch.get(uid)) == enable:
                    lines.append(f"{i}. {uid}❌本就{operation}")
                else:
                    switch[uid] = enable
                    lines.append(f"{i}. {uid}✅这就{operation}")
            await self.store.write_json(_FRIEND_SWITCH_REL, switch)
            return await self._maybe_forward(event, "\n".join(lines))
        # 全部群聊
        groups = await self.star.api.get_group_list()
        if not groups:
            return "获取【群聊】列表失败！"
        lines = [f"已将【{len(groups)}】个群聊统一设为「{operation}」"]
        for i, g in enumerate(groups, 1):
            gid = str(g.get("group_id") or "")
            if await self.star.group_event_enabled(gid, "group_fire") == enable:
                lines.append(f"{i}. {gid}❌本就{operation}")
            else:
                await self.star.set_group_event(gid, "group_fire", enable)
                lines.append(f"{i}. {gid}✅这就{operation}")
        return await self._maybe_forward(event, "\n".join(lines))

    async def _maybe_forward(self, event, text: str) -> Any:
        """数量多时以合并转发发送，否则直接返回文本。"""
        if len(text.splitlines()) >= 15:
            nodes = [self.star.sender.build_node("[续火]", event.get_sender_id(), text)]
            await self.star.sender.send_forward(event, nodes)
            return None
        return text
