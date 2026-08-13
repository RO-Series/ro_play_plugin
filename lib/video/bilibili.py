from __future__ import annotations

import json
import re
from typing import Any

from . import DEFAULT_USER_AGENT, _fetch_text, _follow_redirect

__all__ = ["parse"]

_B23_RE = re.compile(r"https?://b23\.tv/[a-zA-Z0-9]+", re.IGNORECASE)
_BV_RE = re.compile(r"BV[a-zA-Z0-9]{10}", re.IGNORECASE)

def _first_dict_item(data: Any, key: str) -> dict:

    if isinstance(data, dict):
        value = data.get(key)
        if isinstance(value, dict):
            return value
    return {}

async def parse(url: str) -> dict:

    raw = (url or "").strip()
    if not raw:
        raise RuntimeError("参数为空，请输入 B 站链接或 BV 号")

    short_match = _B23_RE.search(raw)
    bv_match = _BV_RE.search(raw)
    bvid: str | None = None
    try:
        if short_match:
            final_url = await _follow_redirect(short_match.group(0), DEFAULT_USER_AGENT)
            redirected_bv = _BV_RE.search(final_url)
            if redirected_bv:
                bvid = redirected_bv.group(0)
            elif bv_match:
                bvid = bv_match.group(0)
        else:
            if bv_match:
                bvid = bv_match.group(0)
    except Exception as e:
        raise RuntimeError(f"B 站链接跳转失败: {e}") from e

    if not bvid:
        raise RuntimeError("未找到 b23.tv 短链接或 BV 号")

    try:
        view_raw = await _fetch_text(
            f"https://api.bilibili.com/x/web-interface/wbi/view?bvid={bvid}"
        )
        view_data: Any = json.loads(view_raw)
    except Exception as e:
        raise RuntimeError(f"获取 B 站视频信息失败: {e}") from e
    if not isinstance(view_data, dict) or view_data.get("code") != 0:
        raise RuntimeError("获取视频信息失败")
    info = view_data.get("data")
    if not isinstance(info, dict):
        raise RuntimeError("获取视频信息失败")
    cid = info.get("cid")
    if not cid:
        raise RuntimeError("获取视频信息失败：缺少 cid")

    play_url = (
        "https://api.bilibili.com/x/player/wbi/playurl"
        f"?gaia_source=view-card&fnval=4048&platform=html5&bvid={bvid}&cid={cid}"
    )
    try:
        play_raw = await _fetch_text(play_url)
        play_data: Any = json.loads(play_raw)
    except Exception as e:
        raise RuntimeError(f"获取播放地址失败: {e}") from e
    if not isinstance(play_data, dict) or play_data.get("code") != 0:
        raise RuntimeError("获取播放地址失败")
    pdata = play_data.get("data")
    if not isinstance(pdata, dict):
        raise RuntimeError("获取播放地址失败")

    video_url = ""
    durl = pdata.get("durl")
    if isinstance(durl, list) and durl and isinstance(durl[0], dict) and durl[0].get("url"):
        video_url = str(durl[0]["url"]).replace("\\", "")
    if not video_url:
        dash = pdata.get("dash")
        if isinstance(dash, dict):
            video_list = dash.get("video")
            if isinstance(video_list, list) and video_list and isinstance(video_list[0], dict):
                video_url = (
                    video_list[0].get("baseUrl")
                    or video_list[0].get("base_url")
                    or ""
                )
                video_url = str(video_url).replace("\\", "")
    if not video_url:
        raise RuntimeError("获取播放地址失败")

    owner = _first_dict_item(info, "owner")
    return {
        "title": str(info.get("title") or ""),
        "author": str(owner.get("name") or ""),
        "cover": str(info.get("pic") or ""),
        "url": video_url,
        "type": "video",
        "images": [],
        "music": None,
    }
