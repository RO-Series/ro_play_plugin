"""工具集模块（ToolsModule）。

对应原 index.mjs 的以下功能：
- L12542「发病文学[对象名]」、L12564「(cs)?搜饰品[关键词]」、
  L12670「查(MC|mc|我的世界)服务器[IP]」、L12725「(三角洲|sjz)(密码|每日密码)」、
  L12845「EPIC免费游戏」、L13772「运行状态」、L14860「重启服务」、
  L14915「获取声聊角色列表」、L14948「发送(AI|ai)声聊[内容]」、
  L14970「查(群员|群友|用户|群聊)[QQ]」、L17110「赞我/点赞」、
  L17124「拍我/截我」、L17138「撤回」、L17152「图转链接」。
- 被动：L17496 视频解析（哔哩哔哩/抖音/小红书/快手）——转发给 lib/video 解析，
  成功先发「标题+作者+封面」再发视频段；图集/实况图发多图；失败仅记日志。

数据：
- 发病文学模板：star.data_path/templates/text/fake_chat_lines.json
- 三角洲密码缓存：BaiXuan/扩展功能/三角洲密码/cache_{日}.json（300s）
- 点赞记录：BaiXuan/扩展功能/点赞记录/{日}.json
- AI 声聊：BaiXuan/扩展功能/AI声聊/{群号}/模型列表.json、正在使用.json

外部 API：
- 三角洲密码 https://www.guoping123.com/hykb_tools/sjz/mrmm/index.php?immgj=0
- EPIC https://uapis.cn/api/v1/game/epic-free
- 搜饰品 https://sdt-api.ok-skins.com/user/skin/v1/auto-completion?q=...
- MC https://uapis.cn/api/v1/game/minecraft/serverstatus?server=...

命名替换：路径前缀「筱筱吖」→「BaiXuan」，MKbot → RO_Play。
"""
from __future__ import annotations

import inspect
import os
import platform as _platform
import random
import re
import time
from typing import Any, Optional

import aiohttp
from astrbot.api import logger
import astrbot.api.message_components as Comp

_HTTP_TIMEOUT = 15
_DELTA_CACHE_REL = "BaiXuan/扩展功能/三角洲密码"
_LIKE_RECORD_REL = "BaiXuan/扩展功能/点赞记录"
_AI_VOICE_REL = "BaiXuan/扩展功能/AI声聊"
_KNOWN_MAPS = ["零号大坝", "长弓溪谷", "巴克什", "航天基地", "潮汐监狱"]


class ToolsModule:
    """工具集：娱乐查询 / 系统状态 / 互动与视频解析。"""

    def __init__(self, star) -> None:
        self.star = star
        self.store = star.store

    # ==================== 网络工具 ====================

    async def _fetch_text(self, url: str, headers: Optional[dict] = None) -> Optional[str]:
        try:
            timeout = aiohttp.ClientTimeout(total=_HTTP_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers or {}) as resp:
                    if resp.status != 200:
                        logger.warning(f"请求失败 HTTP {resp.status}: {url}")
                        return None
                    return await resp.text()
        except Exception as e:  # noqa: BLE001
            logger.error(f"请求异常 {url}: {e}")
            return None

    async def _fetch_json(self, url: str, headers: Optional[dict] = None) -> Any:
        try:
            timeout = aiohttp.ClientTimeout(total=_HTTP_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers or {}) as resp:
                    if resp.status != 200:
                        logger.warning(f"请求失败 HTTP {resp.status}: {url}")
                        return None
                    return await resp.json(content_type=None)
        except Exception as e:  # noqa: BLE001
            logger.error(f"请求异常 {url}: {e}")
            return None

    @staticmethod
    def _fmt_time(ts: Any) -> str:
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts)))
        except (TypeError, ValueError, OSError):
            return "-"

    @staticmethod
    def _fmt_remain(seconds: float) -> str:
        if seconds <= 0:
            return "-"
        sec = int(seconds)
        d, rem = divmod(sec, 86400)
        h, rem = divmod(rem, 3600)
        m, s = divmod(rem, 60)
        return f"{d}天{h}时{m}分{s}秒"

    # ==================== 指令方法（main.py 调用） ====================

    async def fabing(self, event, target: str = "") -> Any:
        """发病文学：/发病文学 对象名（原 L12542）。"""
        try:
            target = (target or "").strip()
            if not target:
                return "请按格式：发病文学[对象名]"
            lines = await self.store.read_json("templates/text/fake_chat_lines.json", []) or []
            if not lines:
                return "发病文学模板为空"
            line = random.choice(lines)
            return str(line).replace("[name]", target)
        except Exception as e:  # noqa: BLE001
            logger.error(f"发病文学失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    async def delta_password(self, event) -> Any:
        """三角洲行动每日密码（原 L12725，300s 缓存）。"""
        try:
            today = time.strftime("%Y-%m-%d")
            cache_rel = f"{_DELTA_CACHE_REL}/cache_{today}.json"
            data: Optional[dict] = None
            used_cache = False
            cache = await self.store.read_json(cache_rel, None)
            if isinstance(cache, dict) and isinstance(cache.get("data"), dict):
                if time.time() - float(cache.get("timestamp", 0)) < 300:
                    data = cache["data"]
                    used_cache = True
            if data is None:
                html = await self._fetch_text(
                    "https://www.guoping123.com/hykb_tools/sjz/mrmm/index.php?immgj=0",
                    {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                )
                if html is None:
                    return "网络请求失败，请稍后重试"
                plain = re.sub(r"<[^>]*>", "", html)
                plain = re.sub(r"\s+", " ", plain).strip()
                pairs: list = []
                seen: list = []
                for m in re.finditer(r"查看位置\s*([^：]+)：(\d{4})", plain):
                    place = m.group(1).strip()
                    if place and place not in seen:
                        seen.append(place)
                        pairs.append({"地名": place, "密码": m.group(2)})
                if not pairs:
                    for m in re.finditer(r"([^：\s]+)：(\d{4})", plain):
                        place = m.group(1).strip()
                        if 2 < len(place) < 20 and not re.search(r"\d", place) and place not in seen:
                            seen.append(place)
                            pairs.append({"地名": place, "密码": m.group(2)})
                if not pairs:
                    for place in _KNOWN_MAPS:
                        m = re.search(re.escape(place) + r"：(\d{4})", plain)
                        if m:
                            pairs.append({"地名": place, "密码": m.group(1)})
                if not pairs:
                    return "未能解析到密码信息，网站可能已更改"
                dm = re.search(r"(\d{1,2}月\d{1,2}日)", plain)
                data = {
                    "密码列表": pairs,
                    "更新日期": dm.group(1) if dm else "未知",
                    "查询时间": self._fmt_time(time.time()),
                }
                await self.store.write_json(cache_rel, {"timestamp": time.time(), "data": data})
            lines = [
                "三角洲行动每日密码",
                "══════════════",
                f"原网站更新：{data.get('更新日期', '未知')}",
                f"查询时间：{data.get('查询时间', '-')}",
                "══════════════",
            ]
            for i, item in enumerate(data.get("密码列表") or [], 1):
                lines.append(f"{i}. {item.get('地名', '')}\n   密码：{item.get('密码', '')}")
            lines.append("══════════════")
            if used_cache:
                lines.append("[数据来自缓存]")
            return "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            logger.error(f"三角洲密码失败: {e}")
            return f"查询出错: {type(e).__name__}: {e}"

    async def epic_games(self, event) -> Any:
        """EPIC 免费游戏（原 L12845）。"""
        try:
            res = await self._fetch_json("https://uapis.cn/api/v1/game/epic-free")
            games = (res or {}).get("data") or [] if isinstance(res, dict) else []
            if not games:
                return "API读取异常！"
            now = time.time()
            nodes = [self.star.sender.build_node("[EPIC免费游戏]", event.get_sender_id(), f"共计【{len(games)}】个免费/限时免费游戏")]
            for g in games:
                free = "✅是" if bool(g.get("is_free_now")) else "❌否"
                remain = self._fmt_remain(int(g.get("free_end_at") or 0) / 1000 - now) if g.get("is_free_now") else "-"
                text = (
                    f"[CQ:image,file={g.get('cover', '')}]《{g.get('title', '')}》\n"
                    f"{g.get('description', '')}\n"
                    "---------------------------\n"
                    f"发行:{g.get('seller', '')}\n"
                    f"原价:{g.get('original_price_desc', '')}\n"
                    "---------------------------\n"
                    f"免费状态:{free}\n"
                    f"开始时间:{self._fmt_time(int(g.get('free_start_at') or 0) / 1000)}\n"
                    f"结束时间:{self._fmt_time(int(g.get('free_end_at') or 0) / 1000)}\n"
                    f"剩余时间:{remain}\n"
                    "---------------------------\n"
                    f"相关链接\n{g.get('link', '')}"
                )
                nodes.append(self.star.sender.build_node("[EPIC免费游戏]", event.get_sender_id(), text))
            await self.star.sender.send_forward(event, nodes)
            return None
        except Exception as e:  # noqa: BLE001
            logger.error(f"EPIC 免费游戏失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    async def search_skin(self, event, keyword: str = "", cs: bool = False) -> Any:
        """搜饰品：/搜饰品 关键词 或 /cs搜饰品 关键词（原 L12564）。"""
        try:
            keyword = (keyword or "").strip()
            if not keyword:
                return "请按格式：搜饰品AK 或 cs搜饰品AK"
            headers = {
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36",
                "Origin": "https://m.steamdt.com",
                "Referer": "https://m.steamdt.com",
            }
            url = f"https://sdt-api.ok-skins.com/user/skin/v1/auto-completion?q={keyword}"
            res = await self._fetch_json(url, headers)
            items = (res or {}).get("data") or [] if isinstance(res, dict) else []
            if not items:
                return f"未搜索到相关饰品：{keyword}"
            limit = min(len(items), 100 if cs else 10)
            if cs:
                nodes = [
                    self.star.sender.build_node(
                        "[搜饰品]", event.get_sender_id(),
                        f"饰品搜索结果：{keyword}\n共匹配：{len(items)} 条（展示前 {limit} 条）",
                    )
                ]
                for i, it in enumerate(items[:limit]):
                    name = it.get("name") or "未知"
                    market = it.get("marketHashName") or "未知"
                    icon = it.get("url") or "-"
                    text = f"【{i + 1}】{name}\n市场名:{market}"
                    if icon and icon != "-":
                        text = f"[CQ:image,file={icon}]\n" + text
                    nodes.append(self.star.sender.build_node("[搜饰品]", event.get_sender_id(), text))
                await self.star.sender.send_forward(event, nodes)
                return None
            lines = [f"饰品搜索结果：{keyword}", "══════════════", f"共匹配：{len(items)} 条（展示前 {limit} 条）"]
            for i, it in enumerate(items[:limit]):
                name = it.get("name") or "未知"
                market = it.get("marketHashName") or "未知"
                icon = it.get("url") or "-"
                lines.append("----------------")
                if icon and icon != "-":
                    lines.append(f"[CQ:image,file={icon}]")
                lines.append(f"【{i + 1}】{name}\n市场名:{market}")
            lines.append("══════════════")
            return "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            logger.error(f"搜饰品失败: {e}")
            return f"搜索失败：{type(e).__name__}: {e}"

    async def mc_server(self, event, address: str = "") -> Any:
        """查MC服务器：/查MC服务器 IP（原 L12670）。"""
        try:
            address = (address or "").strip()
            if not address:
                return "请按格式：查MC服务器[IP/域名]"
            res = await self._fetch_json(
                f"https://uapis.cn/api/v1/game/minecraft/serverstatus?server={address}"
            )
            if not isinstance(res, dict) or res.get("online") is not True:
                return "无查询到该服务器内容！"
            lines = []
            favicon = res.get("favicon_url") or ""
            if favicon and "," in favicon:
                lines.append(f"[CQ:image,file=base64://{favicon.split(',', 1)[1]}]")
            lines.append(f"IP:{res.get('ip', '')}")
            lines.append(f"端口:{res.get('port', '')}")
            lines.append(f"版本号:{res.get('version', '')}")
            lines.append(f"目前人数:{res.get('players', 0)}/{res.get('max_players', 0)}")
            kind, rows = self._parse_mc_players(res.get("online_players"))
            if rows:
                lines.append("──────────────")
                if kind == "players":
                    lines.append(f"在线玩家({len(rows)}):")
                    lines += [f"{i + 1}. {name}" for i, name in enumerate(rows)]
                else:
                    lines.append("玩家状态:")
                    lines += rows
            text = "\n".join(lines)
            if len(rows) > 10:
                nodes = [self.star.sender.build_node("[MC服务器]", event.get_sender_id(), text)]
                await self.star.sender.send_forward(event, nodes)
                return None
            return text
        except Exception as e:  # noqa: BLE001
            logger.error(f"查MC服务器失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    @staticmethod
    def _strip_mc_color(name: str) -> str:
        return re.sub(r"\u00a7[0-9a-fk-or]", "", str(name))

    @staticmethod
    def _is_mc_status_entry(name: str) -> bool:
        n = str(name)
        if n.startswith("00000000-0000-0001"):
            return True
        if re.match(r"^(in-game|queue|priority queue|waiting|playing|lobby)\s*:", n, re.I):
            return True
        return bool(re.search(r":\s*\d+\s*$", n))

    def _parse_mc_players(self, online_players: Any) -> tuple:
        if not isinstance(online_players, list) or not online_players:
            return "none", []
        entries = [p for p in online_players if p and (p.get("name") or p.get("uuid"))]
        if not entries:
            return "none", []
        status_count = sum(1 for p in entries if self._is_mc_status_entry(p.get("name") or ""))
        is_status = status_count == len(entries) or status_count >= len(entries) * 0.75
        rows = [self._strip_mc_color(p.get("name") or "") for p in entries]
        rows = [r for r in rows if r]
        return ("status" if is_status else "players"), rows

    async def img_to_url(self, event) -> Any:
        """图转链接（提取消息与引用消息内的图片/视频 URL，原 L17152）。"""
        try:
            images: list = []
            videos: list = []
            reply_id: Optional[str] = None

            def _looks_link(v: Any) -> bool:
                return isinstance(v, str) and re.match(r"^(https?://|file://|base64://)", v, re.I) is not None

            def _add_unique(arr: list, value: Any) -> None:
                s = str(value or "").strip()
                if s and s not in arr:
                    arr.append(s)

            for seg in getattr(event, "message", None) or []:
                name = type(seg).__name__.lower()
                if name == "image":
                    for v in (getattr(seg, "url", ""), getattr(seg, "file", "")):
                        if _looks_link(v):
                            _add_unique(images, v)
                elif name == "video":
                    for v in (getattr(seg, "url", ""), getattr(seg, "file", "")):
                        if _looks_link(v):
                            _add_unique(videos, v)
                elif name == "reply":
                    reply_id = str(getattr(seg, "id", "") or "")
            # CQ 码兜底
            for m in re.finditer(r"\[CQ:image,file=([^,\]]+)", event.message_str or ""):
                if _looks_link(m.group(1)):
                    _add_unique(images, m.group(1))
            for m in re.finditer(r"\[CQ:video,file=([^,\]]+)", event.message_str or ""):
                if _looks_link(m.group(1)):
                    _add_unique(videos, m.group(1))
            # 引用消息
            if reply_id:
                try:
                    r = await self.star.api.call_result("get_msg", message_id=reply_id)
                    data = r.get("data") if isinstance(r, dict) else r
                    for seg in (data or {}).get("message") or [] if isinstance(data, dict) else []:
                        if not isinstance(seg, dict):
                            continue
                        if seg.get("type") == "image":
                            for v in (seg.get("data", {}).get("url"), seg.get("data", {}).get("file")):
                                if _looks_link(v):
                                    _add_unique(images, v)
                        elif seg.get("type") == "video":
                            for v in (seg.get("data", {}).get("url"), seg.get("data", {}).get("file")):
                                if _looks_link(v):
                                    _add_unique(videos, v)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"读取引用消息失败: {e}")
            if not images and not videos:
                return "未检测到图片或视频链接～"
            nodes = [self.star.sender.build_node("[图转链接]", event.get_sender_id(), "图转链接结果:")]
            for i, u in enumerate(images, 1):
                nodes.append(self.star.sender.build_node(f"[第{i}张图片]", event.get_sender_id(),
                                                         f"[CQ:image,file={u}]══════════════\n{u}"))
            for i, u in enumerate(videos, 1):
                nodes.append(self.star.sender.build_node(f"[第{i}个视频]", event.get_sender_id(), f"视频链接:\n{u}"))
            await self.star.sender.send_forward(event, nodes)
            return None
        except Exception as e:  # noqa: BLE001
            logger.error(f"图转链接失败: {e}")
            return f"图转链接处理失败: {type(e).__name__}: {e}"

    async def status(self, event) -> Any:
        """运行状态（原 L13772，渲染 status.html，失败回退文本）。"""
        try:
            if not await self.star.perm.check_admin(event):
                return None
            login = await self.star.api.get_login_info()
            bot_qq = str((login or {}).get("user_id") or event.get_sender_id())
            bot_name = str((login or {}).get("nickname") or "未知")
            try:
                friends = await self.star.api.get_friend_list()
                friend_count = len(friends or [])
            except Exception as e:  # noqa: BLE001
                logger.error(f"获取好友列表失败: {e}")
                friend_count = 0
            try:
                groups = await self.star.api.get_group_list()
                group_count = len(groups or [])
            except Exception as e:  # noqa: BLE001
                logger.error(f"获取群聊列表失败: {e}")
                group_count = 0
            cpu_pct, mem_pct, cpu_count, total_gb, disk_used_gb, disk_total_gb, disk_free_gb, disk_pct = self._system_metrics()
            process_data = self._process_data()
            data = {
                "QQ": bot_qq,
                "name": bot_name,
                "type": _platform.system() or "Unknown",
                "arch": _platform.machine() or "Unknown",
                "groupCount": group_count,
                "friendCount": friend_count,
                "cpuUsagePercent": cpu_pct,
                "memoryUsagePercent": mem_pct,
                "cpuCount": cpu_count,
                "totalMemoryGB": total_gb,
                "diskUsedGB": disk_used_gb,
                "diskTotalGB": disk_total_gb,
                "diskFreeGB": disk_free_gb,
                "diskUsagePercent": disk_pct,
                "process_data": process_data,
            }
            try:
                img_url = await self.star.render.render_html("status.html", data)
                return event.image_result(img_url)
            except Exception as e:  # noqa: BLE001
                logger.error(f"运行状态渲染失败，回退文本: {e}")
                lines = [
                    "══════════════",
                    "【运行状态】",
                    "══════════════",
                    "[账号信息]",
                    f" - 昵称: {bot_name}",
                    f" - QQ: {bot_qq}",
                    f" - 群聊: {group_count}",
                    f" - 好友: {friend_count}",
                    "[系统信息]",
                    f" - 系统: {_platform.system() or 'Unknown'}",
                    f" - 架构: {_platform.machine() or 'Unknown'}",
                    f" - CPU核心: {cpu_count}",
                    f" - CPU使用: {cpu_pct}%",
                    f" - 内存: {mem_pct}%",
                    f" - 磁盘: {disk_pct}%",
                    "══════════════",
                ]
                return "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            logger.error(f"运行状态失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    def _system_metrics(self) -> tuple:
        """psutil 可用时取真实指标，否则返回 0 占位。"""
        cpu_pct = 0.0
        mem_pct = 0.0
        cpu_count = os.cpu_count() or 1
        total_gb = 0.0
        disk_used_gb = disk_total_gb = disk_free_gb = 0.0
        disk_pct = 0.0
        try:
            import psutil

            cpu_pct = round(float(psutil.cpu_percent(interval=0.5) or 0), 2)
            vm = psutil.virtual_memory()
            mem_pct = round(float(vm.percent or 0), 2)
            total_gb = round(float(vm.total) / 1024 ** 3, 2)
            du = psutil.disk_usage(os.getcwd())
            disk_total_gb = round(float(du.total) / 1024 ** 3, 2)
            disk_used_gb = round(float(du.used) / 1024 ** 3, 2)
            disk_free_gb = round(float(du.free) / 1024 ** 3, 2)
            disk_pct = round(float(du.percent or 0), 2)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"psutil 不可用，使用占位指标: {e}")
        return cpu_pct, mem_pct, cpu_count, total_gb, disk_used_gb, disk_total_gb, disk_free_gb, disk_pct

    def _process_data(self) -> list:
        """psutil 不可用时返回空列表（status.html 兜底）。"""
        try:
            import psutil

            rows = []
            for proc in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
                try:
                    pinfo = proc.info
                    mem = (pinfo.get("memory_info") or {}).rss or 0
                    rows.append({
                        "pid": str(pinfo.get("pid") or ""),
                        "name": str(pinfo.get("name") or "Unknown"),
                        "memory": mem,
                        "memoryMB": f"{mem / 1024 / 1024:.2f}",
                        "cpuPercent": f"{float(pinfo.get('cpu_percent') or 0):.1f}",
                    })
                except Exception:  # noqa: BLE001
                    continue
            rows.sort(key=lambda r: r["memory"], reverse=True)
            return rows[:20]
        except Exception as e:  # noqa: BLE001
            logger.warning(f"进程数据不可用: {e}")
            return []

    async def like_me(self, event) -> Any:
        """赞我：/赞我（原 L17110，调 send_like）。"""
        try:
            uid = str(event.get_sender_id())
            if await self.star.global_event_enabled("自动点赞"):
                today = time.strftime("%Y-%m-%d")
                rel = f"{_LIKE_RECORD_REL}/{today}.json"
                if await self.store.read_key(rel, uid, "未") == "未":
                    await self.store.write_key(rel, uid, "已")
                    await self.star.api.call("send_like", user_id=uid, times=20)
            else:
                await self.star.api.call("send_like", user_id=uid, times=20)
            return None
        except Exception as e:  # noqa: BLE001
            logger.error(f"赞我失败: {e}")
            return None

    async def poke_me(self, event) -> Any:
        """拍我：/拍我（原 L17124，调 friend_poke）。"""
        try:
            uid = str(event.get_sender_id())
            await self.star.api.call("friend_poke", user_id=uid)
            return None
        except Exception as e:  # noqa: BLE001
            logger.error(f"拍我失败: {e}")
            return None

    async def restart(self, event) -> Any:
        """重启服务：/重启服务（主人，原 L14860）。"""
        try:
            if not await self.star.perm.check_owner(event):
                return "你不是主人哦～"
            await self.star.api.call("set_restart")
            return "已发送重启请求～请等待！\n预计10秒内会回复，如没有则需手动！"
        except Exception as e:  # noqa: BLE001
            logger.error(f"重启服务失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    # ==================== 被动视频解析 ====================

    async def video_scan(self, event) -> None:
        """被动：视频/图集解析（原 L17496，调 lib.video）。"""
        try:
            try:
                from lib.video import match_platform, parse
            except ImportError as e:  # noqa: BLE001
                logger.warning(f"lib.video 未就绪，跳过解析: {e}")
                return
            text = (event.message_str or "").strip()
            if not text:
                return
            if not callable(match_platform):
                return
            link = match_platform(text)
            if not link:
                return
            info = parse(link)
            if inspect.isawaitable(info):
                info = await info
            if not info:
                logger.warning(f"视频解析失败: {link}")
                return
            title = info.get("标题") or info.get("title") or info.get("视频标题") or ""
            author = info.get("作者") or info.get("author") or (info.get("UP主信息") or {}).get("UP主名称") or ""
            cover = info.get("封面") or info.get("cover") or info.get("视频封面") or ""
            desc = info.get("描述") or info.get("description") or info.get("视频描述") or ""
            parts = []
            if cover:
                parts.append(f"[CQ:image,file={cover}]")
            if title:
                parts.append(f"标题:{title}")
            if desc:
                parts.append(f"简介:{desc}")
            if author:
                parts.append(f"作者:{author}")
            if parts:
                await self.star.sender.send_reply(event, "\n".join(parts))
            # 图集 / 实况图：多图
            album = info.get("images") or info.get("图片") or info.get("图集") or []
            if isinstance(album, list) and album:
                for u in album[:9]:
                    if str(u).startswith(("http://", "https://")):
                        await self.star.sender.send_reply(event, f"[CQ:image,file={u}]")
                return
            # 视频段
            video_url = info.get("视频链接") or info.get("url") or info.get("video_url") or ""
            if video_url and str(video_url).startswith(("http://", "https://")):
                await event.send(event.chain_result([Comp.Video.fromURL(str(video_url))]))
        except Exception as e:  # noqa: BLE001
            logger.error(f"视频解析异常: {e}")

    # ==================== 无前缀 legacy ====================

    async def legacy(self, event, message: str) -> Any:
        """正则匹配无前缀工具指令（原 L12542~L17152 等）。"""
        try:
            m = re.match(r"^发病文学([\s\S]+)$", message)
            if m:
                return await self.fabing(event, m.group(1))
            m = re.match(r"^(三角洲|sjz)(密码|每日密码)$", message)
            if m:
                return await self.delta_password(event)
            m = re.match(r"^(epic|Epic|EPIC)免费游戏$", message)
            if m:
                return await self.epic_games(event)
            m = re.match(r"^(?:[cC][sS])?搜饰品([\s\S]+)$", message)
            if m:
                return await self.search_skin(event, m.group(1), cs=m.group(0).startswith(("cs", "CS", "cS", "Cs")))
            m = re.match(r"^查(MC|mc|我的世界)服务器([\s\S]*)$", message)
            if m:
                return await self.mc_server(event, m.group(2).strip())
            m = re.match(r"^查(群员|群友|用户|群聊)([0-9]+)$", message)
            if m:
                return await self._query_info(event, m.group(1), m.group(2))
            if "撤回" in message:
                return await self._withdraw(event)
            if message == "运行状态":
                return await self.status(event)
            if re.match(r"^(图|)转链接$", message):
                return await self.img_to_url(event)
            if message in ("赞我", "点赞"):
                return await self.like_me(event)
            if message in ("拍我", "截我"):
                return await self.poke_me(event)
            if message == "获取声聊角色列表":
                return await self._ai_characters(event)
            m = re.match(r"^发送(.*?)(AI|ai)声聊([\s\S]*)$", message)
            if m:
                return await self._send_ai_voice(event, m.group(1), m.group(3))
        except Exception as e:  # noqa: BLE001
            logger.error(f"工具 legacy 异常: {e}")
        return None

    async def _query_info(self, event, kind: str, target: str) -> Any:
        """查群员/群友/用户/群聊（原 L14970）。"""
        gid = str(event.get_group_id() or "")
        if not gid:
            return None
        sex_map = {"unknown": "未知", "female": "女", "male": "男"}
        if kind == "群聊":
            info = await self.star.api.call_result("get_group_detail_info", group_id=target)
            if not info:
                return "查无此群～！"
            intro = str((info.get("richFingerMemo") or "-"))
            lines = [
                f"[CQ:image,file=http://p.qlogo.cn/gh/{target}/{target}/0]",
                "══════════════",
                f"[群号]:{target}",
                f"[群名]:{info.get('group_name', '-')}",
                f"[群主]:{info.get('ownerUin') if info.get('ownerUin') and info.get('ownerUin') != '0' else '-'}",
                f"[人数]:{info.get('member_count', 0)}/{info.get('max_member_count', 0)}",
                f"[创建]:{self._fmt_time(info.get('groupCreateTime') or time.time())}",
                "---------------",
                intro,
                "══════════════",
            ]
            return "\n".join(lines)
        if kind == "用户":
            info = await self.star.api.call_result("get_stranger_info", user_id=target)
            if not info:
                return "查无此人～！"
            lines = [
                f"[CQ:image,file=https://q4.qlogo.cn/g?b=qq&nk={target}&s=5]",
                "══════════════",
                f"[QQ]:{target}",
                f"[Qid]:{info.get('qid', '-')}",
                f"[昵称]:{info.get('nick', '-')}",
                f"[性别]:{sex_map.get(info.get('sex'), '未知')}",
                f"[用户等级]:{info.get('qqLevel', '-')}",
                f"[会员等级]:{info.get('vip_level', '-')}",
                f"[注册时间]:{self._fmt_time(info.get('reg_time')) if info.get('reg_time') else '-'}",
                "--------",
                f"[个性签名]:{info.get('longNick', '-')}",
                "══════════════",
            ]
            return "\n".join(lines)
        info = await self.star.api.get_group_member_info(gid, target)
        if not info:
            return "查无此人～！"
        role_map = {"owner": "群主", "admin": "管理员", "member": "普通成员", "unknown": "未知"}
        age = f"{info.get('age')}岁" if info.get("age") else "-"
        level = f"{info.get('qq_level')}级" if info.get("qq_level") else "-"
        card = info.get("card") or info.get("nickname") or "-"
        title = info.get("title") or "-"
        lines = [
            f"[CQ:image,file=https://q4.qlogo.cn/g?b=qq&nk={target}&s=5]",
            "══════════════",
            f"[目标]:{info.get('user_id', target)}",
            f"[昵称]:{info.get('nickname', '-')}",
            f"[性别]:{sex_map.get(info.get('sex'), '未知')}",
            f"[年龄]:{age}",
            f"[等级]:{level}",
            "══════════════",
            f"[群昵称]:{card}",
            f"[群身份]:{role_map.get(info.get('role'), '未知')}",
            f"[群头衔]:{title}",
            f"[群等级]:{info.get('level', '-')}",
            "══════════════",
            f"[入群时间]:{self._fmt_time(info.get('join_time')) if info.get('join_time') else '-'}",
            f"[最近发言]:{self._fmt_time(info.get('last_sent_time')) if info.get('last_sent_time') else '-'}",
            "══════════════",
        ]
        return "\n".join(lines)

    async def _withdraw(self, event) -> Any:
        """撤回引用消息（原 L17138）。"""
        try:
            if not await self.star.perm.check_admin(event):
                return None
            reply_id = ""
            for seg in getattr(event, "message", None) or []:
                if type(seg).__name__.lower() == "reply":
                    reply_id = str(getattr(seg, "id", "") or "")
                    break
            if not reply_id:
                return None
            ok = await self.star.api.call("delete_msg", message_id=reply_id)
            if not ok:
                logger.warning(f"撤回消息失败: {reply_id}")
            return None
        except Exception as e:  # noqa: BLE001
            logger.error(f"撤回失败: {e}")
            return None

    async def _ai_characters(self, event) -> Any:
        """获取声聊角色列表（原 L14915）。"""
        try:
            gid = str(event.get_group_id() or "")
            if not gid:
                return None
            res = await self.star.api.call_result("get_ai_characters", group_id=gid)
            items = res or []
            if not items:
                return "获取失败！"
            lines = []
            for i, group in enumerate(items):
                chars = group.get("characters") or []
                names = [c.get("character_name", "") for c in chars if isinstance(c, dict)]
                if i == 0:
                    lines.append(f"【{group.get('type', '')}】")
                else:
                    lines.append(f"\n【{group.get('type', '')}】")
                if names:
                    lines.append("、".join(names))
                for c in chars if isinstance(c, dict) else []:
                    if c.get("character_name"):
                        await self.store.write_key(
                            f"{_AI_VOICE_REL}/{gid}/模型列表.json",
                            str(c.get("character_name")), str(c.get("character_id") or ""),
                        )
                lines.append("")
            return "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            logger.error(f"获取声聊角色列表失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    async def _send_ai_voice(self, event, model_arg: str, content_arg: str) -> Any:
        """发送 AI 声聊（原 L14948）。"""
        try:
            gid = str(event.get_group_id() or "")
            if not gid:
                return None
            model = str(model_arg or "").strip()
            if not model:
                model = await self.store.read_key(f"{_AI_VOICE_REL}/{gid}/正在使用.json", "正在使用", "lucy-voice-houge")
            else:
                model = await self.store.read_key(f"{_AI_VOICE_REL}/{gid}/模型列表.json", model, "lucy-voice-houge")
                await self.store.write_key(f"{_AI_VOICE_REL}/{gid}/正在使用.json", "正在使用", model)
            content = (content_arg or "").strip() or "谁教你这么发指令的，回答我！"
            ok = await self.star.api.call(
                "send_group_ai_record", character=str(model), group_id=gid, text=content
            )
            return None if ok else "AI 声聊发送失败～"
        except Exception as e:  # noqa: BLE001
            logger.error(f"发送 AI 声聊失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"
