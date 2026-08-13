from __future__ import annotations

import json
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger

from lib.cqcode import parse_cq_code

def cq_to_chain(text: str) -> list:

    chain: list = []
    for seg in parse_cq_code(text):
        t = seg["type"]
        d = seg.get("data", {})
        try:
            if t == "text":
                chain.append(Comp.Plain(d.get("text", "")))
            elif t == "at":
                chain.append(Comp.At(qq=d.get("qq", "")))
            elif t == "image":
                file = d.get("file", "")
                if file.startswith(("http://", "https://")):
                    chain.append(Comp.Image.fromURL(file))
                else:
                    chain.append(Comp.Image(file=file))
            elif t == "record":
                file = d.get("file", "")
                chain.append(Comp.Record(file=file, url=file))
            elif t == "video":
                url = d.get("url") or d.get("file") or ""
                if url.startswith(("http://", "https://")):
                    chain.append(Comp.Video.fromURL(url))
                else:
                    chain.append(Comp.Video(file=url))
            elif t == "reply":
                chain.append(Comp.Reply(id=str(d.get("id", ""))))
            elif t == "face":
                chain.append(Comp.Face(id=d.get("id", "0")))
            elif t == "music":
                chain.append(
                    Comp.Music(
                        kind="custom",
                        url=d.get("url", ""),
                        audio=d.get("audio", ""),
                        title=d.get("title", ""),
                        content=d.get("content", ""),
                        image=d.get("image", ""),
                    )
                )
            elif t == "json":
                try:
                    chain.append(Comp.Json(data=json.loads(d.get("data", "{}"))))
                except (json.JSONDecodeError, ValueError):
                    pass
        except Exception as e:
            logger.warning(f"CQ 段转换失败 {seg}: {e}")
    return chain

def to_chain(content: Any) -> list:

    if isinstance(content, str):
        return cq_to_chain(content) or [Comp.Plain(content)]
    if isinstance(content, dict):
        return [Comp.Json(data=content)]
    if isinstance(content, list):
        return content
    return [Comp.Plain(str(content))]

class Sender:

    def __init__(self, star: Any) -> None:
        self.star = star

    async def send_reply(self, event: Any, content: Any) -> None:

        try:
            chain = to_chain(content)
            await event.send(event.chain_result(chain))
        except Exception as e:
            logger.warning(f"send_reply 失败: {e}")

    async def send_reply_multi(self, event: Any, contents: list) -> None:

        for c in contents:
            await self.send_reply(event, c)

    async def _umo(self, message_type: str, target_id: Any) -> str:

        cache_key = f"umo/{message_type}_{target_id}"
        cached = await self.star.get_kv_data(cache_key, "")
        if cached:
            return str(cached)
        kind = "group" if message_type == "group" else "private"
        return f"aiocqhttp:{kind}:{target_id}"

    async def send_to_group(self, gid: Any, content: Any) -> bool:

        try:
            await self.star.context.send_message(
                await self._umo("group", gid), to_chain(content)
            )
            return True
        except Exception as e:
            logger.warning(f"向群 {gid} 主动发送失败: {e}")
            return False

    async def send_to_private(self, uid: Any, content: Any) -> bool:

        try:
            await self.star.context.send_message(
                await self._umo("private", uid), to_chain(content)
            )
            return True
        except Exception as e:
            logger.warning(f"向好友 {uid} 主动发送失败: {e}")
            return False

    def build_node(self, name: str, uin: Any, content: Any) -> dict:

        if isinstance(content, str):
            segs = to_chain(content)
        else:
            segs = content
        return {"type": "node", "data": {"name": name, "uin": str(uin), "content": segs}}

    def build_forward_content(self, blocks: dict) -> list:

        segs: list = []
        if blocks.get("text"):
            segs += to_chain(str(blocks["text"]))
        if blocks.get("json"):
            segs.append(Comp.Json(data=blocks["json"]))
        for u in blocks.get("image", []) or []:
            segs.append(Comp.Image.fromURL(u) if str(u).startswith("http") else Comp.Image(file=str(u)))
        for v in blocks.get("video", []) or []:
            segs.append(Comp.Video.fromURL(v) if str(v).startswith("http") else Comp.Video(file=str(v)))
        return segs

    async def send_forward(self, event: Any, nodes: list) -> bool:

        gid = event.get_group_id()
        if gid:
            ok = await self.star.api.call("send_group_forward_msg", group_id=gid, messages=nodes)
            if ok:
                return True
            return await self.star.api.call("send_forward_msg", group_id=gid, messages=nodes)
        uid = event.get_sender_id()
        ok = await self.star.api.call("send_private_forward_msg", user_id=uid, messages=nodes)
        if ok:
            return True
        return await self.star.api.call("send_forward_msg", user_id=uid, messages=nodes)
