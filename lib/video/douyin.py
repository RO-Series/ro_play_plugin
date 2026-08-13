"""抖音视频解析（对应原 MKbot 2.3.4 napcat-plugin-mkbot/lib/api/dy.mjs）。

算法保持与 JS 原版一致：提取链接 -> v.douyin.com 短链先解重定向得到真实链接 ->
提取视频 ID -> 依次请求 iesdouyin.com / douyin.com 的 share 页 ->
解析页面内嵌状态 RENDER_DATA（URI 编码 JSON）或 window._ROUTER_DATA 配平 JSON ->
按 bitRateList / play_addr / playApi 提取最高画质直链（playwm 换 play、v26-web 换
v26-luna 域名）-> 统一转换为 {"title","author","cover","url","type","images","music"}。
页面编码按 utf-8 解码，出错回退 gbk。
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote, unquote, urlparse

from . import _extract_balanced_json, _clean_url_tail, _fetch_text, _follow_redirect, _get_location, _strip_tags

__all__ = ["parse"]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 8.0.0; SM-G955U Build/R16NW) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/103.0.0.0 Mobile Safari/537.36"
)

_RENDER_START = '<script id="RENDER_DATA" type="application/json">'

_ID_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"/share/note/(\d+)"),
    re.compile(r"/share/video/(\d+)"),
    re.compile(r"/share/slides/(\d+)"),
    re.compile(r"/video/(\d+)"),
    re.compile(r"/note/(\d+)"),
    re.compile(r"/slides/(\d+)"),
    re.compile(r"modal_id=(\d+)"),
    re.compile(r"[?&]item_ids=(\d+)"),
    re.compile(r"^(\d+)$"),
)


def _extract_douyin_url(text: str) -> str:
    """从文本中提取抖音链接（对应原 extractDouyinUrl）。"""
    short_match = re.search(r"https?://v\.douyin\.com/[\w-]+", text, re.IGNORECASE)
    if short_match:
        return short_match.group(0).strip()
    long_match = re.search(r"https?://(?:www\.)?douyin\.com/[^\s]+", text, re.IGNORECASE)
    if long_match:
        return _clean_url_tail(long_match.group(0).strip())
    any_match = re.search(r"https?://[^\s]*douyin\.com[^\s]*", text, re.IGNORECASE)
    if any_match:
        return _clean_url_tail(any_match.group(0).strip())
    return (text or "").strip()


def _extract_id(url: str) -> str | None:
    """从 URL 中提取作品 ID（对应原 extractId）。"""
    for pattern in _ID_PATTERNS:
        matched = pattern.search(url)
        if matched:
            return matched.group(1)
    return None


def _is_note_url(url: str) -> bool:
    """判断是否为图文笔记链接。"""
    return re.search(r"/note/|share/note", url, re.IGNORECASE) is not None


def _is_slides_url(url: str) -> bool:
    """判断是否为图文幻灯片链接。"""
    return re.search(r"/slides/|share/slides", url, re.IGNORECASE) is not None


def _build_share_fetch_urls(resolved_url: str, vid: str) -> list[str]:
    """构造候选抓取页面 URL（对应原 buildShareFetchUrls）。"""
    urls: list[str] = []
    if _is_note_url(resolved_url):
        urls.append(f"https://www.iesdouyin.com/share/note/{vid}/")
        urls.append(f"https://www.douyin.com/note/{vid}")
    elif _is_slides_url(resolved_url):
        urls.append(f"https://www.iesdouyin.com/share/slides/{vid}/")
    urls.append(f"https://www.iesdouyin.com/share/video/{vid}/")
    urls.append(f"https://www.douyin.com/video/{vid}")
    urls.append(f"https://www.douyin.com/user/self?modal_id={vid}&showTab=like")
    seen: set[str] = set()
    result: list[str] = []
    for item in urls:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _is_blocked_html(html: str) -> bool:
    """判断是否命中风控/空页面（对应原 isBlockedHtml）。"""
    if "waf-js" in html and len(html) < 10000:
        return True
    if len(html) < 3000:
        return True
    return False


def _pick_best_play_url(candidates: list[str]) -> str | None:
    """优先 v3-web，其次 v26-web（替换为 v26-luna 域名），否则取第一个（对应原 pickBestPlayUrl）。"""
    if not candidates:
        return None
    v26_link: str | None = None
    for candidate in candidates:
        if "v3-web" in candidate:
            return candidate
        if "v26-web" in candidate:
            v26_link = candidate
    if v26_link:
        return re.sub(r"://([^/]+)", "://v26-luna.douyinvod.com", v26_link, count=1)
    return candidates[0]


def _extract_live_video_url(video_info: Any) -> str | None:
    """从图文项内嵌视频信息中提取实况视频直链（对应原 extractLiveVideoUrl）。"""
    live_url: str | None = None
    if isinstance(video_info, dict):
        play_addr = video_info.get("playAddr")
        if isinstance(play_addr, list):
            candidates = [
                addr.get("src")
                for addr in play_addr
                if isinstance(addr, dict) and addr.get("src")
            ]
            live_url = _pick_best_play_url(candidates)
            if not live_url and len(play_addr) > 1 and isinstance(play_addr[1], dict):
                live_url = play_addr[1].get("src")
            if not live_url and play_addr and isinstance(play_addr[0], dict):
                live_url = play_addr[0].get("src")
        play_addr_snake = video_info.get("play_addr")
        if not live_url and isinstance(play_addr_snake, dict):
            url_list = play_addr_snake.get("url_list") or []
            if url_list:
                live_url = _pick_best_play_url([str(item) for item in url_list])
                if not live_url:
                    live_url = (
                        str(url_list[1]) if len(url_list) > 1 else str(url_list[0])
                    )
        play_api = video_info.get("playApi")
        if not live_url and isinstance(play_api, str):
            live_url = play_api
    if live_url:
        return live_url.replace("playwm", "play")
    return None


def _extract_highest_quality_video(detail: dict) -> tuple[str | None, list[str]]:
    """提取最高画质直链及备用列表（对应原 extractHighestQualityVideo）。"""
    url: str | None = None
    backup: list[str] = []
    video = detail.get("video")
    if not isinstance(video, dict):
        video = None

    if video is not None:
        bit_rate_list = video.get("bitRateList")
        if isinstance(bit_rate_list, list) and bit_rate_list:
            sorted_rates = sorted(
                bit_rate_list,
                key=lambda item: float(item.get("bitRate") or 0)
                if isinstance(item, dict)
                else 0.0,
                reverse=True,
            )
            for rate_item in sorted_rates:
                candidates: list[str] = []
                if isinstance(rate_item, dict):
                    play_addr = rate_item.get("playAddr")
                    if isinstance(play_addr, list):
                        candidates = [
                            pa.get("src")
                            for pa in play_addr
                            if isinstance(pa, dict) and pa.get("src")
                        ]
                    else:
                        play_addr_snake = rate_item.get("play_addr")
                        if isinstance(play_addr_snake, dict):
                            candidates = [
                                str(item)
                                for item in (play_addr_snake.get("url_list") or [])
                            ]
                if not candidates:
                    continue
                current_best = _pick_best_play_url(candidates)
                if not url and current_best:
                    url = current_best
                for candidate in candidates:
                    if "v26-web" in candidate:
                        candidate = re.sub(
                            r"://([^/]+)",
                            "://v26-luna.douyinvod.com",
                            candidate,
                            count=1,
                        )
                    if candidate != url and candidate not in backup:
                        backup.append(candidate)
                if url and backup:
                    break

        if not url:
            uri = video.get("uri")
            play_addr = video.get("play_addr")
            play_api = video.get("playApi")
            if not play_api and isinstance(play_addr, dict):
                url_list = play_addr.get("url_list") or []
                if url_list:
                    play_api = url_list[0]
            if play_api:
                url = str(play_api).replace("playwm", "play")
            elif uri:
                url = (
                    "https://aweme.snssdk.com/aweme/v1/play/"
                    f"?video_id={quote(str(uri))}&ratio=720p&line=0"
                )
            if isinstance(play_addr, dict):
                url_list = play_addr.get("url_list") or []
                for i in range(1, len(url_list)):
                    backup.append(str(url_list[i]).replace("playwm", "play"))

    if url:
        url = url.replace("playwm", "play")
    return url, backup


def _extract_cover(detail: dict) -> str:
    """提取封面图（对应原 extractCover）。"""
    video = detail.get("video")
    video = video if isinstance(video, dict) else {}
    cover = ""

    origin_cover = video.get("originCover")
    origin_cover_snake = video.get("origin_cover")
    if isinstance(origin_cover, dict):
        url_list = origin_cover.get("urlList") or []
        if url_list:
            cover = url_list[0]
    if not cover and isinstance(origin_cover_snake, dict):
        url_list = origin_cover_snake.get("url_list") or []
        if url_list:
            cover = url_list[0]
    if not cover and isinstance(origin_cover, str):
        cover = origin_cover
    if not cover:
        origin_cover_list = video.get("originCoverUrlList")
        if isinstance(origin_cover_list, list) and origin_cover_list and origin_cover_list[0]:
            cover = str(origin_cover_list[0])

    if not cover and video:
        cover_obj = video.get("cover")
        if isinstance(cover_obj, str):
            cover = cover_obj
        elif isinstance(cover_obj, dict):
            url_list = cover_obj.get("urlList") or []
            if url_list:
                cover = url_list[0]
            if not cover:
                url_list_snake = cover_obj.get("url_list") or []
                if url_list_snake:
                    cover = url_list_snake[0]

    detail_cover = detail.get("cover")
    if not cover and isinstance(detail_cover, dict):
        url_list = detail_cover.get("url_list") or []
        if url_list:
            cover = url_list[0]

    if not cover and video:
        dynamic_cover = video.get("dynamicCover")
        dynamic_cover_snake = video.get("dynamic_cover")
        if isinstance(dynamic_cover, dict):
            url_list = dynamic_cover.get("urlList") or []
            if url_list:
                cover = url_list[0]
        if not cover and isinstance(dynamic_cover_snake, dict):
            url_list = dynamic_cover_snake.get("url_list") or []
            if url_list:
                cover = url_list[0]
    return cover


def _build_music_info(detail: dict) -> dict:
    """构造统一 music 结构（对应原 formatData 中的 music 字段）。"""
    music = detail.get("music")
    music = music if isinstance(music, dict) else {}
    info: dict = {
        "title": music.get("musicName") or music.get("title") or "",
        "author": music.get("ownerNickname") or music.get("author") or "",
        "url": "",
        "cover": "",
    }
    play_url = music.get("playUrl")
    play_url_snake = music.get("play_url")
    if isinstance(play_url, dict):
        info["url"] = play_url.get("uri") or ""
    if not info["url"] and isinstance(play_url_snake, dict):
        info["url"] = play_url_snake.get("uri") or ""
    cover_thumb = music.get("coverThumb")
    cover_thumb_snake = music.get("cover_thumb")
    if isinstance(cover_thumb, dict):
        url_list = cover_thumb.get("urlList") or []
        if url_list:
            info["cover"] = url_list[0]
    if not info["cover"] and isinstance(cover_thumb_snake, dict):
        url_list = cover_thumb_snake.get("url_list") or []
        if url_list:
            info["cover"] = url_list[0]
    return info


def _format_data(detail: dict) -> dict:
    """将页面内嵌 detail 转换为统一输出结构（对应原 formatData）。"""
    author_info = detail.get("authorInfo")
    author = detail.get("author")
    author_info = author_info if isinstance(author_info, dict) else {}
    author = author if isinstance(author, dict) else {}
    author_name = author_info.get("nickname") or author.get("nickname") or ""

    cover = _extract_cover(detail)
    music_info = _build_music_info(detail)

    images = detail.get("images")
    if isinstance(images, list) and images:
        image_urls: list[str] = []
        live_photos: list[dict] = []
        for img in images:
            img_url = ""
            if isinstance(img, dict):
                url_list = img.get("urlList") or []
                if url_list:
                    img_url = url_list[0] or ""
                if not img_url:
                    url_list_snake = img.get("url_list") or []
                    if url_list_snake:
                        img_url = url_list_snake[0] or ""
            if img_url:
                image_urls.append(img_url)
            video_info = img.get("video") if isinstance(img, dict) else None
            live_url = _extract_live_video_url(video_info)
            if live_url:
                live_photos.append({"image": img_url, "video": live_url})
        if live_photos:
            return {
                "title": str(detail.get("desc") or ""),
                "author": str(author_name),
                "cover": cover,
                "url": live_photos[0]["video"],
                "type": "live",
                "images": image_urls,
                "music": music_info,
            }
        return {
            "title": str(detail.get("desc") or ""),
            "author": str(author_name),
            "cover": cover,
            "url": "",
            "type": "image",
            "images": image_urls,
            "music": music_info,
        }

    video_url, _backup = _extract_highest_quality_video(detail)
    return {
        "title": str(detail.get("desc") or ""),
        "author": str(author_name),
        "cover": cover,
        "url": video_url or "",
        "type": "video",
        "images": [],
        "music": music_info,
    }


def _extract_json_from_html(html: str) -> dict | None:
    """解析页面内嵌状态：优先 RENDER_DATA，其次 window._ROUTER_DATA（对应原 extractJsonFromHtml）。"""
    pos = html.find(_RENDER_START)
    if pos >= 0:
        chunk = html[pos + len(_RENDER_START):]
        end = chunk.find("</script>")
        if end >= 0:
            try:
                decoded = unquote(chunk[:end])
                data: Any = json.loads(decoded)
                if isinstance(data, dict):
                    app = data.get("app")
                    if isinstance(app, dict):
                        video_detail = app.get("videoDetail")
                        if isinstance(video_detail, dict):
                            return video_detail
            except Exception:  # noqa: BLE001
                pass

    router_json = _extract_balanced_json(html, "window._ROUTER_DATA")
    if router_json:
        try:
            data = json.loads(router_json)
            if isinstance(data, dict):
                loader = data.get("loaderData")
                if isinstance(loader, dict):
                    for key, page in loader.items():
                        if "page" not in key:
                            continue
                        if not isinstance(page, dict):
                            continue
                        video_info_res = page.get("videoInfoRes")
                        if isinstance(video_info_res, dict):
                            item_list = video_info_res.get("item_list")
                            if isinstance(item_list, list) and item_list:
                                return item_list[0]
        except Exception:  # noqa: BLE001
            pass
    return None


async def _request_page(url: str, user_agent: str = MOBILE_UA) -> str | None:
    """抓取页面 HTML，命中风控/空页返回 None（对应原 requestPage）。"""
    try:
        html = await _fetch_text(
            url,
            headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/webp,image/apng,*/*;q=0.8"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://www.douyin.com/",
            },
            user_agent=user_agent,
        )
    except Exception:  # noqa: BLE001
        return None
    if _is_blocked_html(html):
        return None
    return html


async def _fetch_detail_by_id(resolved_url: str, vid: str) -> dict | None:
    """依次尝试候选页面与 UA，返回首个命中 detail（对应原 fetchDetailById）。"""
    page_urls = _build_share_fetch_urls(resolved_url, vid)
    for page_url in page_urls:
        is_ies = "iesdouyin.com" in page_url
        uas = [MOBILE_UA, USER_AGENT] if is_ies else [USER_AGENT, MOBILE_UA]
        for ua in uas:
            html = await _request_page(page_url, ua)
            if not html:
                continue
            detail = _extract_json_from_html(html)
            if detail:
                return detail
    return None


async def _get_real_url(url: str) -> str:
    """解短链：先取 Location，失败则整体跟随重定向（对应原 getRealUrl）。"""
    location = await _get_location(url, MOBILE_UA)
    if location:
        return location
    return await _follow_redirect(url, MOBILE_UA)


async def parse(url: str) -> dict:
    """解析抖音链接，返回统一结构；失败抛 RuntimeError（中文信息）。"""
    cleaned_url = _clean_url_tail(_strip_tags(_extract_douyin_url(url)))
    if not cleaned_url:
        raise RuntimeError("请输入抖音链接")
    try:
        host = urlparse(cleaned_url).hostname or ""
    except ValueError:
        raise RuntimeError("链接格式错误")
    if host.lower() == "v.douyin.com" or "douyin.com" not in cleaned_url or not _extract_id(cleaned_url):
        cleaned_url = await _get_real_url(cleaned_url)
    vid = _extract_id(cleaned_url)
    if not vid:
        raise RuntimeError(f"链接格式错误，无法提取ID。处理后的链接: {cleaned_url}")
    detail = await _fetch_detail_by_id(cleaned_url, vid)
    if not detail:
        raise RuntimeError("解析失败，未找到有效内容（可能触发抖音风控，请稍后重试）")
    return _format_data(detail)
