from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Any, Optional

import aiohttp
from astrbot.api import logger
import astrbot.api.message_components as Comp

_PM_STORAGE_REL = "BaiXuan/扩展功能/入群私聊/分群"
_PM_STATUS_REL = "BaiXuan/扩展功能/入群私聊/收录状态.txt"
_PM_PROB_REL = "BaiXuan/扩展功能/入群私聊/概率.json"
_RECORD_WINDOW_SEC = 300
_MAX_FORWARD_DEPTH = 3

class JoinPmModule:

    def __init__(self, star) -> None:
        self.star = star
        self.store = star.store

    async def start_record(self, event, gid: str = "") -> Any:

        try:
            if not await self.star.perm.check_owner(event):
                return "你不是主人哦～"
            gid = (gid or "").strip()
            if not gid:
                return "群号参数为空！！！"
            await self.store.write_json(f"{_PM_STORAGE_REL}/{gid}.json", [])
            await self.store.write_json(_PM_STATUS_REL, {"状态": "开始", "群号": gid})
            uid = str(event.get_sender_id())

            asyncio.create_task(self._record_window(gid, uid))
            return f"已开启收录，请在300秒内发送内容进行收录！当前收录群号为「{gid}」"
        except Exception as e:
            logger.error(f"开始记录失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    async def _record_window(self, gid: str, uid: str) -> None:

        try:
            for _ in range(_RECORD_WINDOW_SEC):
                await asyncio.sleep(1)
                status = await self.store.read_key(_PM_STATUS_REL, "状态", "结束")
                if str(status) != "开始":
                    return
            await self.store.write_json(_PM_STATUS_REL, {"状态": "结束", "群号": gid})
            await self.star.sender.send_to_private(uid, "执行超时，已强制结束！")
        except Exception as e:
            logger.error(f"收录窗口任务异常: {e}")

    async def stop_record(self, event) -> Any:

        try:
            if not await self.star.perm.check_owner(event):
                return "你不是主人哦～"
            cur = await self.store.read_key(_PM_STATUS_REL, "状态", "结束")
            if str(cur) != "开始":
                return f"目前已是「{cur}」状态啦～"
            await self.store.write_json(_PM_STATUS_REL, {"状态": "结束", "群号": ""})
            return "已结束本次收录！"
        except Exception as e:
            logger.error(f"结束记录失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    async def view_record(self, event, gid: str = "") -> Any:

        try:
            if not await self.star.perm.check_owner(event):
                return "你不是主人哦～"
            gid = (gid or "").strip()
            if not gid:
                return "群号参数为空！！！"
            entries = await self.store.read_json(f"{_PM_STORAGE_REL}/{gid}.json", []) or []
            if not isinstance(entries, list) or not entries:
                return "该群尚未收录任何入群私聊内容。"
            uid = str(event.get_sender_id())
            await self._replay_entries(uid, gid, entries)
            return f"已展示「{gid}」的全部入群私聊记录。"
        except Exception as e:
            logger.error(f"查看记录内容失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    async def set_probability(self, event, args: str = "") -> Any:

        try:
            if not await self.star.perm.check_owner(event):
                return "你不是主人哦～"
            m = re.match(r"^(\d+)\s+(\d+)%?$", (args or "").strip())
            if not m:
                return "格式：设置入群私聊概率 群号 概率%（0-100）"
            gid, percent = m.group(1), int(m.group(2))
            if percent < 0 or percent > 100:
                return "概率仅支持 0～100 的整数（代表 0%～100%）。"
            prob = percent / 100.0
            await self.store.write_key(_PM_PROB_REL, gid, prob)
            return (
                "入群私聊概率已更新\n══════════════\n"
                f"群号：{gid}\n概率：{percent}%\n存储值：{prob}"
            )
        except Exception as e:
            logger.error(f"设置入群私聊概率失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    async def on_group_increase(self, event, raw: dict) -> None:

        try:
            gid = str(raw.get("group_id") or "")
            uid = str(raw.get("user_id") or "")
            if not gid or not uid:
                return
            if not await self.star.group_event_enabled(gid, "join_pm"):
                return
            prob = await self._get_probability(gid)
            if prob <= 0 or random.random() > prob:
                return
            entries = await self.store.read_json(f"{_PM_STORAGE_REL}/{gid}.json", []) or []
            if isinstance(entries, list) and entries:
                await self._replay_entries(uid, gid, entries)
        except Exception as e:
            logger.error(f"入群私聊重放失败: {e}")

    async def _get_probability(self, gid: str) -> float:
        raw = await self.store.read_key(_PM_PROB_REL, str(gid), None)
        if raw is not None:
            try:
                prob = float(raw)
                return max(0.0, min(prob, 1.0))
            except (TypeError, ValueError):
                pass
        try:
            return max(0.0, min(float(self.star.config.get("join_pm_probability", 20)) / 100.0, 1.0))
        except (TypeError, ValueError):
            return 0.2

    async def _record_message(self, event, gid: str) -> bool:

        try:
            segs = getattr(event, "message", None) or []
            text_parts: list = []
            image_urls: list = []
            video_urls: list = []
            forward_nodes: Optional[list] = None
            for seg in segs:
                name = type(seg).__name__.lower()
                if name == "plain":
                    text_parts.append(str(getattr(seg, "text", "")))
                elif name == "image":
                    url = getattr(seg, "url", "") or getattr(seg, "file", "")
                    if url:
                        image_urls.append(str(url))
                elif name == "video":
                    url = getattr(seg, "url", "") or getattr(seg, "file", "")
                    if url:
                        video_urls.append(str(url))

            m = re.search(r"\[CQ:forward,id=(\d+)\]", event.message_str or "")
            if m:
                forward_nodes = await self._fetch_forward_nodes(m.group(1), 0)
            items: list = []
            saved_images = await self._save_media_list(image_urls, gid, "image")
            saved_videos = await self._save_media_list(video_urls, gid, "video")
            text = "".join(text_parts).strip()
            if saved_videos:
                for v in saved_videos:
                    items.append({"类型": "video", "文件": v})
            if text and saved_images:
                items.append({"类型": "text+image", "内容": text, "图片": saved_images})
            elif text:
                items.append({"类型": "text", "内容": text})
            elif saved_images:
                items.append({"类型": "image", "图片": saved_images})
            if forward_nodes:
                items.append({"类型": "forward", "节点": forward_nodes})
            if not items:
                return False
            rel = f"{_PM_STORAGE_REL}/{gid}.json"
            data = await self.store.read_json(rel, []) or []
            if not isinstance(data, list):
                data = []
            data.extend(items)
            await self.store.write_json(rel, data)
            return True
        except Exception as e:
            logger.error(f"入群私聊收录失败: {e}")
            return False

    async def _save_media_list(self, urls: list, gid: str, kind: str) -> list:
        saved: list = []
        for url in urls:
            if not str(url).startswith(("http://", "https://")):
                continue
            name = f"{random.randint(10000000, 999999999)}.{'png' if kind == 'image' else 'mp4'}"
            rel = f"{_PM_STORAGE_REL}/{name}"
            if await self._download(url, rel):
                saved.append(name)
        return saved

    async def _download(self, url: str, rel: str) -> bool:
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return False
                    data = await resp.read()
            if not data:
                return False
            import aiofiles

            p = (self.star.data_path / rel).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(p, "wb") as f:
                await f.write(data)
            return True
        except Exception as e:
            logger.warning(f"入群私聊媒体下载失败 {url}: {e}")
            return False

    async def _fetch_forward_nodes(self, forward_id: str, depth: int) -> list:
        if depth > _MAX_FORWARD_DEPTH or not forward_id:
            return []
        try:
            result = await self.star.api.call_result("get_forward_msg", id=forward_id)
            messages = self._normalize_forward(result)
            nodes: list = []
            for msg in messages:
                node = await self._ob_node(msg, depth)
                if node:
                    nodes.append(node)
            return nodes
        except Exception as e:
            logger.error(f"[入群私聊] get_forward_msg 失败: {e}")
            return []

    @staticmethod
    def _normalize_forward(result: Any) -> list:
        if not isinstance(result, dict):
            return []
        data = result.get("data")
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            return data["messages"]
        if isinstance(data, list):
            return data
        return []

    async def _ob_node(self, msg: Any, depth: int) -> Optional[dict]:
        if not isinstance(msg, dict):
            return None
        if msg.get("type") == "node":
            d = msg.get("data") or {}
            name = str(d.get("name") or d.get("nickname") or "用户")
            uin = str(d.get("uin") or d.get("user_id") or "")
            content = d.get("content") or d.get("message") or []
        else:
            sender = msg.get("sender") or {}
            name = str(sender.get("nickname") or sender.get("card") or "用户")
            uin = str(msg.get("user_id") or sender.get("user_id") or "")
            content = msg.get("message") or msg.get("content") or []
        segments: list = []
        for c in content if isinstance(content, list) else []:
            if not isinstance(c, dict):
                continue
            t = str(c.get("type") or "").lower()
            d = c.get("data") or {}
            if t == "text":
                text = str(d.get("text") or "")
                if text:
                    segments.append({"kind": "text", "内容": text})
            elif t == "image":
                url = d.get("url") or d.get("file") or ""
                if url and str(url).startswith(("http://", "https://")):
                    name = f"{random.randint(10000000, 999999999)}.png"
                    if await self._download(str(url), f"{_PM_STORAGE_REL}/{name}"):
                        segments.append({"kind": "image", "文件": name})
            elif t == "video":
                url = d.get("url") or d.get("file") or ""
                if url and str(url).startswith(("http://", "https://")):
                    name = f"{random.randint(10000000, 999999999)}.mp4"
                    if await self._download(str(url), f"{_PM_STORAGE_REL}/{name}"):
                        segments.append({"kind": "video", "文件": name})
            elif t == "forward" and depth + 1 <= _MAX_FORWARD_DEPTH:
                fid = str(d.get("id") or "")
                if fid:
                    nested = await self._fetch_forward_nodes(fid, depth + 1)
                    if nested:
                        segments.append({"kind": "forward", "节点": nested})
        if not segments:
            return None
        return {"name": name, "uin": uin, "segments": segments}

    async def _replay_entries(self, uid: str, gid: str, entries: list) -> None:

        for entry in entries:
            try:
                await self._replay_one(uid, gid, entry)
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"[入群私聊] 发送失败: {e}")

    async def _replay_one(self, uid: str, gid: str, entry: Any) -> None:
        if not isinstance(entry, dict):
            return
        kind = entry.get("类型", "")
        content = str(entry.get("内容") or "")
        if kind == "text":
            await self.star.sender.send_to_private(uid, content)
        elif kind in ("image", "text+image"):
            files = entry.get("图片") or []
            cq = content
            for name in files:
                p = (self.star.data_path / _PM_STORAGE_REL / str(name)).resolve()
                cq += f"[CQ:image,file={p.as_uri()}]"
            await self.star.sender.send_to_private(uid, cq)
        elif kind == "video":
            p = (self.star.data_path / _PM_STORAGE_REL / str(entry.get("文件") or "")).resolve()
            await self.star.sender.send_to_private(uid, f"[CQ:video,file={p.as_uri()}]")
        elif kind == "json":
            try:
                obj = json.loads(content)
                await self.star.sender.send_to_private(uid, [Comp.Json(data=obj)])
            except (json.JSONDecodeError, ValueError):
                await self.star.sender.send_to_private(uid, content)
        elif kind == "forward":
            nodes = entry.get("节点") or []
            ob_nodes = []
            for node in nodes if isinstance(nodes, list) else []:
                if not isinstance(node, dict):
                    continue
                segs = self._segments_to_chain(node.get("segments") or [])
                if not segs:
                    continue
                ob_nodes.append(
                    self.star.sender.build_node(node.get("name", "用户"), node.get("uin", ""), segs)
                )
            if ob_nodes:
                await self.star.api.call("send_private_forward_msg", user_id=uid, messages=ob_nodes)

    def _segments_to_chain(self, segments: list) -> list:
        chain: list = []
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            kind = seg.get("kind", "")
            if kind == "text":
                from astrbot.api.message_components import Plain
                chain.append(Plain(seg.get("内容", "")))
            elif kind == "image":
                p = (self.star.data_path / _PM_STORAGE_REL / str(seg.get("文件") or "")).resolve()
                chain.append(Comp.Image.fromURL(p.as_uri()))
            elif kind == "video":
                p = (self.star.data_path / _PM_STORAGE_REL / str(seg.get("文件") or "")).resolve()
                chain.append(Comp.Video.fromURL(p.as_uri()))
            elif kind == "forward":
                sub = self._segments_to_chain(seg.get("节点") or [])
                chain += sub
        return chain

    async def legacy(self, event, message: str) -> Any:

        try:

            if event.get_group_id() is None:
                status = await self.store.read_key(_PM_STATUS_REL, "状态", "结束")
                if str(status) == "开始":
                    sender = str(event.get_sender_id())
                    self_id = getattr(getattr(event, "message_obj", None), "self_id", None)
                    if self.star.perm.is_owner(sender) and (not self_id or sender != str(self_id)):
                        gid = str(await self.store.read_key(_PM_STATUS_REL, "群号", ""))
                        if gid and await self._record_message(event, gid):
                            await self.star.sender.send_reply(event, "记录成功！")
                            return None
            m = re.match(r"^(结束|开始)记录([0-9]+|)$", message)
            if m:
                if m.group(1) == "开始":
                    return await self.start_record(event, m.group(2))
                return await self.stop_record(event)
            m = re.match(r"^查看记录内容([0-9]+)$", message)
            if m:
                return await self.view_record(event, m.group(1))
            m = re.match(r"^设置入群私聊概率([0-9]+) ([0-9]+)%$", message)
            if m:
                return await self.set_probability(event, f"{m.group(1)} {m.group(2)}")
        except Exception as e:
            logger.error(f"入群私聊 legacy 异常: {e}")
        return None
