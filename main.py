from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path
from typing import Any

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

PLUGIN_NAME = "ro_play_plugin"
TEMPLATES_SRC = Path(__file__).resolve().parent / "data" / "templates"

class Main(Star):

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self.name = PLUGIN_NAME
        self.data_path = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        self.data_path.mkdir(parents=True, exist_ok=True)

        self.store = DataStore(self.data_path)
        self.api = ApiClient(self)
        self.sender = Sender(self)
        self.render = Renderer(self)
        self.perm = Permission(self)
        self.notice = NoticeHandler(self)
        self.scheduler = Scheduler(self)

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

    @filter.on_astrbot_loaded()
    async def on_loaded(self) -> None:

        await self._migrate_templates()
        self._tasks.append(asyncio.create_task(self.scheduler.run_hourly()))
        self._tasks.append(asyncio.create_task(self.scheduler.run_broadcast()))
        logger.info("RO_Play 插件已加载，数据目录: %s", self.data_path)

    async def terminate(self) -> None:

        self.scheduler.stop()
        for t in self._tasks:
            t.cancel()
        for m in self.modules.values():
            if hasattr(m, "terminate"):
                try:
                    await m.terminate()
                except Exception:
                    pass
        logger.info("RO_Play 插件已卸载")

    async def _migrate_templates(self) -> None:

        if self._templates_migrated:
            return
        dst = self.data_path / "templates"
        dst.mkdir(parents=True, exist_ok=True)
        try:
            if TEMPLATES_SRC.exists():
                shutil.copytree(TEMPLATES_SRC, dst, dirs_exist_ok=True)
            self._templates_migrated = True
        except Exception as e:
            logger.error(f"模板迁移失败: {e}")

    async def group_event_enabled(self, gid: str, key: str) -> bool:

        if not gid:
            return False
        data = await self.store.read_json(f"BaiXuan/事件系统/{gid}.json", {})
        if key in (data or {}):
            return bool(data[key])
        return bool((self.config.get("default_events", {}) or {}).get(key, False))

    async def set_group_event(self, gid: str, key: str, value: bool) -> None:
        await self.store.write_key(f"BaiXuan/事件系统/{gid}.json", key, value)

    async def global_event_enabled(self, key: str) -> bool:

        data = await self.store.read_json("BaiXuan/事件系统/全局.json", {})
        return bool((data or {}).get(key, False))

    async def deep_entertainment_enabled(self) -> bool:

        rel = str(self.config.get("deep_entertainment_path", "")).strip()
        if not rel:
            return True
        return await self.store.read_key(rel, "enabled", False)

    async def _emit(self, event: AstrMessageEvent, mod: str, meth: str, **kw):

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
        except Exception as e:
            logger.error(f"模块 {mod}.{meth} 出错: {e}")
            yield event.plain_result(f"指令执行出错：{type(e).__name__}: {e}")

    async def _emit_direct(self, event: AstrMessageEvent, res: Any) -> None:

        if res is None:
            return
        if isinstance(res, list):
            for r in res:
                await event.send(r if isinstance(r, MessageEventResult) else event.plain_result(str(r)))
        elif isinstance(res, MessageEventResult):
            await event.send(res)
        else:
            await event.send(event.plain_result(str(res)))

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_all_message(self, event: AstrMessageEvent) -> None:

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

        if self._is_self_sender(event) and not self.config.get("self_trigger", False):
            return

        if not await self._in_whitelist(event):
            return

        await self._record_umo(event)
        await self._passive_features(event, text)

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
            except Exception as e:
                logger.error(f"legacy {type(inst).__name__} 异常: {e}")

    def _is_self_sender(self, event: AstrMessageEvent) -> bool:
        try:
            bot_id = event.message_obj.self_id if event.message_obj else None
            return bool(bot_id) and str(event.get_sender_id()) == str(bot_id)
        except Exception:
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

        try:
            umo = event.unified_msg_origin
            gid = event.get_group_id()
            if gid:
                await self.put_kv_data(f"umo/group_{gid}", umo)
            else:
                await self.put_kv_data(f"umo/private_{event.get_sender_id()}", umo)
        except Exception:
            pass

    async def _passive_features(self, event: AstrMessageEvent, text: str) -> None:

        gid = event.get_group_id()

        if gid and await self.group_event_enabled(gid, "prohibited"):
            await self._try_passive(event, "blacklist", "check_message")

        if gid and await self.group_event_enabled(gid, "qa"):
            await self._try_passive(event, "qa", "on_message")

        if gid and await self.group_event_enabled(gid, "talk_stats"):
            await self._try_passive(event, "talk_stats", "count")

        if gid and await self.group_event_enabled(gid, "video_parse") and text:
            await self._try_passive(event, "tools", "video_scan")

    async def _try_passive(self, event: AstrMessageEvent, mod: str, meth: str) -> None:
        try:
            inst = self.modules.get(mod)
            if inst and hasattr(inst, meth):
                await getattr(inst, meth)(event)
        except Exception as e:
            logger.error(f"被动功能 {mod}.{meth} 异常: {e}")

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
        except Exception as e:
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
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @staticmethod
    def _req_arg(key: str) -> str:
        try:
            from quart import request
            return request.args.get(key, "")
        except Exception:
            return ""

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
        except Exception as e:
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
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

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
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

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
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    async def _web_about(self):
        from quart import jsonify
        return jsonify(
            {
                "name": "ro_play_plugin",
                "display_name": "RO_Play",
                "version": "1.0.0",
                "source": "AstrBot",
                "desc": "群管 + 娱乐 + 音乐 + 视频解析的综合性 QQ 机器人插件",
            }
        )

    @filter.command("签到", alias={"打卡"})
    async def cmd_sign_in(self, event: AstrMessageEvent):

        async for r in self._emit(event, "entertainment", "sign_in"):
            yield r

    @filter.command("签到排行榜")
    async def cmd_sign_rank(self, event: AstrMessageEvent):

        async for r in self._emit(event, "entertainment", "sign_rank"):
            yield r

    @filter.command("钓鱼")
    async def cmd_fishing(self, event: AstrMessageEvent, times: int = 1):

        async for r in self._emit(event, "entertainment", "fishing", times=times):
            yield r

    @filter.command("我的鱼获", alias={"我的鱼篓"})
    async def cmd_my_fish(self, event: AstrMessageEvent):

        async for r in self._emit(event, "entertainment", "my_fish"):
            yield r

    @filter.command("出售")
    async def cmd_sell_fish(self, event: AstrMessageEvent, args: str = ""):

        async for r in self._emit(event, "entertainment", "sell_fish", args=args):
            yield r

    @filter.command("银行系统")
    async def cmd_bank_menu(self, event: AstrMessageEvent):

        async for r in self._emit(event, "entertainment", "bank_menu"):
            yield r

    @filter.command("存款", alias={"存入"})
    async def cmd_bank_deposit(self, event: AstrMessageEvent, amount: str = ""):

        async for r in self._emit(event, "entertainment", "bank_deposit", amount=amount):
            yield r

    @filter.command("取款", alias={"取出"})
    async def cmd_bank_withdraw(self, event: AstrMessageEvent, amount: str = ""):

        async for r in self._emit(event, "entertainment", "bank_withdraw", amount=amount):
            yield r

    @filter.command("转移归笺")
    async def cmd_transfer(self, event: AstrMessageEvent, args: str = ""):

        async for r in self._emit(event, "entertainment", "transfer", args=args):
            yield r

    @filter.command("存款排行榜", alias={"银行归笺排行榜"})
    async def cmd_bank_rank(self, event: AstrMessageEvent):

        async for r in self._emit(event, "entertainment", "bank_rank"):
            yield r

    @filter.command("归笺排行榜")
    async def cmd_money_rank(self, event: AstrMessageEvent):

        async for r in self._emit(event, "entertainment", "money_rank"):
            yield r

    @filter.command("幸运轮盘")
    async def cmd_roulette(self, event: AstrMessageEvent, amount: str = ""):

        async for r in self._emit(event, "entertainment", "roulette", amount=amount):
            yield r

    @filter.command("打劫")
    async def cmd_rob(self, event: AstrMessageEvent):

        async for r in self._emit(event, "entertainment", "rob"):
            yield r

    @filter.command("今日运势")
    async def cmd_fortune(self, event: AstrMessageEvent):

        async for r in self._emit(event, "entertainment", "fortune"):
            yield r

    @filter.command("我的信息", alias={"我的货币", "我的归笺"})
    async def cmd_my_info(self, event: AstrMessageEvent):

        async for r in self._emit(event, "entertainment", "my_info"):
            yield r

    @filter.command("商店")
    async def cmd_shop(self, event: AstrMessageEvent):

        async for r in self._emit(event, "entertainment", "shop"):
            yield r

    @filter.command("买")
    async def cmd_buy(self, event: AstrMessageEvent, args: str = ""):

        async for r in self._emit(event, "entertainment", "buy", args=args):
            yield r

    @filter.command("今日老婆", alias={"今日老公"})
    async def cmd_wife_today(self, event: AstrMessageEvent):

        async for r in self._emit(event, "group_wife", "today"):
            yield r

    @filter.command("我的老婆", alias={"我的老公"})
    async def cmd_wife_mine(self, event: AstrMessageEvent):

        async for r in self._emit(event, "group_wife", "mine"):
            yield r

    @filter.command("更换老婆", alias={"更换老公"})
    async def cmd_wife_change(self, event: AstrMessageEvent):

        async for r in self._emit(event, "group_wife", "change"):
            yield r

    @filter.command("换群老婆")
    async def cmd_wife_switch(self, event: AstrMessageEvent):

        async for r in self._emit(event, "group_wife", "switch_group"):
            yield r

    @filter.command("漂流瓶")
    async def cmd_bottle_menu(self, event: AstrMessageEvent):

        async for r in self._emit(event, "drift_bottle", "menu"):
            yield r

    @filter.command("抛瓶子")
    async def cmd_bottle_throw(self, event: AstrMessageEvent, content: str = ""):

        async for r in self._emit(event, "drift_bottle", "throw_bottle", content=content):
            yield r

    @filter.command("捞瓶子", alias={"捡瓶子"})
    async def cmd_bottle_pick(self, event: AstrMessageEvent):

        async for r in self._emit(event, "drift_bottle", "pick_bottle"):
            yield r

    @filter.command("我的瓶子")
    async def cmd_bottle_mine(self, event: AstrMessageEvent):

        async for r in self._emit(event, "drift_bottle", "my_bottles"):
            yield r

    @filter.command("查瓶子")
    async def cmd_bottle_query(self, event: AstrMessageEvent, bottle_id: str = ""):

        async for r in self._emit(event, "drift_bottle", "query_bottle", bottle_id=bottle_id):
            yield r

    @filter.command("删瓶子")
    async def cmd_bottle_delete(self, event: AstrMessageEvent, bottle_id: str = ""):

        async for r in self._emit(event, "drift_bottle", "delete_bottle", bottle_id=bottle_id):
            yield r

    @filter.command("赞此瓶子")
    async def cmd_bottle_like(self, event: AstrMessageEvent, bottle_id: str = ""):

        async for r in self._emit(event, "drift_bottle", "like_bottle", bottle_id=bottle_id):
            yield r

    @filter.command("踩此瓶子")
    async def cmd_bottle_dislike(self, event: AstrMessageEvent, bottle_id: str = ""):

        async for r in self._emit(event, "drift_bottle", "dislike_bottle", bottle_id=bottle_id):
            yield r

    @filter.command("点歌")
    async def cmd_music_search(self, event: AstrMessageEvent, name: str = ""):

        async for r in self._emit(event, "music", "search", name=name, source=""):
            yield r

    @filter.command("选歌")
    async def cmd_music_pick(self, event: AstrMessageEvent, index: str = ""):

        async for r in self._emit(event, "music", "pick", index=index, mode="卡片"):
            yield r

    @filter.command("收藏音乐", alias={"收藏歌曲"})
    async def cmd_music_fav(self, event: AstrMessageEvent, index: str = ""):

        async for r in self._emit(event, "music", "favorite", index=index):
            yield r

    @filter.command("取消收藏")
    async def cmd_music_unfav(self, event: AstrMessageEvent, index: str = ""):

        async for r in self._emit(event, "music", "unfavorite", index=index):
            yield r

    @filter.command("我的收藏", alias={"个人歌单"})
    async def cmd_music_favlist(self, event: AstrMessageEvent):

        async for r in self._emit(event, "music", "fav_list"):
            yield r

    @filter.command("清空个人收藏", alias={"清空个人歌曲"})
    async def cmd_music_clearfav(self, event: AstrMessageEvent):

        async for r in self._emit(event, "music", "clear_fav"):
            yield r

    @filter.command("播放收藏")
    async def cmd_music_playfav(self, event: AstrMessageEvent, index: str = ""):

        async for r in self._emit(event, "music", "play_fav", index=index):
            yield r

    @filter.command("添加精准问答")
    async def cmd_qa_add_exact(self, event: AstrMessageEvent, args: str = ""):

        async for r in self._emit(event, "qa", "add_exact", args=args):
            yield r

    @filter.command("删除精准问答")
    async def cmd_qa_del_exact(self, event: AstrMessageEvent, args: str = ""):

        async for r in self._emit(event, "qa", "del_exact", args=args):
            yield r

    @filter.command("添加模糊问答")
    async def cmd_qa_add_fuzzy(self, event: AstrMessageEvent, args: str = ""):

        async for r in self._emit(event, "qa", "add_fuzzy", args=args):
            yield r

    @filter.command("删除模糊问答")
    async def cmd_qa_del_fuzzy(self, event: AstrMessageEvent, args: str = ""):

        async for r in self._emit(event, "qa", "del_fuzzy", args=args):
            yield r

    @filter.command("问答词列表")
    async def cmd_qa_list(self, event: AstrMessageEvent):

        async for r in self._emit(event, "qa", "list"):
            yield r

    @filter.command("授权系统")
    async def cmd_license_menu(self, event: AstrMessageEvent):

        async for r in self._emit(event, "license", "menu"):
            yield r

    @filter.command("授权判断")
    async def cmd_license_check(self, event: AstrMessageEvent, gid: str = ""):

        async for r in self._emit(event, "license", "check", gid=gid):
            yield r

    @filter.command("使用卡密")
    async def cmd_license_use(self, event: AstrMessageEvent, card: str = ""):

        async for r in self._emit(event, "license", "use_card", card=card):
            yield r

    @filter.command("卡密列表")
    async def cmd_license_list(self, event: AstrMessageEvent):

        async for r in self._emit(event, "license", "card_list"):
            yield r

    @filter.command("生成卡密")
    async def cmd_license_gen(self, event: AstrMessageEvent, args: str = ""):

        async for r in self._emit(event, "license", "generate", args=args):
            yield r

    @filter.command("删除卡密")
    async def cmd_license_del(self, event: AstrMessageEvent, card: str = ""):

        async for r in self._emit(event, "license", "delete_card", card=card):
            yield r

    @filter.command("添加授权")
    async def cmd_license_add(self, event: AstrMessageEvent, args: str = ""):

        async for r in self._emit(event, "license", "add_license", args=args):
            yield r

    @filter.command("删除授权")
    async def cmd_license_remove(self, event: AstrMessageEvent, gid: str = ""):

        async for r in self._emit(event, "license", "remove_license", gid=gid):
            yield r

    @filter.command_group("admin")
    def admin():

    @admin.command("mute")
    async def admin_mute(self, event: AstrMessageEvent, seconds: int = 60):

        async for r in self._emit(event, "admin", "mute", seconds=seconds):
            yield r

    @admin.command("unmute")
    async def admin_unmute(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "unmute"):
            yield r

    @admin.command("kick")
    async def admin_kick(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "kick"):
            yield r

    @admin.command("blackkick")
    async def admin_blackkick(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "black_kick"):
            yield r

    @admin.command("wholeban", alias={"全员禁言", "全体禁言"})
    async def admin_wholeban(self, event: AstrMessageEvent, enable: bool = True):

        async for r in self._emit(event, "admin", "whole_ban", enable=enable):
            yield r

    @admin.command("promote")
    async def admin_promote(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "promote"):
            yield r

    @admin.command("demote")
    async def admin_demote(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "demote"):
            yield r

    @admin.command("banlist")
    async def admin_banlist(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "ban_list"):
            yield r

    @admin.command("unbanall")
    async def admin_unbanall(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "unban_all"):
            yield r

    @filter.command("禁言")
    async def cmd_mute(self, event: AstrMessageEvent, seconds: int = 60):

        async for r in self._emit(event, "admin", "mute", seconds=seconds):
            yield r

    @filter.command("解禁")
    async def cmd_unmute(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "unmute"):
            yield r

    @filter.command("踢出")
    async def cmd_kick(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "kick"):
            yield r

    @filter.command("黑踢")
    async def cmd_blackkick(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "black_kick"):
            yield r

    @filter.command("全体禁言", alias={"全员禁言", "全禁"})
    async def cmd_wholeban(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "whole_ban", enable=True):
            yield r

    @filter.command("全体解禁", alias={"全解"})
    async def cmd_wholeunban(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "whole_ban", enable=False):
            yield r

    @filter.command("全解群员")
    async def cmd_unbanall(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "unban_all"):
            yield r

    @filter.command("获取禁言列表")
    async def cmd_banlist(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "ban_list"):
            yield r

    @filter.command("上管")
    async def cmd_promote(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "promote"):
            yield r

    @filter.command("下管")
    async def cmd_demote(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "demote"):
            yield r

    @filter.command("我要头衔")
    async def cmd_self_title(self, event: AstrMessageEvent, title: str = ""):

        async for r in self._emit(event, "admin", "self_title", title=title):
            yield r

    @filter.command("设置头衔")
    async def cmd_set_title(self, event: AstrMessageEvent, title: str = ""):

        async for r in self._emit(event, "admin", "set_title", title=title):
            yield r

    @filter.command("发公告")
    async def cmd_notice(self, event: AstrMessageEvent, content: str = ""):

        async for r in self._emit(event, "admin", "send_notice", content=content):
            yield r

    @filter.command("执行群发")
    async def cmd_broadcast(self, event: AstrMessageEvent, content: str = ""):

        async for r in self._emit(event, "admin", "broadcast", content=content):
            yield r

    @filter.command("获取可群发列表", alias={"查看可群发列表"})
    async def cmd_broadcast_list(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "broadcast_list"):
            yield r

    @filter.command("新增可群发目标")
    async def cmd_broadcast_add(self, event: AstrMessageEvent, gid: str = ""):

        async for r in self._emit(event, "admin", "broadcast_add", gid=gid):
            yield r

    @filter.command("取消可群发目标")
    async def cmd_broadcast_del(self, event: AstrMessageEvent, gid: str = ""):

        async for r in self._emit(event, "admin", "broadcast_del", gid=gid):
            yield r

    @filter.command("设置续火内容")
    async def cmd_fire_content(self, event: AstrMessageEvent, content: str = ""):

        async for r in self._emit(event, "firekeep", "set_content", content=content):
            yield r

    @filter.command("设置续火模式")
    async def cmd_fire_mode(self, event: AstrMessageEvent, mode: str = ""):

        async for r in self._emit(event, "firekeep", "set_mode", mode=mode):
            yield r

    @filter.command("管理续火")
    async def cmd_fire_manage(self, event: AstrMessageEvent):

        async for r in self._emit(event, "firekeep", "manage"):
            yield r

    @filter.command("发卡商店")
    async def cmd_shop_cards(self, event: AstrMessageEvent):

        async for r in self._emit(event, "card_shop", "shop"):
            yield r

    @filter.command("兑换商品")
    async def cmd_exchange(self, event: AstrMessageEvent, args: str = ""):

        async for r in self._emit(event, "card_shop", "exchange", args=args):
            yield r

    @filter.command("添加发卡商品")
    async def cmd_card_add(self, event: AstrMessageEvent, name: str = ""):

        async for r in self._emit(event, "card_shop", "add_product", name=name):
            yield r

    @filter.command("填充发卡商品")
    async def cmd_card_fill(self, event: AstrMessageEvent, args: str = ""):

        async for r in self._emit(event, "card_shop", "fill_product", args=args):
            yield r

    @filter.command("发卡商品定价")
    async def cmd_card_price(self, event: AstrMessageEvent, args: str = ""):

        async for r in self._emit(event, "card_shop", "set_price", args=args):
            yield r

    @filter.command("发卡商品上架")
    async def cmd_card_on(self, event: AstrMessageEvent, name: str = ""):

        async for r in self._emit(event, "card_shop", "shelf", name=name, on=True):
            yield r

    @filter.command("发卡商品下架")
    async def cmd_card_off(self, event: AstrMessageEvent, name: str = ""):

        async for r in self._emit(event, "card_shop", "shelf", name=name, on=False):
            yield r

    @filter.command("清空发卡商品")
    async def cmd_card_clear(self, event: AstrMessageEvent, name: str = ""):

        async for r in self._emit(event, "card_shop", "clear_product", name=name):
            yield r

    @filter.command("发病文学")
    async def cmd_fabing(self, event: AstrMessageEvent, target: str = ""):

        async for r in self._emit(event, "tools", "fabing", target=target):
            yield r

    @filter.command("三角洲密码", alias={"sjz密码", "每日密码"})
    async def cmd_delta(self, event: AstrMessageEvent):

        async for r in self._emit(event, "tools", "delta_password"):
            yield r

    @filter.command("EPIC免费游戏", alias={"epic免费游戏"})
    async def cmd_epic(self, event: AstrMessageEvent):

        async for r in self._emit(event, "tools", "epic_games"):
            yield r

    @filter.command("搜饰品")
    async def cmd_skin(self, event: AstrMessageEvent, keyword: str = ""):

        async for r in self._emit(event, "tools", "search_skin", keyword=keyword):
            yield r

    @filter.command("查MC服务器")
    async def cmd_mc(self, event: AstrMessageEvent, address: str = ""):

        async for r in self._emit(event, "tools", "mc_server", address=address):
            yield r

    @filter.command("图转链接")
    async def cmd_img2url(self, event: AstrMessageEvent):

        async for r in self._emit(event, "tools", "img_to_url"):
            yield r

    @filter.command("运行状态")
    async def cmd_status(self, event: AstrMessageEvent):

        async for r in self._emit(event, "tools", "status"):
            yield r

    @filter.command("赞我", alias={"点赞"})
    async def cmd_like_me(self, event: AstrMessageEvent):

        async for r in self._emit(event, "tools", "like_me"):
            yield r

    @filter.command("拍我", alias={"截我"})
    async def cmd_poke_me(self, event: AstrMessageEvent):

        async for r in self._emit(event, "tools", "poke_me"):
            yield r

    @filter.command("伪造聊天")
    async def cmd_fake_chat(self, event: AstrMessageEvent, payload: str = ""):

        async for r in self._emit(event, "fake_chat", "fake", payload=payload):
            yield r

    @filter.command("设置马甲内容")
    async def cmd_masq_set(self, event: AstrMessageEvent, prefix: str = ""):

        async for r in self._emit(event, "masquerade", "set_prefix", prefix=prefix):
            yield r

    @filter.command("全员马甲")
    async def cmd_masq_all(self, event: AstrMessageEvent, prefix: str = ""):

        async for r in self._emit(event, "masquerade", "apply_all", prefix=prefix):
            yield r

    @filter.command("开始记录")
    async def cmd_jpm_start(self, event: AstrMessageEvent, gid: str = ""):

        async for r in self._emit(event, "join_pm", "start_record", gid=gid):
            yield r

    @filter.command("结束记录")
    async def cmd_jpm_stop(self, event: AstrMessageEvent):

        async for r in self._emit(event, "join_pm", "stop_record"):
            yield r

    @filter.command("查看记录内容")
    async def cmd_jpm_view(self, event: AstrMessageEvent, gid: str = ""):

        async for r in self._emit(event, "join_pm", "view_record", gid=gid):
            yield r

    @filter.command("设置入群私聊概率")
    async def cmd_jpm_prob(self, event: AstrMessageEvent, args: str = ""):

        async for r in self._emit(event, "join_pm", "set_probability", args=args):
            yield r

    @filter.command("获取本群成员", alias={"群成员列表"})
    async def cmd_members(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "member_list"):
            yield r

    @filter.command("开启事件")
    async def cmd_event_on(self, event: AstrMessageEvent, name: str = ""):

        async for r in self._emit(event, "admin", "set_event", name=name, enabled=True):
            yield r

    @filter.command("关闭事件")
    async def cmd_event_off(self, event: AstrMessageEvent, name: str = ""):

        async for r in self._emit(event, "admin", "set_event", name=name, enabled=False):
            yield r

    @filter.command("事件列表")
    async def cmd_event_list(self, event: AstrMessageEvent):

        async for r in self._emit(event, "admin", "event_list"):
            yield r

    @filter.command("重启服务")
    async def cmd_restart(self, event: AstrMessageEvent):

        async for r in self._emit(event, "tools", "restart"):
            yield r
