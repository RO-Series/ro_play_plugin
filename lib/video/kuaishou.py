"""快手视频/图片解析（对应原 MKbot 2.3.4 napcat-plugin-mkbot/lib/api/ks.mjs）。

算法保持与 JS 原版一致：提取链接 -> 跟随重定向得到真实链接 ->
识别内容类型（short-video / long-video / photo）与内容 ID ->
抓取页面并依次解析内嵌状态 window.INIT_STATE（tusjoh 开头的媒体节点，
支持多图 atlas / 单图 / 视频 mainMvUrls / manifest）与 window.__APOLLO_STATE__
（defaultClient 下的 VisionVideoDetailPhoto 节点）-> 统一转换为
{"title","author","cover","url","type","images","music"} 结构。
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import _extract_balanced_json, _clean_url_tail, _fetch_text, _get_session

__all__ = ["parse"]

USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1 Edg/122.0.0.0"
)


def _extract_kuaishou_url(text: str) -> str:
    """从文本中提取快手链接（对应原 extractKuaishouUrl）。"""
    short_match = re.search(r"https?://v\.kuaishou\.com/[\w-]+", text, re.IGNORECASE)
    if short_match:
        return short_match.group(0).strip()
    any_match = re.search(r"https?://[^\s]*kuaishou\.com[^\s]*", text, re.IGNORECASE)
    if any_match:
        return _clean_url_tail(any_match.group(0).strip())
    return (text or "").strip()


async def _get_redirected_url(url: str) -> str | None:
    """跟随重定向并返回最终 URL；失败返回 None（对应原 getRedirectedUrl）。"""
    try:
        async with _get_session().get(
            url, headers={"User-Agent": USER_AGENT}, allow_redirects=True
        ) as resp:
            return str(resp.url)
    except Exception:  # noqa: BLE001
        return None


async def _curl_request(url: str) -> str | None:
    """抓取页面 HTML，失败返回 None（对应原 curlRequest）。"""
    try:
        return await _fetch_text(
            url,
            headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,image/apng,*/*;q=0.8"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Upgrade-Insecure-Requests": "1",
            },
            user_agent=USER_AGENT,
        )
    except Exception:  # noqa: BLE001
        return None


def _extract_content_id_and_type(url: str) -> tuple[str, str]:
    """识别内容类型与 ID（对应原 extractContentIdAndType）。"""
    patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("short-video", re.compile(r"short-video/([^?]+)")),
        ("long-video", re.compile(r"long-video/([^?]+)")),
        ("photo", re.compile(r"photo/([^?]+)")),
    )
    for content_type, pattern in patterns:
        matched = pattern.search(url)
        if matched:
            return content_type, matched.group(1)
    return "", ""


def _filter_media_data(data: dict) -> dict:
    """只保留 tusjoh 开头且含 fid/photo 的媒体节点（对应原 filterMediaData）。"""
    filtered: dict = {}
    for key, value in data.items():
        if not str(key).startswith("tusjoh"):
            continue
        if isinstance(value, dict) and ("fid" in value or "photo" in value):
            filtered[key] = value
    return filtered


def _build_music_info(photo: dict) -> dict:
    """构造音乐信息（对应原 buildMusicInfo，name/artist 字段）。"""
    music = photo.get("music") or photo.get("soundTrack") or {}
    music = music if isinstance(music, dict) else {}
    cover = ""
    image_urls = music.get("imageUrls") or []
    if isinstance(image_urls, list) and image_urls and isinstance(image_urls[0], dict):
        cover = image_urls[0].get("url") or ""
    if not cover:
        avatar_urls = music.get("avatarUrls") or []
        if isinstance(avatar_urls, list) and avatar_urls and isinstance(avatar_urls[0], dict):
            cover = avatar_urls[0].get("url") or ""
    audio_url = ""
    audio_urls = music.get("audioUrls") or []
    if isinstance(audio_urls, list) and audio_urls and isinstance(audio_urls[0], dict):
        audio_url = audio_urls[0].get("url") or ""
    return {
        "name": str(music.get("name") or ""),
        "artist": str(music.get("artist") or ""),
        "cover": str(cover),
        "url": str(audio_url),
    }


def _unify_music(music_info: dict) -> dict:
    """将 name/artist 字段映射为统一结构的 title/author。"""
    return {
        "title": music_info.get("name") or "",
        "author": music_info.get("artist") or "",
        "url": music_info.get("url") or "",
        "cover": music_info.get("cover") or "",
    }


def _safe_photo(first_item: Any) -> dict:
    """从媒体节点中安全取出 photo 对象。"""
    if not isinstance(first_item, dict):
        return {}
    photo = first_item.get("photo")
    return photo if isinstance(photo, dict) else {}


def _parse_init_state(page_content: str) -> dict | None:
    """解析 window.INIT_STATE 内嵌状态（对应原 parseInitState）。"""
    json_string = _extract_balanced_json(page_content, "window.INIT_STATE")
    if not json_string:
        return None
    json_string = re.sub(r";\s*$", "", json_string)
    try:
        data: Any = json.loads(json_string)
    except Exception:  # noqa: BLE001
        cleaned = (
            json_string.replace('\\"', '"')
            .replace(
                '"{"err_msg":"launchApplication:fail"}"',
                '"err_msg","launchApplication:fail"',
            )
            .replace(
                '"{"err_msg":"system:access_denied"}"',
                '"err_msg","system:access_denied"',
            )
        )
        try:
            data = json.loads(cleaned)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"JSON解析错误: {e}") from e
    if not isinstance(data, dict):
        return None

    filtered_data = _filter_media_data(data)
    if not filtered_data:
        return None
    first_item = next(iter(filtered_data.values()))
    photo = _safe_photo(first_item)
    music_info = _build_music_info(photo)

    atlas = photo.get("ext_params")
    atlas = atlas if isinstance(atlas, dict) else {}
    atlas_obj = atlas.get("atlas")
    atlas_obj = atlas_obj if isinstance(atlas_obj, dict) else {}
    image_list = atlas_obj.get("list") or []
    if isinstance(image_list, list) and image_list:
        images = [f"http://tx2.a.yximgs.com/{path}" for path in image_list]
        music_path = atlas_obj.get("music") or ""
        music_url = f"http://txmov2.a.kwimgs.com{music_path}" if music_path else ""
        return {
            "title": str(photo.get("caption") or ""),
            "author": str(photo.get("userName") or ""),
            "cover": images[0],
            "url": images[0],
            "type": "image",
            "images": images,
            "music": {"title": "", "author": "", "url": music_url, "cover": ""},
        }

    if photo.get("photoType") == "SINGLE_PICTURE" or photo.get("singlePicture") is True:
        cover_urls = photo.get("coverUrls")
        image_url = ""
        if isinstance(cover_urls, list) and cover_urls and isinstance(cover_urls[0], dict):
            image_url = cover_urls[0].get("url") or ""
        if image_url:
            return {
                "title": str(photo.get("caption") or ""),
                "author": str(photo.get("userName") or ""),
                "cover": image_url,
                "url": image_url,
                "type": "image",
                "images": [image_url],
                "music": _unify_music(music_info),
            }

    if photo.get("mainMvUrls") or photo.get("photoType") == "VIDEO":
        main_mv_urls = photo.get("mainMvUrls")
        video_url = ""
        if isinstance(main_mv_urls, list) and main_mv_urls and isinstance(main_mv_urls[0], dict):
            video_url = main_mv_urls[0].get("url") or ""
        manifest = photo.get("manifest")
        manifest = manifest if isinstance(manifest, dict) else {}
        if not video_url:
            adaptation_set = manifest.get("adaptationSet") or []
            if isinstance(adaptation_set, list) and adaptation_set and isinstance(adaptation_set[0], dict):
                representation = adaptation_set[0].get("representation") or []
                if isinstance(representation, list) and representation and isinstance(representation[0], dict):
                    video_url = representation[0].get("url") or ""
        if video_url:
            cover_urls = photo.get("coverUrls")
            cover = ""
            if isinstance(cover_urls, list) and cover_urls and isinstance(cover_urls[0], dict):
                cover = cover_urls[0].get("url") or ""
            return {
                "title": str(photo.get("caption") or ""),
                "author": str(photo.get("userName") or ""),
                "cover": cover,
                "url": video_url,
                "type": "video",
                "images": [],
                "music": _unify_music(music_info),
            }
    return None


def _parse_apollo_state(page_content: str, content_id: str, content_type: str) -> dict | None:
    """解析 window.__APOLLO_STATE__ 内嵌状态（对应原 parseApolloState）。"""
    raw = _extract_balanced_json(page_content, "window.__APOLLO_STATE__")
    if not raw:
        return None
    # 等价于原 JS 的连续 replace：清理函数字面量、多余逗号与自执行残片
    cleaned_data = re.sub(r"function\s*\([^)]*\)\s*{[^}]*}", ":", raw)
    cleaned_data = re.sub(r",\s*(?=}|])", "", cleaned_data)
    cleaned_data = re.sub(r";\(:?\(\)\);/", "", cleaned_data)
    try:
        apollo_state: Any = json.loads(cleaned_data)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(apollo_state, dict):
        return None
    video_info = apollo_state.get("defaultClient")
    if not isinstance(video_info, dict):
        return None

    key = f"VisionVideoDetailPhoto:{content_id}"
    video_data = video_info.get(key)
    if not isinstance(video_data, dict):
        return None

    author_data: dict | None = None
    for k, value in video_info.items():
        if k.startswith("VisionVideoDetailAuthor:"):
            author_data = value if isinstance(value, dict) else None
            break

    video_url = ""
    if content_type == "long-video":
        manifest_h265 = video_data.get("manifestH265")
        manifest_h265 = manifest_h265 if isinstance(manifest_h265, dict) else {}
        manifest_json = manifest_h265.get("json")
        manifest_json = manifest_json if isinstance(manifest_json, dict) else {}
        adaptation_set = manifest_json.get("adaptationSet") or []
        if isinstance(adaptation_set, list) and adaptation_set and isinstance(adaptation_set[0], dict):
            representation = adaptation_set[0].get("representation") or []
            if isinstance(representation, list) and representation and isinstance(representation[0], dict):
                backup_url = representation[0].get("backupUrl") or []
                if isinstance(backup_url, list) and backup_url:
                    video_url = backup_url[0] or ""
    else:
        video_url = video_data.get("photoUrl") or ""
    if not video_url:
        return None

    author = author_data or {}
    return {
        "title": str(video_data.get("caption") or ""),
        "author": str(author.get("name") or ""),
        "cover": str(video_data.get("coverUrl") or ""),
        "url": video_url,
        "type": "image" if content_type == "photo" else "video",
        "images": [],
        "music": None,
    }


async def parse(url: str) -> dict:
    """解析快手链接，返回统一结构；失败抛 RuntimeError（中文信息）。"""
    cleaned_url = _clean_url_tail(_extract_kuaishou_url(url))
    if not cleaned_url:
        raise RuntimeError("url为空")
    try:
        redirect_url = await _get_redirected_url(cleaned_url)
        if not redirect_url:
            raise RuntimeError("无法获取有效链接")
        page_content = await _curl_request(redirect_url)
        if not page_content:
            raise RuntimeError("页面内容获取失败")
        content_type, content_id = _extract_content_id_and_type(redirect_url)
        if not content_id:
            raise RuntimeError("无法识别的链接类型")
        result = _parse_init_state(page_content)
        if not result:
            result = _parse_apollo_state(page_content, content_id, content_type)
        if result:
            return result
        raise RuntimeError("未找到有效媒体信息")
    except RuntimeError:
        raise
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"快手解析失败: {e}") from e
