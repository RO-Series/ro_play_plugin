"""RO_Play 插件主入口（迁移自 MKbot 2.3.4）。

对应原 index.mjs 的 plugin_init / plugin_onmessage / plugin_onevent /
plugin_on_config_change / plugin_cleanup。AstrBot 中：
- 生命周期：__init__ + @filter.on_astrbot_loaded() + terminate()
- 指令：@filter.command / @filter.command_group
- OneBot notice/request 事件：EventMessageType.ALL 兜底监听器解析 raw_message
- 定时任务：asyncio 任务（句柄保存，terminate 取消）

命名替换：路径前缀「筱筱吖」→「BaiXuan」，MKbot → RO_Play，MK → RO。
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path
from typing import Any

# AstrBot 加载插件时不会把插件目录加入 sys.path，
# 此处注入插件根目录，使 `lib` 包（lib/、lib/modules/、lib/video/）可被绝对导入。
_PLUGIN_ROOT = str(Path(__file__).resolve().parent)
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import MessageEventResult, filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from lib.api_client import ApiClient
from lib.notice_handler import NoticeHandler
from lib.permission import Permission
from lib.render import Renderer
from lib.scheduler import Scheduler
from lib.sender import Sender
from lib.storage import DataStore

from lib.modules import (
    AdminModule,
    BlacklistModule,
    CardShopModule,
    DriftBottleModule,
    EntertainmentModule,
    FakeChatModule,
    FirekeepModule,
    GroupWifeModule,
    JoinPmModule,
    JoinReviewModule,
    LicenseModule,
    MasqueradeModule,
    MusicModule,
    QaModule,
    TalkStatsModule,
    ToolsModule,
)

PLUGIN_NAME = "astrbot_plugin_ro_play"
TEMPLATES_SRC = Path(__file__).resolve().parent / "data" / "templates"


class Main(Star):
    """RO_Play 主类。"""

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self.name = PLUGIN_NAME
        self.data_path = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        self.data_path.mkdir(parents=True, exist_ok=True)

        # 基础设施
        self.store = DataStore(self.data_path)
        self.api = ApiClient(self)
        self.sender = Sender(self)
        self.render = Renderer(self)
        self.perm = Permission(self)
        self.notice = NoticeHandler(self)
        self.scheduler = Scheduler(self)

        # 功能模块
        self.modules: dict[str, Any] = {
            "license": LicenseModule(self),
            "admin": AdminModule(self),
            "join_review": JoinReviewModule(self),
            "entertainment": EntertainmentModule(self),
            "group_wife": GroupWifeModule(self),
            "drift_bottle": DriftBottleModule(self),
            "card_shop": CardShopModule(self),
            "music": MusicModule(self),
            "qa": QaModule(self),
            "firekeep": FirekeepModule(self),
            "blacklist": BlacklistModule(self),
            "talk_stats": TalkStatsModule(self),
            "fake_chat": FakeChatModule(self),
            "masquerade": MasqueradeModule(self),
            "join_pm": JoinPmModule(self),
            "tools": ToolsModule(self),
        }

        self._tasks: list[asyncio.Task] = []
        self._templates_migrated = False

        self._register_web_apis()

    # ==================== 生命周期 ====================

    @filter.on_astrbot_loaded()
    async def on_loaded(self) -> None:
        """替代 plugin_init：迁移默认资源并启动定时任务。"""
        await self._migrate_templates()
        self._tasks.append(asyncio.create_task(self.scheduler.run_hourly()))
        self._tasks.append(asyncio.create_task(self.scheduler.run_broadcast()))
        logger.info("RO_Play 插件已加载，数据目录: %s", self.data_path)

    async def terminate(self) -> None:
        """替代 plugin_cleanup：取消全部定时任务。"""
        self.scheduler.stop()
        for t in self._tasks:
            t.cancel()
        for m in self.modules.values():
            if hasattr(m, "terminate"):
                try:
                    await m.terminate()
                except Exception:  # noqa: BLE001
                    pass
        logger.info("RO_Play 插件已卸载")

    async def _migrate_templates(self) -> None:
        """首次运行把随插件分发的模板复制到 plugin_data（只复制缺失的）。"""
        if self._templates_migrated:
            return
        dst = self.data_path / "templates"
        dst.mkdir(parents=True, exist_ok=True)
        try:
            if TEMPLATES_SRC.exists():
                shutil.copytree(TEMPLATES_SRC, dst, dirs_exist_ok=True)
            self._templates_migrated = True
        except Exception as e:  # noqa: BLE001
            logger.error(f"模板迁移失败: {e}")

    # ==================== 事件开关工具 ====================

    async def group_event_enabled(self, gid: str, key: str) -> bool:
        """查询群事件开关（BaiXuan/事件系统/{gid}.json），缺省回退 default_events 配置。"""
        if not gid:
            return False
        data = await self.store.read_json(f"BaiXuan/事件系统/{gid}.json", {})
        if key in (data or {}):
            return bool(data[key])
        return bool((self.config.get("default_events", {}) or {}).get(key, False))

    async def set_group_event(self, gid: str, key: str, value: bool) -> None:
        await self.store.write_key(f"BaiXuan/事件系统/{gid}.json", key, value)

    async def global_event_enabled(self, key: str) -> bool:
        """查询全局事件开关（BaiXuan/事件系统/全局.json）。"""
        data = await self.store.read_json("BaiXuan/事件系统/全局.json", {})
        return bool((data or {}).get(key, False))

    async def deep_entertainment_enabled(self) -> bool:
        """深度娱乐总开关（原 readB(深度娱乐路径)）。"""
        rel = str(self.config.get("deep_entertainment_path", "")).strip()
        if not rel:
            return True
        return await self.store.read_key(rel, "enabled", False)

    # ==================== 通用结果转发 ====================

    async def _emit(self, event: AstrMessageEvent, mod: str, meth: str, **kw):
        """调用模块方法并转发其结果（MessageEventResult / 列表 / 字符串）。"""
        try:
            inst = self.modules.get(mod)
            if inst is None:
                yield event.plain_result("模块未加载")
                return
            res = await getattr(inst, meth)(event, **kw)
            if res is None:
                return
            if isinstance(res, list):
                for r in res:
                    yield r if isinstance(r, MessageEventResult) else event.plain_result(str(r))
            elif isinstance(res, MessageEventResult):
                yield res
            else:
                yield event.plain_result(str(res))
        except Exception as e:  # noqa: BLE001
            logger.error(f"模块 {mod}.{meth} 出错: {e}")
            yield event.plain_result(f"指令执行出错：{type(e).__name__}: {e}")

    async def _emit_direct(self, event: AstrMessageEvent, res: Any) -> None:
        """在监听器（非生成器指令）中直接发送结果。"""
        if res is None:
            return
        if isinstance(res, list):
            for r in res:
                await event.send(r if isinstance(r, MessageEventResult) else event.plain_result(str(r)))
        elif isinstance(res, MessageEventResult):
            await event.send(res)
        else:
            await event.send(event.plain_result(str(res)))

    # ==================== 消息 / 事件总入口 ====================

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_all_message(self, event: AstrMessageEvent) -> None:
        """兜底监听器：OneBot notice/request 事件 + 被动功能 + 无前缀 legacy 指令。"""
        raw = getattr(event.message_obj, "raw_message", None)
        if isinstance(raw, dict) and raw.get("post_type") in ("notice", "request"):
            await self._record_umo(event)
            if raw.get("post_type") == "notice":
                await self.notice.dispatch(event, raw)
            else:
                await self.notice.dispatch_request(event, raw)
            event.stop_event()
            return

        text = (event.message_str or "").strip()
        # 机器人的消息：自触开关关闭时忽略
        if self._is_self_sender(event) and not self.config.get("self_trigger", False):
            return
        # 白名单过滤（原 group_of / haoyou_of）
        if not await self._in_whitelist(event):
            return

        await self._record_umo(event)
        await self._passive_features(event, text)

        # legacy 无前缀指令兜底
        if not text or text.startswith("/"):
            return
        if not self.config.get("legacy_no_prefix", False):
            return
        for inst in self.modules.values():
            legacy = getattr(inst, "legacy", None)
            if legacy is None:
                continue
            try:
                res = await legacy(event, text)
                if res is not None:
                    await self._emit_direct(event, res)
                    event.stop_event()
                    return
            except Exception as e:  # noqa: BLE001
                logger.error(f"legacy {type(inst).__name__} 异常: {e}")

    def _is_self_sender(self, event: AstrMessageEvent) -> bool:
        try:
            bot_id = event.message_obj.self_id if event.message_obj else None
            return bool(bot_id) and str(event.get_sender_id()) == str(bot_id)
        except Exception:  # noqa: BLE001
            return False

    async def _in_whitelist(self, event: AstrMessageEvent) -> bool:
        gid = event.get_group_id()
        if gid:
            wl = [str(x) for x in self.config.get("group_whitelist", [])]
            return (not wl) or (str(gid) in wl)
        uid = event.get_sender_id()
        wl = [str(x) for x in self.config.get("friend_whitelist", [])]
        return (not wl) or (str(uid) in wl)

    async def _record_umo(self, event: AstrMessageEvent) -> None:
        """缓存 unified_msg_origin，供定时任务主动推送使用。"""
        try:
            umo = event.unified_msg_origin
            gid = event.get_group_id()
            if gid:
                await self.put_kv_data(f"umo/group_{gid}", umo)
            else:
                await self.put_kv_data(f"umo/private_{event.get_sender_id()}", umo)
        except Exception:  # noqa: BLE001
            pass

    async def _passive_features(self, event: AstrMessageEvent, text: str) -> None:
        """被动功能：问答 / 违禁检测 / 发言统计 / 视频解析（按群事件开关）。"""
        gid = event.get_group_id()
        # 违禁检测
        if gid and await self.group_event_enabled(gid, "prohibited"):
            await self._try_passive(event, "blacklist", "check_message")
        # 问答
        if gid and await self.group_event_enabled(gid, "qa"):
            await self._try_passive(event, "qa", "on_message")
        # 发言统计
        if gid and await self.group_event_enabled(gid, "talk_stats"):
            await self._try_passive(event, "talk_stats", "count")
        # 视频解析
        if gid and await self.group_event_enabled(gid, "video_parse") and text:
            await self._try_passive(event, "tools", "video_scan")

    async def _try_passive(self, event: AstrMessageEvent, mod: str, meth: str) -> None:
        try:
            inst = self.modules.get(mod)
            if inst and hasattr(inst, meth):
                await getattr(inst, meth)(event)
        except Exception as e:  # noqa: BLE001
            logger.error(f"被动功能 {mod}.{meth} 异常: {e}")

    # ==================== Web API ====================

    def _register_web_apis(self) -> None:
        from quart import jsonify

        self.context.register_web_api(
            f"/{PLUGIN_NAME}/config", self._web_get_config, ["GET"], "读取配置"
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/config", self._web_save_config, ["POST"], "保存配置"
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/groups", self._web_groups, ["GET"], "群列表"
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/friends", self._web_friends, ["GET"], "好友列表"
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/events/group", self._web_events_get, ["GET"], "群事件开关"
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/events/group", self._web_events_save, ["POST"], "保存群事件开关"
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/broadcast", self._web_broadcast_get, ["GET"], "读取群发配置"
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/broadcast", self._web_broadcast_save, ["POST"], "保存群发配置"
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/broadcast/send", self._web_broadcast_send, ["POST"], "执行群发"
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/data-edit", self._web_data_get, ["GET"], "读取玩家数据"
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/data-edit", self._web_data_save, ["POST"], "保存玩家数据"
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/auto-like", self._web_auto_like_get, ["GET"], "读取自动点赞配置"
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/auto-like", self._web_auto_like_save, ["POST"], "保存自动点赞配置"
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/about", self._web_about, ["GET"], "插件版本信息"
        )

    async def _web_get_config(self):
        from quart import jsonify
        return jsonify(dict(self.config))

    async def _web_save_config(self, req):
        from quart import jsonify
        try:
            body = await req.get_json()
            for k, v in (body or {}).items():
                if k in self.config:
                    self.config[k] = v
            self.config.save_config()
            return jsonify({"ok": True})
        except Exception as e:  # noqa: BLE001
            logger.error(f"保存配置失败: {e}")
            return jsonify({"ok": False, "error": str(e)})

    async def _web_groups(self):
        from quart import jsonify
        return jsonify(await self.api.get_group_list())

    async def _web_friends(self):
        from quart import jsonify
        return jsonify(await self.api.get_friend_list())

    async def _web_events_get(self):
        from quart import jsonify
        gid = self._req_arg("gid")
        if not gid:
            return jsonify({"ok": False, "error": "缺少 gid"})
        data = await self.store.read_json(f"BaiXuan/事件系统/{gid}.json", {})
        return jsonify(data)

    async def _web_events_save(self, req):
        from quart import jsonify
        try:
            body = await req.get_json()
            gid = (body or {}).get("gid", "")
            if not gid:
                return jsonify({"ok": False, "error": "缺少 gid"})
            events = body.get("events", {})
            await self.store.write_json(f"BaiXuan/事件系统/{gid}.json", events)
            return jsonify({"ok": True})
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(e)})

    @staticmethod
    def _req_arg(key: str) -> str:
        try:
            from quart import request
            return request.args.get(key, "")
        except Exception:  # noqa: BLE001
            return ""

    # ---------- Web API：群发广播 ----------

    async def _web_broadcast_get(self):
        from quart import jsonify
        conf = await self.store.read_json(
            "BaiXuan/扩展功能/群发系统/定时CQ.json",
            {"enabled": False, "mode": "interval", "intervalSec": 3600, "atAll": False, "content": "", "targets": [], "calendarRules": []},
        )
        return jsonify(conf)

    async def _web_broadcast_save(self, req):
        from quart import jsonify
        try:
            body = await req.get_json()
            await self.store.write_json("BaiXuan/扩展功能/群发系统/定时CQ.json", body or {})
            return jsonify({"ok": True})
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(e)})

    async def _web_broadcast_send(self, req):
        from quart import jsonify
        try:
            body = await req.get_json() or {}
            targets = body.get("targets", []) or []
            content = str(body.get("content", ""))
            sent = 0
            for gid in targets:
                if await self.sender.send_to_group(gid, content):
                    sent += 1
            return jsonify({"ok": True, "sent": sent})
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(e)})

    # ---------- Web API：数据编辑 ----------

    async def _web_data_get(self):
        from quart import jsonify
        uid = self._req_arg("uid")
        if not uid:
            return jsonify({"ok": False, "error": "缺少 uid"})
        money = await self.store.read_key(f"BaiXuan/娱乐系统/游戏数据/归笺.json", str(uid), 0)
        bait = await self.store.read_key(
            "BaiXuan/娱乐系统/钓鱼玩法/道具/诱饵.json", str(uid), 0
        )
        bank = await self.store.read_key(
            "BaiXuan/娱乐系统/游戏数据/银行系统/银行归笺.json", str(uid), 0
        )
        return jsonify({"ok": True, "uid": uid, "money": money, "bait": bait, "bank": bank})

    async def _web_data_save(self, req):
        from quart import jsonify
        try:
            body = await req.get_json() or {}
            uid = str(body.get("uid", ""))
            if not uid:
                return jsonify({"ok": False, "error": "缺少 uid"})
            if "money" in body:
                await self.store.write_key("BaiXuan/娱乐系统/游戏数据/归笺.json", uid, int(body["money"]))
            if "bait" in body:
                await self.store.write_key("BaiXuan/娱乐系统/钓鱼玩法/道具/诱饵.json", uid, int(body["bait"]))
            if "bank" in body:
                await self.store.write_key(
                    "BaiXuan/娱乐系统/游戏数据/银行系统/银行归笺.json", uid, int(body["bank"])
                )
            return jsonify({"ok": True})
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(e)})

    # ---------- Web API：自动点赞 ----------

    async def _web_auto_like_get(self):
        from quart import jsonify
        mode = await self.store.read_key("BaiXuan/扩展功能/自动点赞/模式.json", "mode", "all")
        users = list((await self.store.read_json("BaiXuan/扩展功能/自动点赞/名单.json", {}) or {}).keys())
        return jsonify({"mode": mode, "users": users, "enabled": self.config.get("auto_like_enabled", False)})

    async def _web_auto_like_save(self, req):
        from quart import jsonify
        try:
            body = await req.get_json() or {}
            if "mode" in body:
                await self.store.write_key("BaiXuan/扩展功能/自动点赞/模式.json", "mode", body["mode"])
            if "users" in body:
                await self.store.write_json(
                    "BaiXuan/扩展功能/自动点赞/名单.json", {str(u): True for u in body["users"]}
                )
            if "enabled" in body:
                self.config["auto_like_enabled"] = bool(body["enabled"])
                self.config.save_config()
            return jsonify({"ok": True})
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(e)})

    # ---------- Web API：关于 ----------

    async def _web_about(self):
        from quart import jsonify
        return jsonify(
            {
                "name": "astrbot_plugin_ro_play",
                "display_name": "RO_Play",
                "version": "1.0.0",
                "source": "MKbot 2.3.4 (NapCat) → AstrBot",
                "desc": "群管 + 娱乐 + 音乐 + 视频解析的综合性 QQ 机器人插件",
            }
        )

    # ==================== 指令：娱乐 ====================

    @filter.command("签到", alias={"打卡"})
    async def cmd_sign_in(self, event: AstrMessageEvent):
        """每日签到，获得归笺与诱饵"""
        async for r in self._emit(event, "entertainment", "sign_in"):
            yield r

    @filter.command("签到排行榜")
    async def cmd_sign_rank(self, event: AstrMessageEvent):
        """签到排行榜"""
        async for r in self._emit(event, "entertainment", "sign_rank"):
            yield r

    @filter.command("钓鱼")
    async def cmd_fishing(self, event: AstrMessageEvent, times: int = 1):
        """钓鱼：/钓鱼 [次数]，次数为 1/5/10/20/50/100"""
        async for r in self._emit(event, "entertainment", "fishing", times=times):
            yield r

    @filter.command("我的鱼获", alias={"我的鱼篓"})
    async def cmd_my_fish(self, event: AstrMessageEvent):
        """查看我的鱼获"""
        async for r in self._emit(event, "entertainment", "my_fish"):
            yield r

    @filter.command("出售")
    async def cmd_sell_fish(self, event: AstrMessageEvent, args: str = ""):
        """出售鱼：/出售 全部鱼 或 /出售 鱼名 [数量]"""
        async for r in self._emit(event, "entertainment", "sell_fish", args=args):
            yield r

    @filter.command("银行系统")
    async def cmd_bank_menu(self, event: AstrMessageEvent):
        """银行系统菜单"""
        async for r in self._emit(event, "entertainment", "bank_menu"):
            yield r

    @filter.command("存款", alias={"存入"})
    async def cmd_bank_deposit(self, event: AstrMessageEvent, amount: str = ""):
        """存款：/存款 数量 或 /全部存款"""
        async for r in self._emit(event, "entertainment", "bank_deposit", amount=amount):
            yield r

    @filter.command("取款", alias={"取出"})
    async def cmd_bank_withdraw(self, event: AstrMessageEvent, amount: str = ""):
        """取款：/取款 数量 或 /全部取款"""
        async for r in self._emit(event, "entertainment", "bank_withdraw", amount=amount):
            yield r

    @filter.command("转移归笺")
    async def cmd_transfer(self, event: AstrMessageEvent, args: str = ""):
        """转移归笺：/转移归笺 #QQ #数量"""
        async for r in self._emit(event, "entertainment", "transfer", args=args):
            yield r

    @filter.command("存款排行榜", alias={"银行归笺排行榜"})
    async def cmd_bank_rank(self, event: AstrMessageEvent):
        """存款排行榜"""
        async for r in self._emit(event, "entertainment", "bank_rank"):
            yield r

    @filter.command("归笺排行榜")
    async def cmd_money_rank(self, event: AstrMessageEvent):
        """归笺排行榜"""
        async for r in self._emit(event, "entertainment", "money_rank"):
            yield r

    @filter.command("幸运轮盘")
    async def cmd_roulette(self, event: AstrMessageEvent, amount: str = ""):
        """幸运轮盘：/幸运轮盘 数量"""
        async for r in self._emit(event, "entertainment", "roulette", amount=amount):
            yield r

    @filter.command("打劫")
    async def cmd_rob(self, event: AstrMessageEvent):
        """打劫：/打劫 @目标"""
        async for r in self._emit(event, "entertainment", "rob"):
            yield r

    @filter.command("今日运势")
    async def cmd_fortune(self, event: AstrMessageEvent):
        """今日运势"""
        async for r in self._emit(event, "entertainment", "fortune"):
            yield r

    @filter.command("我的信息", alias={"我的货币", "我的归笺"})
    async def cmd_my_info(self, event: AstrMessageEvent):
        """查看我的信息"""
        async for r in self._emit(event, "entertainment", "my_info"):
            yield r

    @filter.command("商店")
    async def cmd_shop(self, event: AstrMessageEvent):
        """刷新每日商店货架"""
        async for r in self._emit(event, "entertainment", "shop"):
            yield r

    @filter.command("买")
    async def cmd_buy(self, event: AstrMessageEvent, args: str = ""):
        """购买道具：/买 #名称 #数量"""
        async for r in self._emit(event, "entertainment", "buy", args=args):
            yield r

    # ==================== 指令：群老婆 / 漂流瓶 ====================

    @filter.command("今日老婆", alias={"今日老公"})
    async def cmd_wife_today(self, event: AstrMessageEvent):
        """今日老婆/老公"""
        async for r in self._emit(event, "group_wife", "today"):
            yield r

    @filter.command("我的老婆", alias={"我的老公"})
    async def cmd_wife_mine(self, event: AstrMessageEvent):
        """我的老婆/老公"""
        async for r in self._emit(event, "group_wife", "mine"):
            yield r

    @filter.command("更换老婆", alias={"更换老公"})
    async def cmd_wife_change(self, event: AstrMessageEvent):
        """更换老婆/老公"""
        async for r in self._emit(event, "group_wife", "change"):
            yield r

    @filter.command("换群老婆")
    async def cmd_wife_switch(self, event: AstrMessageEvent):
        """换群老婆（切换抽取范围群）"""
        async for r in self._emit(event, "group_wife", "switch_group"):
            yield r

    @filter.command("漂流瓶")
    async def cmd_bottle_menu(self, event: AstrMessageEvent):
        """漂流瓶菜单"""
        async for r in self._emit(event, "drift_bottle", "menu"):
            yield r

    @filter.command("抛瓶子")
    async def cmd_bottle_throw(self, event: AstrMessageEvent, content: str = ""):
        """抛瓶子：/抛瓶子 内容（可附图片）"""
        async for r in self._emit(event, "drift_bottle", "throw_bottle", content=content):
            yield r

    @filter.command("捞瓶子", alias={"捡瓶子"})
    async def cmd_bottle_pick(self, event: AstrMessageEvent):
        """捞瓶子"""
        async for r in self._emit(event, "drift_bottle", "pick_bottle"):
            yield r

    @filter.command("我的瓶子")
    async def cmd_bottle_mine(self, event: AstrMessageEvent):
        """我的瓶子"""
        async for r in self._emit(event, "drift_bottle", "my_bottles"):
            yield r

    @filter.command("查瓶子")
    async def cmd_bottle_query(self, event: AstrMessageEvent, bottle_id: str = ""):
        """查瓶子：/查瓶子 ID"""
        async for r in self._emit(event, "drift_bottle", "query_bottle", bottle_id=bottle_id):
            yield r

    @filter.command("删瓶子")
    async def cmd_bottle_delete(self, event: AstrMessageEvent, bottle_id: str = ""):
        """删瓶子：/删瓶子 ID"""
        async for r in self._emit(event, "drift_bottle", "delete_bottle", bottle_id=bottle_id):
            yield r

    @filter.command("赞此瓶子")
    async def cmd_bottle_like(self, event: AstrMessageEvent, bottle_id: str = ""):
        """赞此瓶子"""
        async for r in self._emit(event, "drift_bottle", "like_bottle", bottle_id=bottle_id):
            yield r

    @filter.command("踩此瓶子")
    async def cmd_bottle_dislike(self, event: AstrMessageEvent, bottle_id: str = ""):
        """踩此瓶子"""
        async for r in self._emit(event, "drift_bottle", "dislike_bottle", bottle_id=bottle_id):
            yield r

    # ==================== 指令：音乐 ====================

    @filter.command("点歌")
    async def cmd_music_search(self, event: AstrMessageEvent, name: str = ""):
        """点歌：/点歌 歌名（使用配置默认音源）"""
        async for r in self._emit(event, "music", "search", name=name, source=""):
            yield r

    @filter.command("选歌")
    async def cmd_music_pick(self, event: AstrMessageEvent, index: str = ""):
        """选歌：/选歌 序号（或 /链接选歌 序号 /语音选歌 序号）"""
        async for r in self._emit(event, "music", "pick", index=index, mode="卡片"):
            yield r

    @filter.command("收藏音乐", alias={"收藏歌曲"})
    async def cmd_music_fav(self, event: AstrMessageEvent, index: str = ""):
        """收藏音乐：/收藏音乐 序号"""
        async for r in self._emit(event, "music", "favorite", index=index):
            yield r

    @filter.command("取消收藏")
    async def cmd_music_unfav(self, event: AstrMessageEvent, index: str = ""):
        """取消收藏：/取消收藏 序号"""
        async for r in self._emit(event, "music", "unfavorite", index=index):
            yield r

    @filter.command("我的收藏", alias={"个人歌单"})
    async def cmd_music_favlist(self, event: AstrMessageEvent):
        """我的收藏"""
        async for r in self._emit(event, "music", "fav_list"):
            yield r

    @filter.command("清空个人收藏", alias={"清空个人歌曲"})
    async def cmd_music_clearfav(self, event: AstrMessageEvent):
        """清空个人收藏"""
        async for r in self._emit(event, "music", "clear_fav"):
            yield r

    @filter.command("播放收藏")
    async def cmd_music_playfav(self, event: AstrMessageEvent, index: str = ""):
        """播放收藏：/播放收藏 序号"""
        async for r in self._emit(event, "music", "play_fav", index=index):
            yield r

    # ==================== 指令：问答 ====================

    @filter.command("添加精准问答")
    async def cmd_qa_add_exact(self, event: AstrMessageEvent, args: str = ""):
        """添加精准问答：/添加精准问答 #问题 #答案"""
        async for r in self._emit(event, "qa", "add_exact", args=args):
            yield r

    @filter.command("删除精准问答")
    async def cmd_qa_del_exact(self, event: AstrMessageEvent, args: str = ""):
        """删除精准问答：/删除精准问答 #问题"""
        async for r in self._emit(event, "qa", "del_exact", args=args):
            yield r

    @filter.command("添加模糊问答")
    async def cmd_qa_add_fuzzy(self, event: AstrMessageEvent, args: str = ""):
        """添加模糊问答：/添加模糊问答 #关键词 #答案"""
        async for r in self._emit(event, "qa", "add_fuzzy", args=args):
            yield r

    @filter.command("删除模糊问答")
    async def cmd_qa_del_fuzzy(self, event: AstrMessageEvent, args: str = ""):
        """删除模糊问答：/删除模糊问答 #关键词"""
        async for r in self._emit(event, "qa", "del_fuzzy", args=args):
            yield r

    @filter.command("问答词列表")
    async def cmd_qa_list(self, event: AstrMessageEvent):
        """问答词列表"""
        async for r in self._emit(event, "qa", "list"):
            yield r

    # ==================== 指令：授权 ====================

    @filter.command("授权系统")
    async def cmd_license_menu(self, event: AstrMessageEvent):
        """授权系统菜单"""
        async for r in self._emit(event, "license", "menu"):
            yield r

    @filter.command("授权判断")
    async def cmd_license_check(self, event: AstrMessageEvent, gid: str = ""):
        """授权判断：/授权判断 或 /授权判断 群号"""
        async for r in self._emit(event, "license", "check", gid=gid):
            yield r

    @filter.command("使用卡密")
    async def cmd_license_use(self, event: AstrMessageEvent, card: str = ""):
        """使用卡密：/使用卡密 卡密"""
        async for r in self._emit(event, "license", "use_card", card=card):
            yield r

    @filter.command("卡密列表")
    async def cmd_license_list(self, event: AstrMessageEvent):
        """卡密列表"""
        async for r in self._emit(event, "license", "card_list"):
            yield r

    @filter.command("生成卡密")
    async def cmd_license_gen(self, event: AstrMessageEvent, args: str = ""):
        """生成卡密：/生成卡密 类型 [数量]，类型为 天/周/月/半年/年/永久"""
        async for r in self._emit(event, "license", "generate", args=args):
            yield r

    @filter.command("删除卡密")
    async def cmd_license_del(self, event: AstrMessageEvent, card: str = ""):
        """删除卡密：/删除卡密 卡密"""
        async for r in self._emit(event, "license", "delete_card", card=card):
            yield r

    @filter.command("添加授权")
    async def cmd_license_add(self, event: AstrMessageEvent, args: str = ""):
        """添加授权：/添加授权 类型 群号"""
        async for r in self._emit(event, "license", "add_license", args=args):
            yield r

    @filter.command("删除授权")
    async def cmd_license_remove(self, event: AstrMessageEvent, gid: str = ""):
        """删除授权：/删除授权 群号"""
        async for r in self._emit(event, "license", "remove_license", gid=gid):
            yield r

    # ==================== 指令：群管（admin 指令组） ====================

    @filter.command_group("admin")
    def admin():
        """群管指令组：/admin mute|kick|promote|..."""

    @admin.command("mute")
    async def admin_mute(self, event: AstrMessageEvent, seconds: int = 60):
        """禁言：/admin mute 秒数（默认60），需 @ 目标"""
        async for r in self._emit(event, "admin", "mute", seconds=seconds):
            yield r

    @admin.command("unmute")
    async def admin_unmute(self, event: AstrMessageEvent):
        """解禁：/admin unmute，需 @ 目标"""
        async for r in self._emit(event, "admin", "unmute"):
            yield r

    @admin.command("kick")
    async def admin_kick(self, event: AstrMessageEvent):
        """踢出：/admin kick，需 @ 目标"""
        async for r in self._emit(event, "admin", "kick"):
            yield r

    @admin.command("blackkick")
    async def admin_blackkick(self, event: AstrMessageEvent):
        """黑踢：/admin blackkick，需 @ 目标（拉黑踢出）"""
        async for r in self._emit(event, "admin", "black_kick"):
            yield r

    @admin.command("wholeban", alias={"全员禁言", "全体禁言"})
    async def admin_wholeban(self, event: AstrMessageEvent, enable: bool = True):
        """全体禁言：/admin wholeban 或 /admin wholeban false"""
        async for r in self._emit(event, "admin", "whole_ban", enable=enable):
            yield r

    @admin.command("promote")
    async def admin_promote(self, event: AstrMessageEvent):
        """上管：/admin promote，需 @ 目标"""
        async for r in self._emit(event, "admin", "promote"):
            yield r

    @admin.command("demote")
    async def admin_demote(self, event: AstrMessageEvent):
        """下管：/admin demote，需 @ 目标"""
        async for r in self._emit(event, "admin", "demote"):
            yield r

    @admin.command("banlist")
    async def admin_banlist(self, event: AstrMessageEvent):
        """获取禁言列表"""
        async for r in self._emit(event, "admin", "ban_list"):
            yield r

    @admin.command("unbanall")
    async def admin_unbanall(self, event: AstrMessageEvent):
        """全解群员：/admin unbanall"""
        async for r in self._emit(event, "admin", "unban_all"):
            yield r

    # ==================== 指令：群管（扁平） ====================

    @filter.command("禁言")
    async def cmd_mute(self, event: AstrMessageEvent, seconds: int = 60):
        """禁言：/禁言 秒数（默认60），需 @ 目标"""
        async for r in self._emit(event, "admin", "mute", seconds=seconds):
            yield r

    @filter.command("解禁")
    async def cmd_unmute(self, event: AstrMessageEvent):
        """解禁：需 @ 目标"""
        async for r in self._emit(event, "admin", "unmute"):
            yield r

    @filter.command("踢出")
    async def cmd_kick(self, event: AstrMessageEvent):
        """踢出：需 @ 目标"""
        async for r in self._emit(event, "admin", "kick"):
            yield r

    @filter.command("黑踢")
    async def cmd_blackkick(self, event: AstrMessageEvent):
        """黑踢（拉黑踢出）：需 @ 目标"""
        async for r in self._emit(event, "admin", "black_kick"):
            yield r

    @filter.command("全体禁言", alias={"全员禁言", "全禁"})
    async def cmd_wholeban(self, event: AstrMessageEvent):
        """全体禁言"""
        async for r in self._emit(event, "admin", "whole_ban", enable=True):
            yield r

    @filter.command("全体解禁", alias={"全解"})
    async def cmd_wholeunban(self, event: AstrMessageEvent):
        """全体解禁"""
        async for r in self._emit(event, "admin", "whole_ban", enable=False):
            yield r

    @filter.command("全解群员")
    async def cmd_unbanall(self, event: AstrMessageEvent):
        """全解群员（遍历禁言列表逐一解禁）"""
        async for r in self._emit(event, "admin", "unban_all"):
            yield r

    @filter.command("获取禁言列表")
    async def cmd_banlist(self, event: AstrMessageEvent):
        """获取禁言列表"""
        async for r in self._emit(event, "admin", "ban_list"):
            yield r

    @filter.command("上管")
    async def cmd_promote(self, event: AstrMessageEvent):
        """上管：需 @ 目标"""
        async for r in self._emit(event, "admin", "promote"):
            yield r

    @filter.command("下管")
    async def cmd_demote(self, event: AstrMessageEvent):
        """下管：需 @ 目标"""
        async for r in self._emit(event, "admin", "demote"):
            yield r

    @filter.command("我要头衔")
    async def cmd_self_title(self, event: AstrMessageEvent, title: str = ""):
        """我要头衔：/我要头衔 内容"""
        async for r in self._emit(event, "admin", "self_title", title=title):
            yield r

    @filter.command("设置头衔")
    async def cmd_set_title(self, event: AstrMessageEvent, title: str = ""):
        """设置头衔：/设置头衔 内容，需 @ 目标"""
        async for r in self._emit(event, "admin", "set_title", title=title):
            yield r

    @filter.command("发公告")
    async def cmd_notice(self, event: AstrMessageEvent, content: str = ""):
        """发公告：/发公告 内容"""
        async for r in self._emit(event, "admin", "send_notice", content=content):
            yield r

    @filter.command("执行群发")
    async def cmd_broadcast(self, event: AstrMessageEvent, content: str = ""):
        """执行群发：/执行群发 内容（加☆前缀则@全体）"""
        async for r in self._emit(event, "admin", "broadcast", content=content):
            yield r

    @filter.command("获取可群发列表", alias={"查看可群发列表"})
    async def cmd_broadcast_list(self, event: AstrMessageEvent):
        """获取可群发列表"""
        async for r in self._emit(event, "admin", "broadcast_list"):
            yield r

    @filter.command("新增可群发目标")
    async def cmd_broadcast_add(self, event: AstrMessageEvent, gid: str = ""):
        """新增可群发目标：/新增可群发目标 群号"""
        async for r in self._emit(event, "admin", "broadcast_add", gid=gid):
            yield r

    @filter.command("取消可群发目标")
    async def cmd_broadcast_del(self, event: AstrMessageEvent, gid: str = ""):
        """取消可群发目标：/取消可群发目标 群号"""
        async for r in self._emit(event, "admin", "broadcast_del", gid=gid):
            yield r

    # ==================== 指令：续火 / 发卡 ====================

    @filter.command("设置续火内容")
    async def cmd_fire_content(self, event: AstrMessageEvent, content: str = ""):
        """设置续火内容：/设置续火内容 内容"""
        async for r in self._emit(event, "firekeep", "set_content", content=content):
            yield r

    @filter.command("设置续火模式")
    async def cmd_fire_mode(self, event: AstrMessageEvent, mode: str = ""):
        """设置续火模式：/设置续火模式 文案|图片"""
        async for r in self._emit(event, "firekeep", "set_mode", mode=mode):
            yield r

    @filter.command("管理续火")
    async def cmd_fire_manage(self, event: AstrMessageEvent):
        """续火状态总览"""
        async for r in self._emit(event, "firekeep", "manage"):
            yield r

    @filter.command("发卡商店")
    async def cmd_shop_cards(self, event: AstrMessageEvent):
        """发卡商店（展示上架商品+库存）"""
        async for r in self._emit(event, "card_shop", "shop"):
            yield r

    @filter.command("兑换商品")
    async def cmd_exchange(self, event: AstrMessageEvent, args: str = ""):
        """兑换商品：/兑换商品 名称 数量"""
        async for r in self._emit(event, "card_shop", "exchange", args=args):
            yield r

    @filter.command("添加发卡商品")
    async def cmd_card_add(self, event: AstrMessageEvent, name: str = ""):
        """添加发卡商品（主人）：/添加发卡商品 名称"""
        async for r in self._emit(event, "card_shop", "add_product", name=name):
            yield r

    @filter.command("填充发卡商品")
    async def cmd_card_fill(self, event: AstrMessageEvent, args: str = ""):
        """填充发卡商品（主人）：/填充发卡商品 商品名\n内容..."""
        async for r in self._emit(event, "card_shop", "fill_product", args=args):
            yield r

    @filter.command("发卡商品定价")
    async def cmd_card_price(self, event: AstrMessageEvent, args: str = ""):
        """发卡商品定价（主人）：/发卡商品定价 名称 价格"""
        async for r in self._emit(event, "card_shop", "set_price", args=args):
            yield r

    @filter.command("发卡商品上架")
    async def cmd_card_on(self, event: AstrMessageEvent, name: str = ""):
        """发卡商品上架（主人）"""
        async for r in self._emit(event, "card_shop", "shelf", name=name, on=True):
            yield r

    @filter.command("发卡商品下架")
    async def cmd_card_off(self, event: AstrMessageEvent, name: str = ""):
        """发卡商品下架（主人）"""
        async for r in self._emit(event, "card_shop", "shelf", name=name, on=False):
            yield r

    @filter.command("清空发卡商品")
    async def cmd_card_clear(self, event: AstrMessageEvent, name: str = ""):
        """清空发卡商品（主人）"""
        async for r in self._emit(event, "card_shop", "clear_product", name=name):
            yield r

    # ==================== 指令：工具 ====================

    @filter.command("发病文学")
    async def cmd_fabing(self, event: AstrMessageEvent, target: str = ""):
        """发病文学：/发病文学 对象名"""
        async for r in self._emit(event, "tools", "fabing", target=target):
            yield r

    @filter.command("三角洲密码", alias={"sjz密码", "每日密码"})
    async def cmd_delta(self, event: AstrMessageEvent):
        """三角洲行动每日密码"""
        async for r in self._emit(event, "tools", "delta_password"):
            yield r

    @filter.command("EPIC免费游戏", alias={"epic免费游戏"})
    async def cmd_epic(self, event: AstrMessageEvent):
        """EPIC 免费游戏"""
        async for r in self._emit(event, "tools", "epic_games"):
            yield r

    @filter.command("搜饰品")
    async def cmd_skin(self, event: AstrMessageEvent, keyword: str = ""):
        """搜饰品：/搜饰品 关键词"""
        async for r in self._emit(event, "tools", "search_skin", keyword=keyword):
            yield r

    @filter.command("查MC服务器")
    async def cmd_mc(self, event: AstrMessageEvent, address: str = ""):
        """查MC服务器：/查MC服务器 IP"""
        async for r in self._emit(event, "tools", "mc_server", address=address):
            yield r

    @filter.command("图转链接")
    async def cmd_img2url(self, event: AstrMessageEvent):
        """图转链接（提取消息内图片URL）"""
        async for r in self._emit(event, "tools", "img_to_url"):
            yield r

    @filter.command("运行状态")
    async def cmd_status(self, event: AstrMessageEvent):
        """运行状态"""
        async for r in self._emit(event, "tools", "status"):
            yield r

    @filter.command("赞我", alias={"点赞"})
    async def cmd_like_me(self, event: AstrMessageEvent):
        """赞我"""
        async for r in self._emit(event, "tools", "like_me"):
            yield r

    @filter.command("拍我", alias={"截我"})
    async def cmd_poke_me(self, event: AstrMessageEvent):
        """拍我"""
        async for r in self._emit(event, "tools", "poke_me"):
            yield r

    @filter.command("伪造聊天")
    async def cmd_fake_chat(self, event: AstrMessageEvent, payload: str = ""):
        """伪造聊天：/伪造聊天 JSON数组"""
        async for r in self._emit(event, "fake_chat", "fake", payload=payload):
            yield r

    @filter.command("设置马甲内容")
    async def cmd_masq_set(self, event: AstrMessageEvent, prefix: str = ""):
        """设置马甲内容：/设置马甲内容 前缀"""
        async for r in self._emit(event, "masquerade", "set_prefix", prefix=prefix):
            yield r

    @filter.command("全员马甲")
    async def cmd_masq_all(self, event: AstrMessageEvent, prefix: str = ""):
        """全员马甲：/全员马甲 前缀"""
        async for r in self._emit(event, "masquerade", "apply_all", prefix=prefix):
            yield r

    @filter.command("开始记录")
    async def cmd_jpm_start(self, event: AstrMessageEvent, gid: str = ""):
        """开始记录入群私聊：/开始记录 群号（300秒收录窗口）"""
        async for r in self._emit(event, "join_pm", "start_record", gid=gid):
            yield r

    @filter.command("结束记录")
    async def cmd_jpm_stop(self, event: AstrMessageEvent):
        """结束记录"""
        async for r in self._emit(event, "join_pm", "stop_record"):
            yield r

    @filter.command("查看记录内容")
    async def cmd_jpm_view(self, event: AstrMessageEvent, gid: str = ""):
        """查看记录内容：/查看记录内容 群号"""
        async for r in self._emit(event, "join_pm", "view_record", gid=gid):
            yield r

    @filter.command("设置入群私聊概率")
    async def cmd_jpm_prob(self, event: AstrMessageEvent, args: str = ""):
        """设置入群私聊概率：/设置入群私聊概率 群号 概率%"""
        async for r in self._emit(event, "join_pm", "set_probability", args=args):
            yield r

    @filter.command("获取本群成员", alias={"群成员列表"})
    async def cmd_members(self, event: AstrMessageEvent):
        """获取本群成员"""
        async for r in self._emit(event, "admin", "member_list"):
            yield r

    # ==================== 指令：事件开关（通用） ====================

    @filter.command("开启事件")
    async def cmd_event_on(self, event: AstrMessageEvent, name: str = ""):
        """开启事件：/开启事件 事件名"""
        async for r in self._emit(event, "admin", "set_event", name=name, enabled=True):
            yield r

    @filter.command("关闭事件")
    async def cmd_event_off(self, event: AstrMessageEvent, name: str = ""):
        """关闭事件：/关闭事件 事件名"""
        async for r in self._emit(event, "admin", "set_event", name=name, enabled=False):
            yield r

    @filter.command("事件列表")
    async def cmd_event_list(self, event: AstrMessageEvent):
        """查看本群事件开关列表"""
        async for r in self._emit(event, "admin", "event_list"):
            yield r

    # ==================== 指令：重启 / 更新 ====================

    @filter.command("重启服务")
    async def cmd_restart(self, event: AstrMessageEvent):
        """重启 AstrBot 服务（主人）"""
        async for r in self._emit(event, "tools", "restart"):
            yield r
