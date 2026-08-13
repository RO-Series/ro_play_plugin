from __future__ import annotations

import re
from typing import Any

import aiohttp

__all__ = ["match_platform", "parse"]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 15

_session: aiohttp.ClientSession | None = None

_TAG_RE = re.compile(r"<[^>]*>")
_TAIL_RE = re.compile(r"[^\w\-./?=&:#]+$")

def _strip_tags(text: str) -> str:

    return _TAG_RE.sub("", text)

def _clean_url_tail(url: str) -> str:

    return _TAIL_RE.sub("", url)

def _decode_bytes(raw: bytes) -> str:

    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")

def _get_session() -> aiohttp.ClientSession:

    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        )
    return _session

async def _close_session() -> None:

    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None

async def _fetch_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    allow_redirects: bool = True,
) -> str:

    request_headers: dict[str, str] = {"User-Agent": user_agent}
    if headers:
        request_headers.update(headers)
    try:
        async with _get_session().get(
            url, headers=request_headers, allow_redirects=allow_redirects
        ) as resp:
            if not (200 <= resp.status < 300):
                raise RuntimeError(f"HTTP {resp.status}")
            raw = await resp.read()
            return _decode_bytes(raw)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"请求失败（{url}）: {e}") from e

async def _follow_redirect(url: str, user_agent: str = DEFAULT_USER_AGENT) -> str:

    try:
        async with _get_session().get(
            url, headers={"User-Agent": user_agent}, allow_redirects=True
        ) as resp:
            return str(resp.url)
    except Exception:
        return url

async def _get_location(url: str, user_agent: str = DEFAULT_USER_AGENT) -> str | None:

    try:
        async with _get_session().get(
            url, headers={"User-Agent": user_agent}, allow_redirects=False
        ) as resp:
            return resp.headers.get("Location")
    except Exception:
        return None

def _extract_balanced_json(html: str, marker: str) -> str | None:

    start = html.find(marker)
    if start < 0:
        return None
    eq = html.find("=", start)
    if eq < 0:
        return None
    brace = html.find("{", eq)
    if brace < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    quote = ""
    i = brace
    while i < len(html):
        ch = html[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                in_string = False
            i += 1
            continue
        if ch in ('"', "'"):
            in_string = True
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return html[brace : i + 1]
        i += 1
    return None

_PLATFORM_PATTERNS: list[tuple[str, str]] = [
    ("bilibili", r"https?://b23\.tv/[a-zA-Z0-9]+"),
    ("bilibili", r"https?://[^\s\u4e00-\u9fff]*bilibili\.com/[^\s\u4e00-\u9fff]*"),
    ("douyin", r"https?://v\.douyin\.com/[a-zA-Z0-9_-]+[^\s\u4e00-\u9fff]*"),
    ("douyin", r"https?://[^\s\u4e00-\u9fff]*douyin\.com[^\s\u4e00-\u9fff]*"),
    ("xiaohongshu", r"https?://xhslink\.com/[a-zA-Z0-9]+"),
    ("xiaohongshu", r"https?://xhs\.com/[^\s\u4e00-\u9fff]*"),
    ("xiaohongshu", r"https?://[^\s\u4e00-\u9fff]*xiaohongshu\.com/[^\s\u4e00-\u9fff]*"),
    ("kuaishou", r"https?://v\.kuaishou\.com/[a-zA-Z0-9_-]+[^\s\u4e00-\u9fff]*"),
    ("kuaishou", r"https?://[^\s\u4e00-\u9fff]*kuaishou\.com[^\s\u4e00-\u9fff]*"),

    ("bilibili", r"(?<![a-zA-Z0-9])BV[a-zA-Z0-9]{10}"),
]

def _match(text: str) -> tuple[str, str] | None:

    cleaned = _strip_tags(text or "")
    for platform, pattern in _PLATFORM_PATTERNS:
        matched = re.search(pattern, cleaned, re.IGNORECASE)
        if matched:
            return platform, _clean_url_tail(matched.group(0).strip())
    return None

def match_platform(text: str) -> str | None:

    result = _match(text)
    return result[1] if result else None

async def parse(text: str) -> dict:

    result = _match(text)
    if result is None:
        raise RuntimeError("未识别到支持的视频平台链接（支持 B站/抖音/小红书/快手）")
    platform, url = result
    if platform == "bilibili":
        from .bilibili import parse as _platform_parse
    elif platform == "douyin":
        from .douyin import parse as _platform_parse
    elif platform == "xiaohongshu":
        from .xiaohongshu import parse as _platform_parse
    else:
        from .kuaishou import parse as _platform_parse
    return await _platform_parse(url)
