from __future__ import annotations

import re
from typing import Any

from astrbot.api import logger

_BLACKLIST_GLOBAL = "BaiXuan/群管系统/黑白名单/全局"
_BANNED_WORDS = "BaiXuan/群管系统/违禁系统"
_MSG_TYPE_MAP = {
    "图片": ["image"],
    "视频": ["video"],
    "语音": ["record"],
    "卡片": ["json", "xml"],
    "合并转发": ["forward"],
}

class BlacklistModule:

    def __init__(self, star) -> None:
        self.star = star
        self.store = star.store

    async def add_blacklist(self, gid: str, uid: str) -> None:

        try:
            rel = f"{_BLACKLIST_GLOBAL}/群聊/{gid}/人员.json"
            data = await self.store.read_json(rel, []) or []
            if not isinstance(data, list):
                data = []
            uid_s = str(uid)
            if uid_s not in [str(x) for x in data]:
                data.append(uid_s)
                await self.store.write_json(rel, data)
        except Exception as e:
            logger.error(f"添加黑名单失败: {e}")

    async def is_blacklisted(self, gid: str, uid: str) -> bool:

        try:
            uid_s = str(uid)
            global_list = await self.store.read_json(f"{_BLACKLIST_GLOBAL}/人员.json", []) or []
            group_list = await self.store.read_json(f"{_BLACKLIST_GLOBAL}/群聊/{gid}/人员.json", []) or []
            return uid_s in [str(x) for x in global_list] or uid_s in [str(x) for x in group_list]
        except Exception as e:
            logger.error(f"黑名单判断失败: {e}")
            return False

    async def check_message(self, event) -> None:

        try:
            gid = str(event.get_group_id() or "")
            if not gid:
                return
            uid = str(event.get_sender_id())
            if self.star.perm.is_owner(uid):
                return
            if not await self._can_punish(event):
                return
            message_id = getattr(event.message_obj, "message_id", None) or getattr(event, "message_id", None)
            text = (event.message_str or "").strip()
            msg_types = self._collect_msg_types(event)

            if text:
                words = await self.store.read_json(f"{_BANNED_WORDS}/{gid}/违禁词.json", []) or []
                hit = any(word and str(word) in text for word in words)
                if hit:
                    await self._apply_handle(event, gid, uid, message_id)
                    return

            banned = await self.store.read_json(f"{_BANNED_WORDS}/{gid}/禁发管理.json", {}) or {}
            for seg_type in msg_types:
                if banned.get(seg_type):
                    await self._delete_msg(message_id)
                    return
        except Exception as e:
            logger.error(f"违禁检测失败: {e}")

    async def _apply_handle(self, event, gid: str, uid: str, message_id: Any) -> None:

        handle = await self.store.read_json(f"{_BANNED_WORDS}/{gid}/处理.json", {}) or {}
        mode = str(handle.get("方式", "撤回"))
        duration = int(handle.get("时长", 600) or 600)
        if mode == "禁言":
            await self.star.api.call("set_group_ban", group_id=gid, user_id=uid, duration=duration)
        elif mode == "撤回":
            await self._delete_msg(message_id)
        else:
            await self.star.api.call("set_group_ban", group_id=gid, user_id=uid, duration=duration)
            await self._delete_msg(message_id)

    async def _delete_msg(self, message_id: Any) -> None:
        if not message_id:
            return
        try:
            await self.star.api.call("delete_msg", message_id=message_id)
        except Exception as e:
            logger.warning(f"撤回消息失败: {e}")

    async def _can_punish(self, event) -> bool:

        try:
            gid = event.get_group_id()
            if not gid:
                return True
            self_id = getattr(getattr(event, "message_obj", None), "self_id", None)
            if not self_id:
                return True
            uid = event.get_sender_id()
            self_info = await self.star.api.get_group_member_info(gid, self_id)
            user_info = await self.star.api.get_group_member_info(gid, uid)
            role_lv = {"owner": 3, "admin": 2, "member": 1, "unknown": 0}
            self_lv = role_lv.get((self_info or {}).get("role", "member"), 1)
            user_lv = role_lv.get((user_info or {}).get("role", "member"), 1)
            return self_lv > user_lv
        except Exception as e:
            logger.warning(f"权限等级判断失败: {e}")
            return True

    def _collect_msg_types(self, event) -> list:

        types: list = []
        try:
            for seg in getattr(event, "message", None) or []:
                name = type(seg).__name__.lower()
                t = str(getattr(seg, "type", "") or "").lower()
                key = t or name
                if key in ("image", "video", "record", "json", "xml", "forward", "file"):
                    types.append(key)
        except Exception as e:
            logger.warning(f"读取消息类型失败: {e}")
        if not types:
            text = event.message_str or ""
            for key, cq in (("image", "[CQ:image"), ("video", "[CQ:video"), ("record", "[CQ:record"),
                            ("json", "[CQ:json"), ("xml", "[CQ:xml"), ("forward", "[CQ:forward")):
                if cq in text:
                    types.append(key)
        return list(dict.fromkeys(types))

    async def legacy(self, event, message: str) -> Any:

        try:
            gid = str(event.get_group_id() or "")
            if not gid:
                return None
            m = re.match(r"^设置(全局|本群|)黑名单处理(踢出|黑踢)$", message)
            if m:
                return await self._set_blacklist_handle(event, m.group(1) or "本群", m.group(2))
            m = re.match(r"^(全局|本群|)黑名单列表$", message)
            if m:
                return await self._blacklist_list(event, m.group(1) or "本群")
            m = re.match(r"^查黑名单([0-9]+)$", message)
            if m:
                return await self._query_blacklist(event, m.group(1))
            m = re.match(r"^(添加|删除|清空)(全局|本群|)黑名单([\s\S]*)$", message)
            if m:
                return await self._modify_blacklist(event, m.group(1), m.group(2) or "本群", m.group(3))
            m = re.match(r"^设置违禁处理(禁言|撤回禁言|撤回|禁言时长)([0-9]+|)$", message)
            if m:
                return await self._set_banned_handle(event, m.group(1), m.group(2))
            m = re.match(r"^(增加|新增|添加|删除|取消|减少|清空)违禁词([\s\S]*)$", message)
            if m:
                return await self._modify_banned_word(event, m.group(1), m.group(2))
            if message == "违禁词列表":
                return await self._banned_word_list(event)
            m = re.match(r"^(开启|关闭)禁发(图片|视频|语音|卡片|合并转发)$", message)
            if m:
                return await self._toggle_banned_send(event, m.group(1), m.group(2))
        except Exception as e:
            logger.error(f"黑名单 legacy 异常: {e}")
        return None

    def _bl_paths(self, gid: str, scope: str) -> tuple:
        if scope == "全局":
            return f"{_BLACKLIST_GLOBAL}/人员.json", f"{_BLACKLIST_GLOBAL}/处理方式.json"
        return f"{_BLACKLIST_GLOBAL}/群聊/{gid}/人员.json", f"{_BLACKLIST_GLOBAL}/群聊/{gid}/处理方式.json"

    async def _set_blacklist_handle(self, event, scope: str, mode: str) -> Any:
        if not await self.star.perm.check_admin(event):
            return None
        if scope == "全局" and not await self.star.perm.check_owner(event):
            return "全局黑名单仅主人可设置～"
        gid = str(event.get_group_id() or "")
        _, handle_rel = self._bl_paths(gid, scope)
        cur = await self.store.read_key(handle_rel, "方式", "踢出")
        if cur == mode:
            return f"目前的「{scope}」黑名单处理方式已经是【{cur}】啦！"
        await self.store.write_key(handle_rel, "方式", mode)
        return f"好哒！这就把「{scope}」黑名单的处理方式变为【{mode}】！"

    async def _blacklist_list(self, event, scope: str) -> Any:
        if not await self.star.perm.check_admin(event):
            return None
        if scope == "全局" and not await self.star.perm.check_owner(event):
            return "全局黑名单仅主人可查看～"
        gid = str(event.get_group_id() or "")
        people_rel, _ = self._bl_paths(gid, scope)
        data = await self.store.read_json(people_rel, []) or []
        data = [str(x) for x in data if str(x)]
        if not data:
            return f"我好像没找到「{scope}」黑名单的人唉～？是不是没有啊～"
        lines = [f"当前选择【{scope}】黑名单", f"共计人数【{len(data)}】", "══════════════"]
        lines += [f"{i + 1}.【{x}】" for i, x in enumerate(data)]
        lines.append("══════════════")
        text = "\n".join(lines)
        if len(data) >= 15:
            nodes = [self.star.sender.build_node("[黑名单列表]", event.get_sender_id(), text)]
            await self.star.sender.send_forward(event, nodes)
            return None
        return text

    async def _query_blacklist(self, event, uid: str) -> Any:
        gid = str(event.get_group_id() or "")
        global_list = await self.store.read_json(f"{_BLACKLIST_GLOBAL}/人员.json", []) or []
        group_list = await self.store.read_json(f"{_BLACKLIST_GLOBAL}/群聊/{gid}/人员.json", []) or []
        in_g = str(uid) in [str(x) for x in global_list]
        in_s = str(uid) in [str(x) for x in group_list]
        return (
            "黑名单 查询结果:\n══════════════\n"
            f"查询目标：{uid}\n[全局黑名单]：{in_g}\n[本群黑名单]：{in_s}\n══════════════"
        )

    async def _modify_blacklist(self, event, operation: str, scope: str, tail: str) -> Any:
        if not await self.star.perm.check_admin(event):
            return None
        if scope == "全局" and not await self.star.perm.check_owner(event):
            return "全局黑名单仅主人可操作～"
        gid = str(event.get_group_id() or "")
        people_rel, handle_rel = self._bl_paths(gid, scope)
        data = await self.store.read_json(people_rel, []) or []
        if not isinstance(data, list):
            data = []
        data = [str(x) for x in data if str(x)]
        mode = await self.store.read_key(handle_rel, "方式", "踢出")
        reject = mode != "踢出"
        if operation == "清空":
            await self.store.write_json(people_rel, [])
            return f"好叭～这就把「{scope}」黑名单给清空～～"

        at_users = re.findall(r"\[CQ:at,qq=(\d+)\]", tail)
        content = re.sub(r"\[CQ:at,qq=\d+\]", "", tail).strip()
        targets = list(dict.fromkeys(at_users))
        if not targets and content.isdigit():
            targets = [content]
        if not targets:
            return "❌操作无效！内容非艾特也非数值！"
        lines = []
        changed = False
        for uid in targets:
            if operation in ("添加", "新增"):
                if uid in data:
                    lines.append(f"【{uid}】❌已存在")
                else:
                    data.append(uid)
                    lines.append(f"【{uid}】✅新增")
                    changed = True
            else:
                if uid not in data:
                    lines.append(f"【{uid}】❌不存在")
                else:
                    data = [x for x in data if x != uid]
                    lines.append(f"【{uid}】✅删除")
                    changed = True
        if changed:
            await self.store.write_json(people_rel, data)
        head = f"已把下列人员添加至【{scope}】黑名单列表" if operation in ("添加", "新增") else f"已把下列人员尝试从【{scope}】黑名单列表中移除"
        text = f"{head}\n══════════════\n" + "\n".join(lines) + "\n══════════════"

        if operation in ("添加", "新增") and changed:
            await self.star.api.call("set_group_kick", group_id=gid, user_id=targets[-1], reject_add_request=reject)
        if len(targets) >= 15:
            nodes = [self.star.sender.build_node("[黑名单操作]", event.get_sender_id(), text)]
            await self.star.sender.send_forward(event, nodes)
            return None
        return text

    async def _set_banned_handle(self, event, mode: str, sec: str) -> Any:
        if not await self.star.perm.check_admin(event):
            return None
        gid = str(event.get_group_id() or "")
        handle_rel = f"{_BANNED_WORDS}/{gid}/处理.json"
        if mode == "禁言时长":
            if not sec or not sec.isdigit():
                return "在设置违禁禁言时长时，需要携带时间数量哦(秒)"
            duration = min(int(sec), 2592000)
            await self.store.write_key(handle_rel, "时长", duration)
            return f"好哒！这就把违禁词的禁言时长改成【{sec}】秒！"
        cur = await self.store.read_key(handle_rel, "方式", "撤回")
        if cur == mode:
            return f"现在已经是【{cur}】的处理方式啦！补药再改啦！"
        await self.store.write_key(handle_rel, "方式", mode)
        return f"好哒～！这就把违禁词的处理方式改成【{mode}】\n下一次即可触发了哦～"

    async def _modify_banned_word(self, event, operation: str, word: str) -> Any:
        if not await self.star.perm.check_admin(event):
            return None
        gid = str(event.get_group_id() or "")
        rel = f"{_BANNED_WORDS}/{gid}/违禁词.json"
        data = await self.store.read_json(rel, []) or []
        if not isinstance(data, list):
            data = []
        word = (word or "").strip()
        if operation in ("增加", "新增", "添加"):
            if not word:
                return "违禁词内容不能为空～"
            if word in data:
                return "emmmm，介个违禁词好像也就有了哎～"
            data.append(word)
            await self.store.write_json(rel, data)
            return f"我这就去添加违禁词！\n【新增】: {word}"
        if operation in ("删除", "取消", "减少"):
            if word not in data:
                return "额，介个违禁词好像没有吧，我都找不到～～"
            data = [x for x in data if x != word]
            await self.store.write_json(rel, data)
            return f"我这就去把介个违禁词给ban了！\n【删除】: {word}"
        if operation == "清空":
            await self.store.write_json(rel, [])
            return "耗的，这就就把违禁词通通删除！"
        return None

    async def _banned_word_list(self, event) -> Any:
        gid = str(event.get_group_id() or "")
        rel = f"{_BANNED_WORDS}/{gid}/违禁词.json"
        data = await self.store.read_json(rel, []) or []
        if not data:
            return "介个群好像木有添加违禁词哎"
        handle_rel = f"{_BANNED_WORDS}/{gid}/处理.json"
        mode = await self.store.read_key(handle_rel, "方式", "撤回")
        duration = await self.store.read_key(handle_rel, "时长", 600)
        lines = [f"共计【{len(data)}】个违禁词", f"当前处理方式 :【{mode}】", f"当前禁言时长 :【{duration}秒】", "══════════════"]
        lines += [f"【{i + 1}】: {w}" for i, w in enumerate(data)]
        lines.append("══════════════")
        text = "\n".join(lines)
        if len(data) >= 10:
            nodes = [self.star.sender.build_node("[违禁词列表]", event.get_sender_id(), text)]
            await self.star.sender.send_forward(event, nodes)
            return None
        return text

    async def _toggle_banned_send(self, event, operation: str, target: str) -> Any:
        if not await self.star.perm.check_admin(event):
            return None
        gid = str(event.get_group_id() or "")
        keys = _MSG_TYPE_MAP.get(target, [])
        if not keys:
            return None
        rel = f"{_BANNED_WORDS}/{gid}/禁发管理.json"
        conf = await self.store.read_json(rel, {}) or {}
        enable = operation == "开启"
        if all(bool(conf.get(k)) == enable for k in keys):
            return f"【禁发{target}】已经是{operation}状态啦～"
        for k in keys:
            conf[k] = enable
        await self.store.write_json(rel, conf)
        return f"好哒！本群【禁发{target}】已{operation}～"
