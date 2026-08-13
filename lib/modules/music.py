from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import quote

import aiohttp
import astrbot.api.message_components as Comp
from astrbot.api import logger

from lib.cqcode import cq_music, cq_record

API_URLS: dict[str, str] = {
    "汽水": "https://api-v2.cenguigui.cn/api/qishui/?msg=",
    "QQ": "https://a.aa.cab/qq.music?msg=",
    "酷我": "https://oiapi.net/api/Kuwo?msg=",
    "网易云": "https://oiapi.net/api/Music_163?name=",
}
MUSIC_ROOT = "BaiXuan/音乐系统"

class MusicModule:

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

    async def _fetch(self, url: str, timeout: int = 15) -> Any:

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    return await resp.json()
        except Exception as e:
            logger.warning(f"音乐接口访问失败 {url}: {e}")
            return None

    async def _search_api(self, 音源: str, 歌名: str, n: int | None = None) -> Any:
        base = API_URLS.get(音源)
        if not base:
            return None
        url = base + quote(歌名)
        if 音源 == "汽水":
            url += "&type=json"
            if n is not None:
                url += f"&n={n}"
        elif 音源 == "QQ":
            url += "&num=10"
            if n is not None:
                url += f"&n={n}"
        elif 音源 == "酷我":
            url += "&limit=20"
            if n is not None:
                url += f"&n={n}"
        elif 音源 == "网易云":
            url += "&limit=20"
            if n is not None:
                url += f"&n={n}"
        return await self._fetch(url)

    @staticmethod
    def _extract(item: Any, 音源: str) -> dict:

        item = item or {}
        if 音源 == "汽水":
            return {
                "歌名": str(item.get("title", "") or ""),
                "歌手": str(item.get("singer", "") or ""),
                "封面": str(item.get("cover", "") or ""),
                "链接": str(item.get("music", "") or ""),
                "类型": "yk",
            }
        if 音源 == "酷我":
            return {
                "歌名": str(item.get("song", "") or ""),
                "歌手": str(item.get("singer", "") or ""),
                "封面": str(item.get("picture", "") or ""),
                "链接": str(item.get("url", "") or ""),
                "类型": "kuwo",
            }
        if 音源 == "QQ":
            return {
                "歌名": str(item.get("song", "") or ""),
                "歌手": str(item.get("singer", "") or ""),
                "封面": str(item.get("cover", "") or ""),
                "链接": str(item.get("music", "") or ""),
                "类型": "qq",
            }
        if 音源 == "网易云":
            singers = item.get("singers") or []
            歌手 = ""
            if isinstance(singers, list) and singers:
                歌手 = str(singers[0].get("name", "") or "")
            return {
                "歌名": str(item.get("name", "") or ""),
                "歌手": 歌手,
                "封面": str(item.get("picurl", "") or ""),
                "链接": str(item.get("url", "") or ""),
                "类型": "163",
            }
        return {"歌名": "", "歌手": "", "封面": "", "链接": "", "类型": "163"}

    async def _source_of(self, event: Any, source: str = "") -> str:

        if source and source in API_URLS:
            return source
        uid = str(event.get_sender_id())
        try:
            saved = await self.star.store.read_key(f"{MUSIC_ROOT}/使用音源.json", uid, "")
            if saved and saved in API_URLS:
                return saved
        except Exception as e:
            logger.warning(f"读取音源记录失败: {e}")
        default = str(self.star.config.get("music_source", "汽水") or "汽水")
        return default if default in API_URLS else "汽水"

    async def _save_source(self, event: Any, source: str) -> None:
        try:
            await self.star.store.write_key(f"{MUSIC_ROOT}/使用音源.json", str(event.get_sender_id()), source)
        except Exception as e:
            logger.warning(f"保存音源失败: {e}")

    async def _music_reply(self, event: Any, info: dict, mode: str) -> Any:

        url = info.get("链接", "")
        if len(url) < 10:
            return "访问失败：接口返回异常，请联系开发者修复"
        歌名, 歌手, 封面, 类型 = info.get("歌名", ""), info.get("歌手", ""), info.get("封面", ""), info.get("类型", "163")
        if mode == "语音":
            return cq_record(url)
        if mode == "链接":
            return f"[CQ:image,url={封面}]\n歌名:{歌名}\n歌手:{歌手}\n音频链接:\n{url}"

        if self.star.config.get("music_card_api", False):
            try:
                params = (
                    f"?title={quote(歌名)}&singer={quote(歌手)}&pingtai={类型}&audio={quote(url)}"
                    f"&img={quote(封面)}&wx={quote('你也想听歌嘛？')}&link={quote(url)}"
                )
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        "https://api.s01s.cn/API/music_ark/" + params,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        text = await resp.text()
                data = (
                    text.replace("[", "&#91;")
                    .replace("]", "&#93;")
                    .replace(",", "&#44;")
                )
                return f"[CQ:json,data={data}]"
            except Exception as e:
                logger.warning(f"音乐卡片接口失败，回退 Music 段: {e}")
        try:
            return Comp.Music(
                kind="custom",
                url=url,
                audio=url,
                title=歌名,
                content=歌手,
                image=封面,
            )
        except Exception:
            return cq_music(url, url, 歌名, 歌手, 封面)

    async def search(self, event: Any, name: str = "", source: str = ""):

        try:
            if not await self._authorized(event):
                return None
            name = (name or "").strip()
            if not name:
                return "你是在点歌嘛？"
            音源 = await self._source_of(event, source)
            if source and source in API_URLS:
                await self._save_source(event, source)
            api = await self._search_api(音源, name)
            if not api:
                return f"访问失败：{音源}接口不可达/超时，请联系开发者修复"
            items = api.get("data") or []
            count = len(items)
            if count == 0:
                return "接口取值异常！"
            uid = str(event.get_sender_id())
            await self.star.store.write_key(f"{MUSIC_ROOT}/选歌范围.json", uid, count)
            await self.star.store.write_key(f"{MUSIC_ROOT}/点歌名字.json", uid, name)
            lines = [f"══════════════\n当前为【{音源}】点歌，共{count}首\n══════════════"]
            歌单: list[dict] = []
            for i, item in enumerate(items):
                歌名 = self._extract(item, 音源)["歌名"]
                歌手 = self._extract(item, 音源)["歌手"]
                lines.append(f"{i + 1}.{歌名}---{歌手}")
                歌单.append({"歌名": 歌名, "歌手": 歌手})
            lines.append("══════════════")
            await self.star.store.write_json(f"{MUSIC_ROOT}/临时歌单/{uid}.json", {"音源": 音源, "data": 歌单})
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"点歌异常: {e}")
            return "点歌处理异常，请稍后再试"

    async def pick(self, event: Any, index: str = "", mode: str = "卡片"):

        try:
            if not await self._authorized(event):
                return None
            index = (index or "").strip()
            if not index.isdigit():
                return "请提供选歌序号哦～"
            mub = int(index)
            if mub <= 0:
                return "可选范围异常！"
            uid = str(event.get_sender_id())
            最大 = int(await self.star.store.read_key(f"{MUSIC_ROOT}/选歌范围.json", uid, 0) or 0)
            if mub > 最大:
                return f"可选范围异常，当前你可选范围为【{最大}】"
            歌名 = str(await self.star.store.read_key(f"{MUSIC_ROOT}/点歌名字.json", uid, "九尾狐") or "九尾狐")
            音源 = await self._source_of(event)
            api = await self._search_api(音源, 歌名, mub)
            if not api:
                return f"访问失败：{音源}接口不可达/超时，请联系开发者修复"
            data = api.get("data") if isinstance(api, dict) else None
            item = data[mub - 1] if isinstance(data, list) and len(data) >= mub else data
            if isinstance(data, list) and mub > len(data):
                return f"访问失败：{音源}接口返回异常，请联系开发者修复"
            info = self._extract(item if isinstance(item, dict) else (data if isinstance(data, dict) else {}), 音源)
            return await self._music_reply(event, info, mode)
        except Exception as e:
            logger.error(f"选歌异常: {e}")
            return "选歌处理异常，请稍后再试"

    async def favorite(self, event: Any, index: str = ""):

        try:
            if not await self._authorized(event):
                return None
            index = (index or "").strip()
            if not index.isdigit():
                return "请提供序号哦～"
            选择序号 = int(index)
            uid = str(event.get_sender_id())
            临时 = await self.star.store.read_json(f"{MUSIC_ROOT}/临时歌单/{uid}.json", None)
            if not isinstance(临时, dict) or not isinstance(临时.get("data"), list):
                return "无数据：请先点歌再操作！"
            数量 = len(临时["data"])
            if 选择序号 <= 0 or 选择序号 > 数量:
                return "选取范围无效哦！"
            搜索 = str(await self.star.store.read_key(f"{MUSIC_ROOT}/点歌名字.json", uid, "") or "")
            item = 临时["data"][选择序号 - 1]
            收藏 = await self.star.store.read_json(f"{MUSIC_ROOT}/音乐收藏/{uid}.json", []) or []
            if not isinstance(收藏, list):
                收藏 = []
            收藏.append({
                "搜索": 搜索,
                "序号": 选择序号,
                "音源": str(临时.get("音源", "") or ""),
                "歌名": str(item.get("歌名", "") or ""),
                "歌手": str(item.get("歌手", "") or ""),
            })
            await self.star.store.write_json(f"{MUSIC_ROOT}/音乐收藏/{uid}.json", 收藏)
            return f"已收藏改歌曲:\n{item.get('歌名', '')}----{item.get('歌手', '')}"
        except Exception as e:
            logger.error(f"收藏音乐异常: {e}")
            return "收藏音乐处理异常，请稍后再试"

    async def unfavorite(self, event: Any, index: str = ""):

        try:
            if not await self._authorized(event):
                return None
            uid = str(event.get_sender_id())
            收藏 = await self.star.store.read_json(f"{MUSIC_ROOT}/音乐收藏/{uid}.json", []) or []
            if not isinstance(收藏, list):
                收藏 = []
            数量 = len(收藏)
            if 数量 == 0:
                return "歌单文件数量为0"
            m = re.match(r"^(\d+)(?:[-_\.](\d+))?$", (index or "").strip())
            if not m:
                return "范围无效哟～"
            起始 = int(m.group(1))
            结束 = int(m.group(2)) if m.group(2) else 起始
            if 起始 <= 0 or 起始 > 数量 or 结束 < 起始 or 结束 > 数量:
                return f"范围无效哟～|{数量}"
            范围 = 结束 - 起始 + 1
            删除 = 收藏[起始 - 1:结束]
            del 收藏[起始 - 1:结束]
            await self.star.store.write_json(f"{MUSIC_ROOT}/音乐收藏/{uid}.json", 收藏)
            lines = [f"已删除{起始}|{结束}", "══════════════"]
            for i, item in enumerate(删除):
                lines.append(f"{起始 + i}.[{item.get('音源', '')}]{item.get('歌名', '')} --- {item.get('歌手', '')}")
            lines.append("══════════════")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"取消收藏异常: {e}")
            return "取消收藏处理异常，请稍后再试"

    async def fav_list(self, event: Any):

        try:
            if not await self._authorized(event):
                return None
            uid = str(event.get_sender_id())
            收藏 = await self.star.store.read_json(f"{MUSIC_ROOT}/音乐收藏/{uid}.json", []) or []
            if not isinstance(收藏, list) or len(收藏) == 0:
                return "歌单文件数量为0"
            lines = [f"共计【{len(收藏)}】首收藏歌曲", "══════════════"]
            for i, item in enumerate(收藏):
                lines.append(f"{i + 1}.[{item.get('音源', '')}]{item.get('歌名', '')} --- {item.get('歌手', '')}")
            lines.append("══════════════")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"我的收藏异常: {e}")
            return "我的收藏处理异常，请稍后再试"

    async def clear_fav(self, event: Any):

        try:
            if not await self._authorized(event):
                return None
            uid = str(event.get_sender_id())
            await self.star.store.write_json(f"{MUSIC_ROOT}/音乐收藏/{uid}.json", [])
            return "好叭，这就把你的歌单给清空空！"
        except Exception as e:
            logger.error(f"清空个人收藏异常: {e}")
            return "清空个人收藏处理异常，请稍后再试"

    async def play_fav(self, event: Any, index: str = ""):

        try:
            if not await self._authorized(event):
                return None
            index = (index or "").strip()
            m = re.match(r"^(卡片|链接|语音)?\s*(\d+)$", index)
            if not m:
                return "请提供收藏序号哦～"
            方式 = m.group(1) or "卡片"
            序号 = int(m.group(2))
            uid = str(event.get_sender_id())
            收藏 = await self.star.store.read_json(f"{MUSIC_ROOT}/音乐收藏/{uid}.json", []) or []
            if not isinstance(收藏, list) or len(收藏) == 0:
                return "歌单文件数量为0"
            if 序号 <= 0 or 序号 > len(收藏):
                return f"可选范围异常！请仔细查看收藏数量！\n当前可选范围【{len(收藏)}】"
            entry = 收藏[序号 - 1]
            搜索 = str(entry.get("搜索", "") or "")
            mub = int(entry.get("序号", 1) or 1)
            音源 = str(entry.get("音源", "") or "汽水")
            if 音源 not in API_URLS:
                音源 = "汽水"
            api = await self._search_api(音源, 搜索, mub)
            if not api:
                return f"访问失败：{音源}接口不可达/超时，请联系开发者修复"
            data = api.get("data") if isinstance(api, dict) else None
            item = data[mub - 1] if isinstance(data, list) and len(data) >= mub else data
            if isinstance(data, list) and mub > len(data):
                return f"访问失败：{音源}接口返回异常，请联系开发者修复"
            info = self._extract(item if isinstance(item, dict) else (data if isinstance(data, dict) else {}), 音源)
            return await self._music_reply(event, info, 方式)
        except Exception as e:
            logger.error(f"播放收藏异常: {e}")
            return "播放收藏处理异常，请稍后再试"

    async def legacy(self, event: Any, message: str) -> Any:

        try:
            if message in ("音乐功能", "音乐系统", "音乐菜单"):
                if not await self._authorized(event):
                    return None
                return (
                    "RO - 音乐系统\n"
                    "点歌使用例子↓\n══════════════\n"
                    " - 点歌小团圆\n - QQ点歌小团圆\n - 汽水点歌小团圆\n"
                    " - 酷我点歌小团圆\n - 网易云点歌小团圆\n══════════════\n"
                    "选歌使用例子↓\n══════════════\n"
                    " - 选歌1\n - 卡片选歌1\n - 语音选歌1\n - 链接选歌1\n══════════════\n"
                    "收藏操作\n══════════════\n"
                    " - 个人歌单\n - 收藏歌曲1\n - 取消收藏2\n - 播放收藏6\n"
                    " - 清空个人收藏歌曲\n══════════════"
                )
            m = re.match(r"^(酷我|汽水|网易云|QQ|)点歌([\s\S]*)$", message)
            if m:
                source = m.group(1)
                name = m.group(2).strip()
                if not name:
                    return "你是在点歌嘛？"
                return await self.search(event, name, source)
            m = re.match(r"^(链接|卡片|语音|)选歌([0-9]+)$", message)
            if m:
                mode = m.group(1) or "卡片"
                return await self.pick(event, m.group(2), mode)
            if message in ("我的收藏", "个人歌单"):
                return await self.fav_list(event)
            m = re.match(r"^(收藏音乐|收藏歌曲|取消收藏)([0-9]+)(?:[-_\.]([0-9]+))?$", message)
            if m:
                if m.group(1) in ("收藏音乐", "收藏歌曲"):
                    return await self.favorite(event, m.group(2))
                end = m.group(3) or m.group(2)
                return await self.unfavorite(event, f"{m.group(2)}{'-' if m.group(3) else ''}{end}" if m.group(3) else m.group(2))
            if message in ("清空个人收藏音乐", "清空个人收藏歌曲"):
                return await self.clear_fav(event)
            m = re.match(r"^(链接|卡片|语音|)播放收藏([0-9]+)$", message)
            if m:
                return await self.play_fav(event, f"{m.group(1) if m.group(1) else '卡片'} {m.group(2)}")
            return None
        except Exception as e:
            logger.error(f"音乐 legacy 异常: {e}")
            return None
