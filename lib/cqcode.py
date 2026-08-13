"""CQ 码解析与构造工具。

对应原 index.mjs 的 parseCQCode（L7743）、giveAT（L8004）、
giveImages（L8010）、giveImages_name（L8016）、giveText（L8022）。
AstrBot 发送消息链时并不解析 CQ 码字符串，因此需要把 CQ 码字符串
转为消息段列表（见 lib/sender.py 的 cq_to_chain）。
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote

_CQ_RE = re.compile(r"\[CQ:(\w+)(?:,([^\]]*))?\]")
_IMG_RE = re.compile(r"\[CQ:image,file=([^\]]+)\]")
_AT_RE = re.compile(r"\[CQ:at,qq=(\d+)\]")


def parse_cq_code(text: str) -> list:
    """将 CQ 码字符串解析为段列表：[{"type": ..., "data": {...}}]。

    段之间的纯文本会作为 {"type": "text"} 段保留。
    """
    result: list = []
    pos = 0
    for m in _CQ_RE.finditer(text):
        if m.start() > pos:
            result.append({"type": "text", "data": {"text": text[pos:m.start()]}})
        data: dict = {}
        if m.group(2):
            for kv in m.group(2).split(","):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    data[k] = v
        result.append({"type": m.group(1), "data": data})
        pos = m.end()
    if pos < len(text):
        result.append({"type": "text", "data": {"text": text[pos:]}})
    return result


def give_at(text: str) -> str | None:
    """提取消息中第一个 @ 的 qq（原 giveAT）。"""
    m = _AT_RE.search(text)
    return m.group(1) if m else None


def give_images(text: str) -> list:
    """提取消息中所有图片 file（原 giveImages）。"""
    return _IMG_RE.findall(text)


def give_images_name(text: str) -> list:
    """同 give_images（原 giveImages_name）。"""
    return give_images(text)


def give_text(segments) -> str:
    """从段列表提取纯文本拼接（原 giveText）。"""
    parts = []
    for seg in segments or []:
        if seg.get("type") == "text":
            parts.append(seg.get("data", {}).get("text", ""))
    return "".join(parts)


def html_escape(text: str) -> str:
    """HTML 转义，用于模板占位（原 index.mjs 中多处自实现）。"""
    import html as _html
    return _html.escape(str(text), quote=False)


def html_unescape(text: str) -> str:
    import html as _html
    return _html.unescape(str(text))


# ---------- CQ 码构造 ----------

def cq_at(qq: Any) -> str:
    return f"[CQ:at,qq={qq}]"


def cq_at_all() -> str:
    return "[CQ:at,qq=all]"


def cq_reply(message_id: Any) -> str:
    return f"[CQ:reply,id={message_id}]"


def cq_image(url: str) -> str:
    return f"[CQ:image,file={url}]"


def cq_record(url: str) -> str:
    return f"[CQ:record,file={url}]"


def cq_face(face_id: Any) -> str:
    return f"[CQ:face,id={face_id}]"


def cq_json(data: dict) -> str:
    """构造 JSON 卡片段（原 L12008，转义 &[]）。"""
    raw = quote(json.dumps(data, ensure_ascii=False))
    return f"[CQ:json,data={raw}]"


def cq_music(url: str, audio: str, title: str, content: str = "", image: str = "") -> str:
    """构造自定义音乐分享段（原 L12001）。"""
    return (
        f"[CQ:music,type=custom,url={url},audio={audio},title={title},"
        f"content={content},image={image}]"
    )
