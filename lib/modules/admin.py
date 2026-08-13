from __future__ import annotations

import re
import time
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger

from lib.cqcode import cq_at_all

GROUP_EVENTS: list[str] = [
    "禁言通知", "入群审核", "邀人统计", "自助头衔", "伪造聊天", "黑白名单",
    "退群拉黑", "退群通知", "整点报时", "禁发红包", "入群欢迎", "违禁检测",
    "进阶检测", "发言统计", "群聊续火", "视频解析", "问答系统", "管理模式",
    "入群验证", "马甲系统", "入群私聊",
]

GLOBAL_EVENTS: list[str] = ["全群打卡", "自动点赞", "好友续火", "自动备份", "受邀同意"]

_BROADCAST_RE = re.compile(r"^☆?\s*执行群发(?:公告|文本)([\s\S]*)$")

def _time_a(fmt: str, ts: int | None = None) -> str:
    t = time.localtime(int(time.time()) if ts is None else int(ts))
    table = {
        "y": f"{t.tm_year:04d}", "m": f"{t.tm_mon:02d}", "d": f"{t.tm_mday:02d}",
        "H": f"{t.tm_hour:02d}", "i": f"{t.tm_min:02d}", "s": f"{t.tm_sec:02d}",
    }
    out = fmt
    for k, v in table.items():
        out = out.replace(k, v)
    return out

class AdminModule:

    def __init__(self, star: Any) -> None:
        self.star = star

    def _at_targets(self, event: Any) -> list[str]:

        targets: list[str] = []
        try:
            for seg in event.get_messages() or []:
                if isinstance(seg, Comp.At):
                    qq = getattr(seg, "qq", "")
                    if qq and str(qq) not in ("all", ""):
                        targets.append(str(qq))
        except Exception as e:
            logger.warning(f"提取 @ 目标失败: {e}")
        return targets

    def _plain_text(self, event: Any) -> str:
        parts = []
        try:
            for seg in event.get_messages() or []:
                if isinstance(seg, Comp.Plain):
                    parts.append(str(getattr(seg, "text", "")))
        except Exception:
            pass
        return "".join(parts)

    async def _bot_role(self, event: Any, gid: Any) -> int:

        try:
            self_id = getattr(event.message_obj, "self_id", None) if event.message_obj else None
            if not self_id:
                return 1
            info = await self.star.api.get_group_member_info(gid, self_id)
            if not info:
                return 1
            role = info.get("role", "member")
            return {"owner": 3, "admin": 2, "member": 1}.get(role, 1)
        except Exception as e:
            logger.warning(f"获取机器人群角色失败: {e}")
            return 1

    async def _target_role(self, gid: Any, uid: Any) -> int:
        try:
            info = await self.star.api.get_group_member_info(gid, uid)
            if not info:
                return 1
            role = info.get("role", "member")
            return {"owner": 3, "admin": 2, "member": 1}.get(role, 1)
        except Exception as e:
            logger.warning(f"获取目标群角色失败: {e}")
            return 1

    async def _add_blacklist(self, gid: Any, uid: Any) -> None:

        try:
            mod = self.star.modules.get("blacklist")
            if mod and hasattr(mod, "add_blacklist"):
                await mod.add_blacklist(gid, uid)
        except Exception as e:
            logger.error(f"拉黑失败: {e}")

    async def mute(self, event: Any, seconds: int = 60):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            gid = event.get_group_id()
            if not gid:
                return "该功能仅支持群聊使用哦～"
            targets = self._at_targets(event)
            if not targets:
                return "请 @ 目标成员哦～"
            lines = []
            ok = 0
            for uid in targets:
                if await self._target_role(gid, uid) >= 3:
                    lines.append(f"❌{uid}:权限不足")
                    continue
                done = await self.star.api.call(
                    "set_group_ban", group_id=gid, user_id=uid, duration=int(seconds)
                )
                if done:
                    lines.append(f"✅{uid}:禁言{seconds}秒")
                    ok += 1
                else:
                    lines.append(f"❌{uid}:执行失败")
            head = f"已对【{ok}】人有效禁言啦～\n══════════════\n" + "\n".join(lines)
            return head
        except Exception as e:
            logger.error(f"禁言异常: {e}")
            return "禁言执行出错，请查看日志"

    async def unmute(self, event: Any):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            gid = event.get_group_id()
            if not gid:
                return "该功能仅支持群聊使用哦～"
            targets = self._at_targets(event)
            if not targets:
                return "请 @ 目标成员哦～"
            lines = []
            ok = 0
            for uid in targets:
                done = await self.star.api.call(
                    "set_group_ban", group_id=gid, user_id=uid, duration=0
                )
                if done:
                    lines.append(f"✅{uid}:解禁成功")
                    ok += 1
                else:
                    lines.append(f"❌{uid}:执行失败")
            return f"已对【{ok}】人有效解禁啦～\n══════════════\n" + "\n".join(lines)
        except Exception as e:
            logger.error(f"解禁异常: {e}")
            return "解禁执行出错，请查看日志"

    async def kick(self, event: Any):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            gid = event.get_group_id()
            if not gid:
                return "该功能仅支持群聊使用哦～"
            targets = self._at_targets(event)
            if not targets:
                return "请 @ 目标成员哦～"
            lines = []
            ok = 0
            for uid in targets:
                if await self._target_role(gid, uid) >= 3:
                    lines.append(f"❌{uid}:权限不足")
                    continue
                done = await self.star.api.call("set_group_kick", group_id=gid, user_id=uid)
                if done:
                    lines.append(f"✅{uid}:普通踢出")
                    ok += 1
                else:
                    lines.append(f"❌{uid}:执行失败")
            return f"已对【{ok}】人有效踢出啦～\n══════════════\n" + "\n".join(lines)
        except Exception as e:
            logger.error(f"踢出异常: {e}")
            return "踢出执行出错，请查看日志"

    async def black_kick(self, event: Any):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            gid = event.get_group_id()
            if not gid:
                return "该功能仅支持群聊使用哦～"
            targets = self._at_targets(event)
            if not targets:
                return "请 @ 目标成员哦～"
            lines = []
            ok = 0
            for uid in targets:
                if await self._target_role(gid, uid) >= 3:
                    lines.append(f"❌{uid}:权限不足")
                    continue
                done = await self.star.api.call(
                    "set_group_kick", group_id=gid, user_id=uid, reject_add_request=True
                )
                await self._add_blacklist(gid, uid)
                if done:
                    lines.append(f"✅{uid}:拉黑踢出")
                    ok += 1
                else:
                    lines.append(f"❌{uid}:执行失败")
            return f"已对【{ok}】人有效黑踢啦～\n══════════════\n" + "\n".join(lines)
        except Exception as e:
            logger.error(f"黑踢异常: {e}")
            return "黑踢执行出错，请查看日志"

    async def whole_ban(self, event: Any, enable: bool = True):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            gid = event.get_group_id()
            if not gid:
                return "该功能仅支持群聊使用哦～"
            done = await self.star.api.call("set_group_whole_ban", group_id=gid, enable=bool(enable))
            if not done:
                return "执行失败，可能机器人没有群管权限唉～"
            return "这就把全体禁言给打开，让大家都不能说话！" if enable else "大家又可以说话啦！"
        except Exception as e:
            logger.error(f"全体禁言异常: {e}")
            return "全体禁言执行出错，请查看日志"

    async def promote(self, event: Any):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            gid = event.get_group_id()
            if not gid:
                return "该功能仅支持群聊使用哦～"
            if await self._bot_role(event, gid) < 3:
                return "窝没有群主权限唉～"
            targets = self._at_targets(event)
            if not targets:
                return "请 @ 目标成员哦～"
            lines = []
            ok = 0
            for uid in targets:
                if await self._target_role(gid, uid) >= 2:
                    lines.append(f"❌{uid}:已经是啦")
                    continue
                done = await self.star.api.call(
                    "set_group_admin", group_id=gid, user_id=uid, enable=True
                )
                if done:
                    lines.append(f"✅{uid}:新上位")
                    ok += 1
                else:
                    lines.append(f"❌{uid}:执行失败")
            return f"已对【{ok}】人有效上管啦～\n══════════════\n" + "\n".join(lines)
        except Exception as e:
            logger.error(f"上管异常: {e}")
            return "上管执行出错，请查看日志"

    async def demote(self, event: Any):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            gid = event.get_group_id()
            if not gid:
                return "该功能仅支持群聊使用哦～"
            if await self._bot_role(event, gid) < 3:
                return "窝没有群主权限唉～"
            targets = self._at_targets(event)
            if not targets:
                return "请 @ 目标成员哦～"
            lines = []
            ok = 0
            for uid in targets:
                if await self._target_role(gid, uid) < 2:
                    lines.append(f"❌{uid}:已就不是")
                    continue
                done = await self.star.api.call(
                    "set_group_admin", group_id=gid, user_id=uid, enable=False
                )
                if done:
                    lines.append(f"✅{uid}:被下台了")
                    ok += 1
                else:
                    lines.append(f"❌{uid}:执行失败")
            return f"已对【{ok}】人有效下管啦～\n══════════════\n" + "\n".join(lines)
        except Exception as e:
            logger.error(f"下管异常: {e}")
            return "下管执行出错，请查看日志"

    async def ban_list(self, event: Any):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            gid = event.get_group_id()
            if not gid:
                return "该功能仅支持群聊使用哦～"
            result = await self.star.api.call_result("get_group_shut_list", group_id=gid)
            items = result.get("data", []) if isinstance(result, dict) else result or []
            count = len(items) if isinstance(items, list) else 0
            if count == 0:
                return "没有人被禁言啦～"
            lines = [f"共有【{count}】人处于禁言状态:", "══════════════"]
            for i, item in enumerate(items):
                qq = item.get("uin", "0")
                nick = item.get("nick", "")
                end = _time_a("y-m-d H:i:s", item.get("shutUpTime", 0))
                lines.append(f"{i + 1}.{qq}({nick})\n[结束时间]:{end}")
            lines.append("══════════════")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"获取禁言列表异常: {e}")
            return "获取禁言列表出错，请查看日志"

    async def unban_all(self, event: Any):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            gid = event.get_group_id()
            if not gid:
                return "该功能仅支持群聊使用哦～"
            result = await self.star.api.call_result("get_group_shut_list", group_id=gid)
            items = result.get("data", []) if isinstance(result, dict) else result or []
            if not isinstance(items, list) or len(items) == 0:
                return "没有人被禁言啦～"
            bot_role = await self._bot_role(event, gid)
            ok = skip = fail = 0
            detail: list[str] = []
            for i, item in enumerate(items):
                uid = str(item.get("uin", ""))
                nick = str(item.get("nick", ""))
                if not uid.isdigit():
                    fail += 1
                    detail.append(f"❌{i + 1}.{uid or 'unknown'}({nick})：QQ无效")
                    continue
                try:
                    if await self._target_role(gid, uid) >= bot_role:
                        skip += 1
                        detail.append(f"⏭️{i + 1}.{uid}({nick})：权限不足(同级/更高)")
                        continue
                    done = await self.star.api.call(
                        "set_group_ban", group_id=gid, user_id=uid, duration=0
                    )
                    if done:
                        ok += 1
                        detail.append(f"✅{i + 1}.{uid}({nick})：解除成功")
                    else:
                        fail += 1
                        detail.append(f"❌{i + 1}.{uid}({nick})：解除失败")
                except Exception as e:
                    fail += 1
                    detail.append(f"❌{i + 1}.{uid}({nick})：{e}")
            return (
                "全解群员执行完成\n══════════════\n"
                f"[禁言总数] {len(items)}\n[解除成功] {ok}\n[权限跳过] {skip}\n[执行失败] {fail}\n"
                "══════════════\n" + "\n".join(detail)
            )
        except Exception as e:
            logger.error(f"全解群员异常: {e}")
            return "全解群员执行出错，请查看日志"

    async def self_title(self, event: Any, title: str = ""):

        try:
            gid = event.get_group_id()
            if not gid:
                return "该功能仅支持群聊使用哦～"
            if not await self.star.group_event_enabled(str(gid), "自助头衔"):
                return None
            title = (title or "").strip()
            if not title:
                return "请提供头衔内容哦～"
            done = await self.star.api.call(
                "set_group_special_title", group_id=gid, user_id=event.get_sender_id(), special_title=title
            )
            if not done:
                return "设置头衔失败：窝好像没有权限设置头衔哎～～"
            return None
        except Exception as e:
            logger.error(f"我要头衔异常: {e}")
            return None

    async def set_title(self, event: Any, title: str = ""):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            gid = event.get_group_id()
            if not gid:
                return "该功能仅支持群聊使用哦～"
            targets = self._at_targets(event)
            if not targets:
                return "介个功能需要艾特才能执行哦"
            title = (title or "").strip()
            lines = ["已把下面届些仁的头衔都改成一样的啦！", "══════════════"]
            for uid in targets:
                done = await self.star.api.call(
                    "set_group_special_title", group_id=gid, user_id=uid, special_title=title
                )
                lines.append(f"{'✅' if done else '❌'}{uid}")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"设置头衔异常: {e}")
            return "设置头衔执行出错，请查看日志"

    async def send_notice(self, event: Any, content: str = ""):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            gid = event.get_group_id()
            if not gid:
                return "该功能仅支持群聊使用哦～"
            content = (content or "").strip()
            if not content:
                return "发群公告至少要一个字内容哦～"
            done = await self.star.api.call(
                "send_group_notice", group_id=gid, content=content
            )
            return "公告发送成功啦～！" if done else "公告发送失败，可能机器人没有群管权限唉～"
        except Exception as e:
            logger.error(f"发公告异常: {e}")
            return "公告发送出错，请查看日志"

    async def broadcast(self, event: Any, content: str = ""):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            content = (content or "").strip()
            if not content:
                return "请至少带一段文字或一张图片哦～"
            at_all = content.startswith("☆")
            if at_all:
                content = content.lstrip("☆").strip()
            rel = "BaiXuan/扩展功能/群发系统/可群发.json"
            data = await self.star.store.read_json(rel, []) or []
            total = len(data)
            if total == 0:
                return "好像木有可群发的群聊唉～！"
            msg = (cq_at_all() + " " + content).strip() if at_all else content
            ok = 0
            failed: list[str] = []
            for gid in data:
                gid = str(gid).strip()
                if not gid.isdigit():
                    failed.append(f"{gid}(无效)")
                    continue
                try:
                    if await self.star.sender.send_to_group(gid, msg):
                        ok += 1
                    else:
                        failed.append(gid)
                except Exception as e:
                    logger.error(f"群发到 {gid} 失败: {e}")
                    failed.append(gid)
            report = f"群发「文本」完成：成功 {ok}/{total}"
            if failed:
                report += "\n发送失败：" + "、".join(failed)
            return report
        except Exception as e:
            logger.error(f"执行群发异常: {e}")
            return "执行群发出错，请查看日志"

    async def broadcast_list(self, event: Any):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            rel = "BaiXuan/扩展功能/群发系统/可群发.json"
            data = await self.star.store.read_json(rel, []) or []
            count = len(data)
            if count == 0:
                return "暂无列表，请先发送「获取可群发列表」自动获取！"
            lines = ["══════════════", f"共计已有 {count} 个群聊准备就绪", "══════════════"]
            for i, gid in enumerate(data):
                lines.append(f"{i + 1}.{gid}")
            lines.append("══════════════")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"获取可群发列表异常: {e}")
            return "获取可群发列表出错，请查看日志"

    async def broadcast_add(self, event: Any, gid: str = ""):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            gid = (gid or "").strip()
            if not gid.isdigit():
                return "请提供正确的群号哦～"
            rel = "BaiXuan/扩展功能/群发系统/可群发.json"
            data = [str(x) for x in (await self.star.store.read_json(rel, []) or [])]
            if gid in data:
                return "介个群已经有啦！不信你自己看「查看可群发列表」！"
            data.append(gid)
            await self.star.store.write_json(rel, data)
            return f"好哒好哒！这就把「{gid}」介个群给加到列表里面！"
        except Exception as e:
            logger.error(f"新增可群发目标异常: {e}")
            return "新增可群发目标出错，请查看日志"

    async def broadcast_del(self, event: Any, gid: str = ""):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            gid = (gid or "").strip()
            if not gid.isdigit():
                return "请提供正确的群号哦～"
            rel = "BaiXuan/扩展功能/群发系统/可群发.json"
            data = [str(x) for x in (await self.star.store.read_json(rel, []) or [])]
            if gid not in data:
                return "好像木有这个群唉～"
            data = [x for x in data if x != gid]
            await self.star.store.write_json(rel, data)
            return f"好哒！介就把「{gid}」介个群给去掉！"
        except Exception as e:
            logger.error(f"取消可群发目标异常: {e}")
            return "取消可群发目标出错，请查看日志"

    async def set_event(self, event: Any, name: str = "", enabled: bool = True):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            name = (name or "").strip()
            if not name:
                return "请提供事件名哦～"
            gid = event.get_group_id()
            if name in GLOBAL_EVENTS:
                rel = "BaiXuan/事件系统/全局.json"
                await self.star.store.write_key(rel, name, bool(enabled))
                return f"已将全局事件【{name}】设置为{'开启' if enabled else '关闭'}！"
            if name not in GROUP_EVENTS:
                return f"未知事件名：【{name}】\n可用事件：" + " / ".join(GROUP_EVENTS)
            if not gid:
                return "该功能仅支持群聊使用哦～"
            await self.star.set_group_event(str(gid), name, bool(enabled))
            return f"已将本群事件【{name}】设置为{'开启' if enabled else '关闭'}！"
        except Exception as e:
            logger.error(f"设置事件异常: {e}")
            return "事件设置出错，请查看日志"

    async def event_list(self, event: Any):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            gid = event.get_group_id()
            lines = ["【群事件】", "══════════════"]
            for name in GROUP_EVENTS:
                state = "开启" if await self.star.group_event_enabled(str(gid), name) else "关闭"
                lines.append(f" - {name}: {state}")
            lines.append("══════════════")
            lines.append("【全局事件】")
            lines.append("══════════════")
            for name in GLOBAL_EVENTS:
                state = "开启" if await self.star.global_event_enabled(name) else "关闭"
                lines.append(f" - {name}: {state}")
            lines.append("══════════════")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"事件列表异常: {e}")
            return "事件列表获取出错，请查看日志"

    async def member_list(self, event: Any):

        try:
            if not await self.star.perm.check_admin(event):
                return "你没有权限执行该指令哦～"
            gid = event.get_group_id()
            if not gid:
                return "该功能仅支持群聊使用哦～"
            members = await self.star.api.get_group_member_list(gid)
            if not members:
                return "获取群成员失败！"
            lines = [f"本群共有【{len(members)}】位成员：", "══════════════"]
            for i, m in enumerate(members):
                lines.append(f"{i + 1}.{m.get('user_id')}({m.get('card') or m.get('nickname', '')})")
            lines.append("══════════════")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"获取本群成员异常: {e}")
            return "获取本群成员出错，请查看日志"

    async def legacy(self, event: Any, message: str) -> Any:

        try:
            if not event.get_group_id():
                return None

            m = re.match(r"^(全体|全)(禁言|解禁|禁|解)$", message)
            if m:
                token = m.group(2)
                return await self.whole_ban(event, token in ("禁言", "禁"))

            m = re.match(r"^(禁言|解禁)([\s\S]*?)(?:\s+(\d+))?$", message)
            if m and self._at_targets(event):
                action = m.group(1)
                secs = int(m.group(3) or 60)
                if action == "禁言":
                    return await self.mute(event, secs)
                return await self.unmute(event)

            m = re.match(r"^(踢出|黑踢)([\s\S]*?)$", message)
            if m and self._at_targets(event):
                if m.group(1) == "黑踢":
                    return await self.black_kick(event)
                return await self.kick(event)

            m = re.match(r"^(上管|下管)([\s\S]*?)$", message)
            if m and self._at_targets(event):
                if m.group(1) == "上管":
                    return await self.promote(event)
                return await self.demote(event)
            if message == "获取禁言列表":
                return await self.ban_list(event)
            if message == "全解群员":
                return await self.unban_all(event)

            if message.startswith("我要头衔"):
                return await self.self_title(event, message[4:])

            if message.startswith("设置头衔"):
                return await self.set_title(event, self._plain_text(event).replace("设置头衔", "").strip())

            if message.startswith("发公告"):
                return await self.send_notice(event, self._plain_text(event).replace("发公告", "").strip())

            if message.startswith("执行群发") or message.startswith("☆执行群发"):
                m = _BROADCAST_RE.match(message)
                content = m.group(1).strip() if m else ""
                if message.startswith("☆"):
                    content = "☆" + content
                return await self.broadcast(event, content)
            if message in ("获取可群发列表", "获取全部可群发列表", "查看可群发列表"):
                return await self.broadcast_list(event)
            m = re.match(r"^(取消|新增)可群发目标([0-9]+)$", message)
            if m:
                if m.group(1) == "新增":
                    return await self.broadcast_add(event, m.group(2))
                return await self.broadcast_del(event, m.group(2))

            m = re.match(r"^(开启|关闭)事件([\s\S]*)$", message)
            if m:
                return await self.set_event(event, m.group(2).strip(), m.group(1) == "开启")
            if message == "事件列表":
                return await self.event_list(event)
            if message in ("获取本群成员", "群成员列表"):
                return await self.member_list(event)
            return None
        except Exception as e:
            logger.error(f"群管 legacy 异常: {e}")
            return None
