from __future__ import annotations

import asyncio
import random
import re
import time
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger

from lib.cqcode import cq_at

_JOIN_MODES = ("准确", "包含", "模糊多重", "准确多重", "字数")
_REPLY_RE = re.compile(r"问题：([\s\S]*)\n答案：([\s\S]*)")

def _now() -> int:
    return int(time.time())

def _today() -> str:
    return time.strftime("%Y-%m-%d")

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

def _sub_rel(gid: str, name: str) -> str:
    return f"BaiXuan/群管系统/入群审核/{gid}/{name}.json"

class JoinReviewModule:

    def __init__(self, star: Any) -> None:
        self.star = star
        self._verify_tasks: dict[str, asyncio.Task] = {}

    async def terminate(self) -> None:
        for t in self._verify_tasks.values():
            t.cancel()
        self._verify_tasks.clear()

    async def _group_role(self, gid: Any, uid: Any) -> int:
        try:
            info = await self.star.api.get_group_member_info(gid, uid)
            if not info:
                return 1
            role = info.get("role", "member")
            return {"owner": 3, "admin": 2, "member": 1}.get(role, 1)
        except Exception as e:
            logger.warning(f"获取群角色失败: {e}")
            return 1

    async def on_group_increase(self, event: Any, raw: dict) -> None:

        gid = str(raw.get("group_id") or "")
        uid = str(raw.get("user_id") or "")
        if not gid or not uid:
            return
        try:
            await self.star.store.write_key(_sub_rel(gid, "审核状态.json"), uid, "无")
            await self.star.store.write_key(_sub_rel(gid, "次数.json"), uid, 0)
            await self.star.store.write_key(_sub_rel(gid, "验证码.json"), uid, False)
            if not await self.star.group_event_enabled(gid, "join_verify"):
                return

            if raw.get("sub_type") == "invite":
                operator = str(raw.get("operator_id") or "")
                if operator and await self._group_role(gid, operator) >= 2:
                    return
            bot_self = str(getattr(event.message_obj, "self_id", "") or "")
            if not bot_self or await self._group_role(gid, bot_self) < 2:
                return
            times_cfg = int(self.star.config.get("join_verify_tries", 5))
            timeout_cfg = int(self.star.config.get("join_verify_timeout", 300))
            可用次数 = int(await self.star.store.read_key(_sub_rel(gid, "次数.json"), "可用次数", times_cfg) or times_cfg)
            秒数 = int(await self.star.store.read_key(_sub_rel(gid, "次数.json"), "可用时间", timeout_cfg) or timeout_cfg)
            秒数 = max(1, min(秒数, 86400))
            验证值 = random.randint(1000, 9999)
            await self.star.store.write_key(_sub_rel(gid, "验证码.json"), uid, 验证值)
            await self.star.store.write_key(_sub_rel(gid, "审核状态.json"), uid, "验证中")
            now = _now()
            msg = (
                f"[CQ:image,file=https://q4.qlogo.cn/g?b=qq&nk={uid}&s=5]\n"
                f"{cq_at(uid)} ({uid})\n"
                f"请在{max(1, 秒数 // 60)}分钟内发送一下内容进行验证是否活人！\n"
                "------------------\n"
                f"[验证内容]:{验证值}\n"
                f"[可以机会]:{可用次数}次\n"
                "------------------\n"
                f"[现在时间]:{_time_a('y-m-d H:i:s', now)}\n"
                f"[截止时间]:{_time_a('y-m-d H:i:s', now + 秒数)}"
            )
            await self.star.sender.send_to_group(gid, msg)

            task_key = f"{gid}_{uid}"
            task = asyncio.create_task(self._verify_timeout_loop(gid, uid, bot_self, 秒数))
            self._verify_tasks[task_key] = task
            task.add_done_callback(lambda _t: self._verify_tasks.pop(task_key, None))
        except Exception as e:
            logger.error(f"入群验证码生成异常: {e}")

    async def _verify_timeout_loop(self, gid: str, uid: str, bot_self: str, seconds: int) -> None:

        try:
            elapsed = 0
            while elapsed < seconds:
                await asyncio.sleep(2)
                elapsed += 2
                status = await self.star.store.read_key(_sub_rel(gid, "审核状态.json"), uid, "无")
                if status in ("已通过", "废物", "无"):
                    return
                可用次数 = int(await self.star.store.read_key(_sub_rel(gid, "次数.json"), "可用次数", 5) or 5)
                已用次数 = int(await self.star.store.read_key(_sub_rel(gid, "次数.json"), uid, 0) or 0)
                if 已用次数 >= 可用次数:
                    await self._kick_failed(gid, uid, bot_self, "在规定次数内未成功验证，已处理！")
                    return
            await self._kick_failed(gid, uid, bot_self, "在规定时间内未成功验证，已处理！")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"入群验证超时检测异常: {e}")

    async def _kick_failed(self, gid: str, uid: str, bot_self: str, reason: str) -> None:
        try:
            if await self._group_role(gid, bot_self) > await self._group_role(gid, uid):
                await self.star.api.call("set_group_kick", group_id=gid, user_id=uid)
                await self.star.sender.send_to_group(
                    gid, f"【通报】\n[用户]:{uid}\n{reason}"
                )
            await self.star.store.write_key(_sub_rel(gid, "审核状态.json"), uid, "废物")
            await self.star.store.write_key(_sub_rel(gid, "验证码.json"), uid, False)
        except Exception as e:
            logger.error(f"验证失败踢出异常: {e}")

    async def _process_verify_answer(self, event: Any, message: str) -> bool:

        gid = str(event.get_group_id() or "")
        uid = str(event.get_sender_id() or "")
        if not gid or not uid:
            return False
        try:
            if not await self.star.group_event_enabled(gid, "join_verify"):
                return False
            status = await self.star.store.read_key(_sub_rel(gid, "审核状态.json"), uid, "无")
            if status != "验证中":
                return False
            值 = await self.star.store.read_key(_sub_rel(gid, "验证码.json"), uid, False)
            if not 值:
                return False
            bot_self = str(getattr(event.message_obj, "self_id", "") or "")
            if bot_self and await self._group_role(gid, bot_self) <= await self._group_role(gid, uid):
                await self.star.store.write_key(_sub_rel(gid, "验证码.json"), uid, False)
                await self.star.store.write_key(_sub_rel(gid, "审核状态.json"), uid, "无")
                return True
            可用次数 = int(await self.star.store.read_key(_sub_rel(gid, "次数.json"), "可用次数", 5) or 5)
            if message.strip() != str(值):
                已用次数 = int(await self.star.store.read_key(_sub_rel(gid, "次数.json"), uid, 0) or 0)
                if 已用次数 >= 可用次数:
                    await self.star.store.write_key(_sub_rel(gid, "审核状态.json"), uid, "废物")
                    if bot_self:
                        await self.star.api.call("set_group_kick", group_id=gid, user_id=uid)
                    await self.star.sender.send_to_group(
                        gid, f"【通报】\n[用户]:{uid}\n在规定次数内未成功验证，已处理！"
                    )
                    return True
                await self.star.store.write_key(_sub_rel(gid, "次数.json"), uid, 已用次数 + 1)
                await self.star.api.call("delete_msg", message_id=getattr(event.message_obj, "message_id", ""))
                剩余 = 可用次数 - (已用次数 + 1)
                await self.star.sender.send_to_group(
                    gid,
                    f"{cq_at(uid)} ({uid})\n验证码错误！\n你的验证码是:{值}\n剩余验证次数:{剩余}",
                )
                return True
            await self.star.store.write_key(_sub_rel(gid, "验证码.json"), uid, False)
            await self.star.store.write_key(_sub_rel(gid, "审核状态.json"), uid, "已通过")
            return True
        except Exception as e:
            logger.error(f"验证码判定异常: {e}")
            return False

    async def send_welcome(self, event: Any, raw: dict) -> None:

        gid = str(raw.get("group_id") or "")
        uid = str(raw.get("user_id") or "")
        if not gid or not uid:
            return
        try:
            info = await self.star.api.get_group_member_info(gid, uid)
            info = info or {}
            nick = info.get("nickname") or info.get("nick") or "未知"
            sex_map = {"male": "男", "female": "女", "unknown": "未知"}
            性别 = sex_map.get(info.get("sex", "unknown"), "未知")
            年龄 = info.get("age", 0)
            等级 = info.get("qq_level", info.get("level", 0))
            template = await self.star.store.read_text(
                f"BaiXuan/群管系统/入群欢迎词/{gid}.json",
                "[艾特] ([新人QQ])欢迎你的加入\n[时间]",
            )
            bot_self = str(getattr(event.message_obj, "self_id", "") or "")
            content = template
            content = content.replace("[艾特]", cq_at(uid))
            content = content.replace("[用户QQ]", uid).replace("[新人QQ]", uid)
            content = content.replace("[用户昵称]", str(nick)).replace("[昵称]", str(nick))
            content = content.replace("[群号]", gid)
            content = content.replace("[时间]", _time_a("y-m-d H:i:s"))
            content = content.replace("[性别]", str(性别))
            content = content.replace("[年龄]", str(年龄))
            content = content.replace("[等级]", str(等级))
            if bot_self:
                content = content.replace("[本机头像]", f"[CQ:image,file=https://q4.qlogo.cn/g?b=qq&nk={bot_self}&s=5]")
                content = content.replace("[新人头像]", f"[CQ:image,file=https://q4.qlogo.cn/g?b=qq&nk={uid}&s=5]")
            render_data = {
                "qq": uid,
                "name": str(nick),
                "sex": str(性别),
                "rrrr": _time_a("y-m-d"),
                "age": str(年龄),
                "denji": str(等级),
                "zhuce": str(_time_a("y", info.get("reg_time", _now()))),
                "jiaqun": _time_a("y-m-d H:i:s"),
            }
            if self.star.config.get("html_render_enabled", False):
                try:
                    url = await self.star.render.render_html("join_card.html", render_data, width=1400)
                    if url:
                        await event.send(event.chain_result([Comp.Image.fromURL(url), Comp.Plain(content)]))
                        return
                except Exception as e:
                    logger.warning(f"入群欢迎卡片渲染失败，回退文本: {e}")
            await event.send(event.plain_result(content))
        except Exception as e:
            logger.error(f"入群欢迎异常: {e}")

    async def send_leave_notice(self, event: Any, raw: dict) -> None:

        gid = str(raw.get("group_id") or "")
        uid = str(raw.get("user_id") or "")
        if not gid or not uid:
            return
        try:
            if raw.get("sub_type") == "kick" and raw.get("operator_id") == raw.get("self_id"):
                return
            群名 = gid
            info = await self.star.api.get_group_info(gid)
            if info and info.get("group_name"):
                群名 = str(info.get("group_name"))
            用户昵称 = str(uid)
            stranger = await self.star.api.get_group_member_info(gid, uid) or {}
            if stranger.get("nickname"):
                用户昵称 = str(stranger.get("nickname"))
            退群类型 = "主动退群" if raw.get("sub_type") == "leave" else "被踢出"
            操作者QQ = str(raw.get("operator_id") or "")
            操作者昵称 = 操作者QQ
            if 操作者QQ:
                op = await self.star.api.get_group_member_info(gid, 操作者QQ) or {}
                if op.get("nickname"):
                    操作者昵称 = str(op.get("nickname"))
            template = await self.star.store.read_text(
                f"BaiXuan/群管系统/退群通知模板/{gid}.json",
                "[用户QQ] ([用户昵称]) 离开了本群～",
            )
            bot_self = str(raw.get("self_id") or "")
            content = template
            content = content.replace("[用户QQ]", uid).replace("[用户昵称]", 用户昵称)
            content = content.replace("[操作者QQ]", 操作者QQ).replace("[操作者昵称]", 操作者昵称)
            content = content.replace("[群号]", gid).replace("[群名]", 群名)
            content = content.replace("[时间]", _time_a("y-m-d H:i:s"))
            content = content.replace("[退群类型]", 退群类型)
            if bot_self:
                content = content.replace("[本机头像]", f"[CQ:image,file=https://q4.qlogo.cn/g?b=qq&nk={bot_self}&s=5]")
                content = content.replace("[退者头像]", f"[CQ:image,file=https://q4.qlogo.cn/g?b=qq&nk={uid}&s=5]")
            await self.star.sender.send_to_group(gid, content)
        except Exception as e:
            logger.error(f"退群通知异常: {e}")

    async def on_group_add_request(self, event: Any, raw: dict) -> None:

        gid = str(raw.get("group_id") or "")
        uid = str(raw.get("user_id") or "")
        flag = raw.get("flag", "")
        comment = str(raw.get("comment") or "").strip()
        if not gid or not uid or not flag:
            return
        try:
            sub_type = str(raw.get("sub_type") or "add")
            if sub_type != "add" or not comment:
                await self.star.api.call("set_group_add_request", flag=flag, sub_type=sub_type, approve=True)
                await self.star.sender.send_to_group(gid, f"QQ({uid})通过入群审核，已同意进入～")
                return
            rel = _sub_rel(gid, "数据.json")
            条件 = str(await self.star.store.read_key(rel, "条件", self.star.config.get("join_review_default_condition", "准确")) or "准确")
            次数 = int(await self.star.store.read_key(rel, "次数", self.star.config.get("join_review_daily_limit", 3)) or 3)
            字数数量 = int(await self.star.store.read_key(rel, "字数数量", 5) or 5)
            今天 = _today()
            count_rel = f"BaiXuan/群管系统/入群审核/{gid}/申请次数/{uid}.json"
            me_cs = int(await self.star.store.read_key(count_rel, 今天, 0) or 0)
            if me_cs > 次数:
                await self.star.api.call(
                    "set_group_add_request", flag=flag, approve=False, reason="你今天的可用申请次数已用完咯～"
                )
                return
            await self.star.store.write_key(count_rel, 今天, me_cs + 1)

            answer = comment
            m = _REPLY_RE.search(comment)
            if m:
                answer = m.group(2).strip()

            过滤库 = await self.star.store.read_json(_sub_rel(gid, "过滤库.json"), []) or []
            for word in 过滤库:
                if word and word in answer:
                    await self.star.api.call(
                        "set_group_add_request", flag=flag, approve=False, reason="你的回答不符合本群设定！3"
                    )
                    return
            成功与否 = False
            reason = "意想不到的回复"
            普通答案 = str(await self.star.store.read_key(rel, "答案", "") or "")
            if 条件 == "字数":
                if len(answer) >= 字数数量:
                    成功与否 = True
                else:
                    reason = f"本群设定通过内容为:>={字数数量}个字"
            elif 条件 == "包含":
                if 普通答案 and 普通答案 in answer:
                    成功与否 = True
                else:
                    reason = "你的回答不符合本群设定！1"
            elif 条件 == "准确":
                if 普通答案 and answer == 普通答案:
                    成功与否 = True
                else:
                    reason = "你的回答不符合本群设定！2"
            elif 条件 in ("模糊多重", "准确多重"):
                条件库 = await self.star.store.read_json(_sub_rel(gid, "条件库.json"), []) or []
                for word in 条件库:
                    hit = (word in answer) if 条件 == "模糊多重" else (answer == word)
                    if hit:
                        成功与否 = True
                        break
                    reason = "你的回答不符合本群设定！4"
            await self.star.api.call(
                "set_group_add_request", flag=flag, approve=成功与否, reason="" if 成功与否 else reason
            )
            if 成功与否:
                await self.star.sender.send_to_group(gid, f"QQ({uid})通过入群审核，已同意进入～")
        except Exception as e:
            logger.error(f"入群申请审核异常: {e}")

    async def legacy(self, event: Any, message: str) -> Any:

        try:
            gid = event.get_group_id()

            if gid and await self._process_verify_answer(event, message):
                return None
            if not gid:
                return None
            if not await self.star.perm.check_admin(event):
                return None
            gid = str(gid)

            m = re.match(r"^设置入群审核条件(准确|模糊多重|准确多重|包含|字数)$", message)
            if m:
                mode = m.group(1)
                rel = _sub_rel(gid, "数据.json")
                old = await self.star.store.read_key(rel, "条件", "字数")
                if mode == old:
                    return "目前本群设置的条件是一样的啦～！"
                await self.star.store.write_key(rel, "条件", mode)
                return f"已把本群的入群审核【条件】设置为「{mode}」模式\n══════════════\n记得本账号要有管理权限并且群聊是要为「发送验证消息」才生效哦～"

            if message.startswith("设置入群审核答案"):
                ans = message[len("设置入群审核答案"):]
                await self.star.store.write_key(_sub_rel(gid, "数据.json"), "答案", ans)
                return f"已把本群的入群审核【答案】设置为{ans}\n══════════════\n记得本账号要有管理权限并且群聊是要为「发送验证消息」才生效哦～"

            m = re.match(r"^设置入群审核字数数量([0-9]+)$", message)
            if m:
                num = int(m.group(1))
                if num == 0 or num > 15:
                    return "你这数字真的合适嘛～？"
                await self.star.store.write_key(_sub_rel(gid, "数据.json"), "字数数量", num)
                return f"已把本群的入群审核【字数审核】设置为{m.group(1)}字\n══════════════\n记得本账号要有管理权限并且群聊是要为「发送验证消息」才生效哦～"

            m = re.match(r"^设置入群审核单日次数([0-9]+)$", message)
            if m:
                num = int(m.group(1))
                if num == 0 or num > 100:
                    return "你这数字真的合适嘛～？"
                await self.star.store.write_key(_sub_rel(gid, "数据.json"), "次数", num)
                return f"已把本群的入群审核【每日次数】设置为{m.group(1)}次\n══════════════\n记得本账号要有管理权限并且群聊是要为「发送验证消息」才生效哦～"

            m = re.match(r"^设置入群验证(次数|时长)([0-9]+)$", message)
            if m:
                typ, num = m.group(1), int(m.group(2))
                if num == 0:
                    return f"【{typ}】参数的值不能为0或等于原值！"
                if typ == "时长" and num >= 86400:
                    return "这么长时间我会炸の！"
                await self.star.store.write_key(_sub_rel(gid, "次数.json"), "可用次数" if typ == "次数" else "可用时间", num)
                return f"好哒！这就把入群验证的【{typ}】参数改成「{num}」"

            m = re.match(r"^取消入群验证([0-9]+)$", message)
            if m:
                target = m.group(1)
                status = await self.star.store.read_key(_sub_rel(gid, "审核状态.json"), target, "无")
                if status == "无":
                    return f"「{target}」不处于验证状态啦！"
                await self.star.store.write_key(_sub_rel(gid, "审核状态.json"), target, "无")
                await self.star.store.write_key(_sub_rel(gid, "验证码.json"), target, False)
                return f"好哒！这就给「{target}」取消本次验证！"

            if message.startswith("设置入群欢迎词#"):
                content = message[len("设置入群欢迎词#"):]
                if len(content) < 2:
                    return "请字数大于2个哦～"
                await self.star.store.write_text(f"BaiXuan/群管系统/入群欢迎词/{gid}.json", content)
                return f"好哒！这就把本群的【入群欢迎语】设置为:\n{content}"

            if message.startswith("设置退群通知词#"):
                content = message[len("设置退群通知词#"):]
                if not content.strip():
                    return "模板内容不能为空哦～"
                await self.star.store.write_text(f"BaiXuan/群管系统/退群通知模板/{gid}.json", content)
                return f"已设置本群的退群通知模板：\n{content}"

            m = re.match(r"^(增加|新增|添加|删除|取消|减少|清空)(审核条件|审核过滤词)([\s\S]*)$", message)
            if m:
                op, typ, content = m.group(1), m.group(2), m.group(3)
                rel = _sub_rel(gid, "条件库.json") if typ == "审核条件" else _sub_rel(gid, "过滤库.json")
                data = await self.star.store.read_json(rel, []) or []
                data = [str(x) for x in data]
                if op in ("增加", "新增", "添加"):
                    if content in data:
                        return f"emmmm，介个{typ}好像也就有了哎～"
                    data.append(content)
                    await self.star.store.write_json(rel, data)
                    return f"我这就去更新{typ}\n【新增】: {content}"
                if op in ("删除", "取消", "减少"):
                    if content not in data:
                        return f"额，介个{typ}好像没有吧，我都找不到～～"
                    data = [x for x in data if x != content]
                    await self.star.store.write_json(rel, data)
                    return f"我这就去更新{typ}\n【删除】: {content}"
                if op == "清空":
                    await self.star.store.write_json(rel, [])
                    return f"耗的，这就就把{typ}通通删除！"

            m = re.match(r"^查看(多重条件|审核过滤词)(列表|)$", message)
            if m:
                typ = m.group(1)
                rel = _sub_rel(gid, "条件库.json") if typ == "多重条件" else _sub_rel(gid, "过滤库.json")
                data = await self.star.store.read_json(rel, []) or []
                if not data:
                    return "窝好像没有获取到数据哎～"
                lines = [f"本群共有【{len(data)}】个{typ}", "══════════════"]
                for i, w in enumerate(data):
                    lines.append(f"【{i + 1}】{w}")
                return "\n".join(lines)
            return None
        except Exception as e:
            logger.error(f"入群审核 legacy 异常: {e}")
            return None
