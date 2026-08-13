"""消息发送封装。

对应原 index.mjs 的 callSendMsg（L7710）、sendReply（L7719）、sendReply2（L7728）、
sendForward（L7980）、buildForwardNode（L7889）、buildForwardContent（L7798）。
AstrBot 中被动回复经 event.send() / event.chain_result() 发送；
主动推送经 self.context.send_message(unified_msg_origin, chain) 发送。
CQ 码字符串需先转为消息链（cq_to_chain），AstrBot 不解析 CQ 码。
"""
from __future__ import annotations

import json
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger

from lib.cqcode import parse_cq_code


def cq_to_chain(text: str) -> list:
    """把 CQ 码字符串转换为 AstrBot 消息链（List[BaseMessageComponent]）。

    无法识别的段会被忽略并记日志，不中断整条消息。
    """
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
        except Exception as e:  # noqa: BLE001
            logger.warning(f"CQ 段转换失败 {seg}: {e}")
    return chain


def to_chain(content: Any) -> list:
    """把各种输入统一为消息链：str（含 CQ 码）、dict、list。"""
    if isinstance(content, str):
        return cq_to_chain(content) or [Comp.Plain(content)]
    if isinstance(content, dict):
        return [Comp.Json(data=content)]
    if isinstance(content, list):
        return content
    return [Comp.Plain(str(content))]


class Sender:
    """发送封装，挂载在 Star 实例上。"""

    def __init__(self, star: Any) -> None:
        self.star = star

    # ---------- 被动回复 ----------

    async def send_reply(self, event: Any, content: Any) -> None:
        """回复当前事件（content 可为 CQ 码字符串 / 链 / dict）。"""
        try:
            chain = to_chain(content)
            await event.send(event.chain_result(chain))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"send_reply 失败: {e}")

    async def send_reply_multi(self, event: Any, contents: list) -> None:
        """依次发送多条回复（原 plugin_onmessage 的数组逐条发送）。"""
        for c in contents:
            await self.send_reply(event, c)

    # ---------- 主动推送 ----------

    async def _umo(self, message_type: str, target_id: Any) -> str:
        """优先使用运行期缓存到的真实 unified_msg_origin，否则按平台格式构造。"""
        cache_key = f"umo/{message_type}_{target_id}"
        cached = await self.star.get_kv_data(cache_key, "")
        if cached:
            return str(cached)
        kind = "group" if message_type == "group" else "private"
        return f"aiocqhttp:{kind}:{target_id}"

    async def send_to_group(self, gid: Any, content: Any) -> bool:
        """主动向群发送消息。"""
        try:
            await self.star.context.send_message(
                await self._umo("group", gid), to_chain(content)
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"向群 {gid} 主动发送失败: {e}")
            return False

    async def send_to_private(self, uid: Any, content: Any) -> bool:
        """主动向好友发送消息。"""
        try:
            await self.star.context.send_message(
                await self._umo("private", uid), to_chain(content)
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"向好友 {uid} 主动发送失败: {e}")
            return False

    # ---------- 合并转发 ----------

    def build_node(self, name: str, uin: Any, content: Any) -> dict:
        """构造合并转发节点（原 buildForwardNode）。content 可为 CQ 码字符串。"""
        if isinstance(content, str):
            segs = to_chain(content)
        else:
            segs = content
        return {"type": "node", "data": {"name": name, "uin": str(uin), "content": segs}}

    def build_forward_content(self, blocks: dict) -> list:
        """把 {text, json, xml, image(s), video(s)} 块转为段列表（原 buildForwardContent）。"""
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
        """发送合并转发（群内优先群转发，失败回退 send_forward_msg，原 sendForward）。"""
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
