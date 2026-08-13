from __future__ import annotations

import json
import re
from urllib.parse import quote

_CQ_RE = re.compile(r"\[CQ:(\w+)(?:,([^\]]*))?\]")
_IMG_RE = re.compile(r"\[CQ:image,file=([^\]]+)\]")
_AT_RE = re.compile(r"\[CQ:at,qq=(\d+)\]")

def parse_cq_code(text: str) -> list:

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

    m = _AT_RE.search(text)
    return m.group(1) if m else None

def give_images(text: str) -> list:

    return _IMG_RE.findall(text)

def give_images_name(text: str) -> list:

    return give_images(text)

def give_text(segments) -> str:

    parts = []
    for seg in segments or []:
        if seg.get("type") == "text":
            parts.append(seg.get("data", {}).get("text", ""))
    return "".join(parts)

def html_escape(text: str) -> str:

    import html as _html
    return _html.escape(str(text), quote=False)

def html_unescape(text: str) -> str:
    import html as _html
    return _html.unescape(str(text))

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

    raw = quote(json.dumps(data, ensure_ascii=False))
    return f"[CQ:json,data={raw}]"

def cq_music(url: str, audio: str, title: str, content: str = "", image: str = "") -> str:

    return (
        f"[CQ:music,type=custom,url={url},audio={audio},title={title},"
        f"content={content},image={image}]"
    )
