"""小红书视频/图文解析

算法保持与 JS 原版一致：域名白名单校验 -> xhs.com 归一化为 xhslink.com ->
非 www.xiaohongshu.com 链接先解短链重定向 -> 提取笔记 ID ->
抓取页面并解析 window.__INITIAL_STATE__ 内嵌 JSON（note.noteDetailMap / noteData）-
> 失败时用备份 UA 重试，再失败则提取 xsec_token 请求带 token 的 API 页 ->
formatNoteData 提取视频 masterUrl / 图片 CDN 直链 / 实况图，统一转换为
{"title","author","cover","url","type","images","music"} 结构。
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from . import _clean_url_tail, _fetch_text, _follow_redirect, _get_location, _strip_tags

__all__ = ["parse"]

EDGE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"
)
BACKUP_UA = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Mobile Safari/537.36 EdgA/143.0.0.0"
)

ALLOWED_DOMAINS: list[str] = [
    "xiaohongshu.com",
    "xhslink.com",
    "xhs.com",
    "www.xiaohongshu.com",
    "sns-img-hw.xhscdn.com",
    "sns-video-bd.xhscdn.com",
]

_ID_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"discovery/item/([a-zA-Z0-9]+)"),
    re.compile(r"explore/([a-zA-Z0-9]+)"),
    re.compile(r"item/([a-zA-Z0-9]+)"),
    re.compile(r"note/([a-zA-Z0-9]+)"),
)

_NOTES_RE = re.compile(r"/([a-zA-Z0-9_]+)/([a-zA-Z0-9]+)!")
_SHORT_RE = re.compile(r"(notes_pre_post|spectrum|notes_uhdr)/([a-zA-Z0-9]+)")
_BANG_RE = re.compile(r"/([a-zA-Z0-9]+)!")


def _is_allowed_domain(url: str, allowed_domains: list[str]) -> bool:
    """校验链接域名是否在白名单内（对应原 isAllowedDomain）。"""
    cleaned = _clean_url_tail(url)
    for allowed in allowed_domains:
        pattern = f"https?://[^/]*{re.escape(allowed)}"
        if re.search(pattern, cleaned, re.IGNORECASE):
            return True
    return False


def _extract_id(url: str) -> str | None:
    """从 URL 中提取笔记 ID（对应原 extractId）。"""
    for pattern in _ID_PATTERNS:
        matched = pattern.search(url)
        if matched:
            return matched.group(1)
    return None


async def _get_real_url(url: str) -> str:
    """解短链：先取 Location，失败则整体跟随重定向（对应原 getRealUrl）。"""
    location = await _get_location(url, EDGE_USER_AGENT)
    if location:
        return location
    return await _follow_redirect(url, EDGE_USER_AGENT)


async def _request_page(url: str, user_agent: str = EDGE_USER_AGENT) -> str | None:
    """抓取页面 HTML，失败返回 None（对应原 requestPage）。"""
    if not _is_allowed_domain(url, ALLOWED_DOMAINS):
        return None
    try:
        return await _fetch_text(
            url,
            headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/webp,image/apng,*/*;q=0.8,"
                    "application/signed-exchange;v=b3;q=0.7"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            },
            user_agent=user_agent,
        )
    except Exception:  # noqa: BLE001
        return None


def _process_image_url(url: str) -> str:
    """将图片路径重写为可直连的 CDN 地址（对应原 processImageUrl）。"""
    if not url:
        return ""
    notes_match = _NOTES_RE.search(url)
    if notes_match:
        directory = notes_match.group(1)
        file_part = notes_match.group(2)
        if not re.fullmatch(r"[a-f0-9]{32}", directory) and not re.fullmatch(r"\d+", directory):
            return f"https://sns-img-hw.xhscdn.com/{directory}/{file_part}?imageView2/2/w/1080/format/jpg"
    short_match = _SHORT_RE.search(url)
    if short_match:
        return f"https://sns-img-hw.xhscdn.com/{short_match.group(1)}/{short_match.group(2)}?imageView2/2/w/1080/format/jpg"
    bang_match = _BANG_RE.search(url)
    if bang_match:
        return f"https://ci.xiaohongshu.com/{bang_match.group(1)}?imageView2/2/w/1080/format/jpg"
    return url


def _streams_sorted(streams: list[tuple[dict, str]]) -> list[dict]:
    """视频流排序：h265 优先，其次按码率降序（对应原 sort 逻辑）。"""

    def _bitrate(item: dict) -> float:
        return float(item.get("avgBitrate") or item.get("videoBitrate") or 0)

    streams.sort(
        key=lambda pair: (
            0 if pair[1] == "h265" else 1,
            -_bitrate(pair[0]),
        )
    )
    return [pair[0] for pair in streams]


def _format_note_data(note: dict) -> dict:
    """将笔记数据转换为统一输出结构（对应原 formatNoteData）。"""
    content_type = note.get("type") or "unknown"
    if content_type == "normal":
        content_type = "image"

    image_list = note.get("imageList")
    image_list = image_list if isinstance(image_list, list) else []

    cover_url = ""
    if image_list:
        first_image = image_list[0]
        if isinstance(first_image, dict):
            cover_url = (
                first_image.get("urlPre")
                or first_image.get("urlDefault")
                or first_image.get("url")
                or ""
            )
    video_obj = note.get("video")
    video_obj = video_obj if isinstance(video_obj, dict) else {}
    video_image = video_obj.get("image")
    if not cover_url and content_type == "video" and isinstance(video_image, dict):
        if video_image.get("thumbnailFileid"):
            cover_url = f"https://sns-img-hw.xhscdn.com/{video_image['thumbnailFileid']}"
    cover = note.get("cover")
    if not cover_url and isinstance(cover, dict):
        if cover.get("url"):
            cover_url = cover["url"]
        elif cover.get("fileId"):
            cover_url = f"https://sns-img-hw.xhscdn.com/{cover['fileId']}?imageView2/2/w/1080/format/jpg"

    user = note.get("user")
    user = user if isinstance(user, dict) else {}
    author_name = user.get("nickname") or user.get("nickName") or ""

    # 视频直链
    video_url = ""
    if content_type == "video" and video_obj:
        streams: list[tuple[dict, str]] = []
        media = video_obj.get("media")
        media = media if isinstance(media, dict) else {}
        stream = media.get("stream")
        stream = stream if isinstance(stream, dict) else {}
        for item in stream.get("h265") or []:
            if isinstance(item, dict):
                streams.append((item, "h265"))
        for item in stream.get("h264") or []:
            if isinstance(item, dict):
                streams.append((item, "h264"))
        if streams:
            sorted_streams = _streams_sorted(streams)
            video_url = sorted_streams[0].get("masterUrl") or ""
        consumer = video_obj.get("consumer")
        if not video_url and isinstance(consumer, dict) and consumer.get("originVideoKey"):
            video_url = f"http://sns-video-bd.xhscdn.com/{consumer['originVideoKey']}"

    # 图片列表 / 实况图
    images: list[str] = []
    live_photos: list[dict] = []
    if image_list:
        for img in image_list:
            image_url = ""
            if isinstance(img, dict):
                image_url = img.get("url") or img.get("urlDefault") or img.get("urlPre") or ""
            if image_url:
                images.append(_process_image_url(image_url))
            img_stream = img.get("stream") if isinstance(img, dict) else None
            live_url: str | None = None
            if isinstance(img_stream, dict):
                h264_list = img_stream.get("h264") or []
                if h264_list and isinstance(h264_list[0], dict) and h264_list[0].get("masterUrl"):
                    live_url = h264_list[0]["masterUrl"]
                else:
                    h265_list = img_stream.get("h265") or []
                    if h265_list and isinstance(h265_list[0], dict) and h265_list[0].get("masterUrl"):
                        live_url = h265_list[0]["masterUrl"]
            if live_url:
                live_photos.append(
                    {"image": _process_image_url(image_url or ""), "video": live_url}
                )
        if live_photos:
            content_type = "live"

    return {
        "title": str(note.get("title") or ""),
        "author": str(author_name),
        "cover": _process_image_url(cover_url),
        "url": video_url or (live_photos[0]["video"] if live_photos else ""),
        "type": content_type,
        "images": images,
        "music": None,
    }


def _extract_json(html: str, note_id: str) -> dict | None:
    """解析 window.__INITIAL_STATE__ 内嵌 JSON（对应原 extractJson）。"""
    pattern = re.compile(
        r"<script>\s*window\.__INITIAL_STATE__\s*=\s*({[\s\S]*?})</script>",
        re.IGNORECASE,
    )
    matched = pattern.search(html)
    if not matched:
        return None
    json_str = matched.group(1).replace("undefined", "null")
    try:
        json_data: Any = json.loads(json_str)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(json_data, dict):
        return None

    note = None
    note_root = json_data.get("note")
    if isinstance(note_root, dict):
        note_detail_map = note_root.get("noteDetailMap")
        if isinstance(note_detail_map, dict):
            entry = note_detail_map.get(note_id)
            if isinstance(entry, dict):
                note = entry.get("note")
    if not isinstance(note, dict):
        note_data = json_data.get("noteData")
        if isinstance(note_data, dict):
            data = note_data.get("data")
            if isinstance(data, dict):
                note = data.get("noteData")
    if isinstance(note, dict):
        return _format_note_data(note)
    return None


async def _try_parse_with_token(url: str, note_id: str, response: str) -> dict | None:
    """提取 xsec_token 后请求带 token 的 API 页重试（对应原 tryParseWithToken）。"""
    token = ""
    token_match_1 = re.search(r"token=(.*?)&", response)
    token_match_2 = re.search(r'"xsec_token":\s*"([^"]+)"', response)
    if token_match_1:
        token = token_match_1.group(1)
    elif token_match_2:
        token = token_match_2.group(1)
    if not token:
        return None
    api_url = (
        f"https://www.xiaohongshu.com/discovery/item/{note_id}"
        "?app_platform=android&ignoreEngage=true&app_version=8.69.5"
        "&share_from_user_hidden=true&xsec_source=app_share&type=video"
        f"&xsec_token={token}"
    )
    api_response = await _request_page(api_url)
    if not api_response:
        return None
    return _extract_json(api_response, note_id)


async def parse(url: str) -> dict:
    """解析小红书链接，返回统一结构；失败抛 RuntimeError（中文信息）。"""
    try:
        cleaned = _clean_url_tail(_strip_tags((url or "").strip()))
        if not cleaned:
            raise RuntimeError("请输入小红书链接")
        if not _is_allowed_domain(cleaned, ALLOWED_DOMAINS):
            raise RuntimeError("不允许的域名，仅支持小红书官方链接")
        cleaned = cleaned.replace("xhs.com", "xhslink.com")
        try:
            host = urlparse(cleaned).hostname or ""
        except ValueError:
            raise RuntimeError("链接格式错误")

        if host == "www.xiaohongshu.com":
            note_id = _extract_id(cleaned)
        else:
            cleaned = await _get_real_url(cleaned)
            note_id = _extract_id(cleaned)
        if not note_id:
            raise RuntimeError(f"链接格式错误，无法提取ID。处理后的链接: {cleaned}")

        response = await _request_page(cleaned, EDGE_USER_AGENT)
        if not response:
            raise RuntimeError("请求失败")
        data = _extract_json(response, note_id)
        if not data:
            backup_response = await _request_page(cleaned, BACKUP_UA)
            response = backup_response or response
            data = _extract_json(response, note_id)
        if not data:
            data = await _try_parse_with_token(cleaned, note_id, response)
        if data:
            return data
        raise RuntimeError("解析失败，未找到有效内容")
    except RuntimeError:
        raise
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"小红书解析失败: {e}") from e
