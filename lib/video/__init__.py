"""视频解析模块（MKbot 迁移）。

对应原 MKbot 2.3.4（napcat-plugin-mkbot）lib/api/ 下 4 个视频解析 JS 模块的 Python 重写，
将 blbl.mjs / dy.mjs / xhs.mjs / ks.mjs 的算法（解短链 -> 抓页面内嵌状态
RENDER_DATA / __INITIAL_STATE__ / INIT_STATE / WBI -> 提取直链/图片）原样移植。

本模块对外提供两个入口：
- match_platform(text): 按 b23.tv/bilibili -> v.douyin -> xhslink/xiaohongshu -> v.kuaishou
  的优先级用正则提取链接，返回清洗后的 URL（无法识别返回 None）。
- parse(text): 识别平台后分发到对应子模块解析，统一返回
  {"title": str, "author": str, "cover": str, "url": str,
   "type": "video|image|live", "images": list, "music": dict | None}。
"""
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
    """去除 HTML 标签（对应原 JS stripTags）。"""
    return _TAG_RE.sub("", text)


def _clean_url_tail(url: str) -> str:
    """去掉链接尾部多余标点/非法字符（对应原 JS cleanUrlTail）。"""
    return _TAIL_RE.sub("", url)


def _decode_bytes(raw: bytes) -> str:
    """响应字节解码：优先 utf-8，解码失败回退 gbk（抖音等页面编码场景）。"""
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _get_session() -> aiohttp.ClientSession:
    """获取全局共享 aiohttp 会话（超时 15s，懒创建）。"""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        )
    return _session


async def _close_session() -> None:
    """关闭共享会话（供插件卸载时清理，非必须调用）。"""
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
    """GET 请求并返回解码后的文本。

    异常统一捕获并抛 RuntimeError（携带中文信息）；allow_redirects 控制是否跟随重定向。
    """
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
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"请求失败（{url}）: {e}") from e


async def _follow_redirect(url: str, user_agent: str = DEFAULT_USER_AGENT) -> str:
    """跟随重定向并返回最终 URL（对应原 JS followRedirect）。"""
    try:
        async with _get_session().get(
            url, headers={"User-Agent": user_agent}, allow_redirects=True
        ) as resp:
            return str(resp.url)
    except Exception:  # noqa: BLE001
        return url


async def _get_location(url: str, user_agent: str = DEFAULT_USER_AGENT) -> str | None:
    """发起不跟随重定向的 GET，返回 Location 头（对应原 JS redirect: "manual" 分支）。"""
    try:
        async with _get_session().get(
            url, headers={"User-Agent": user_agent}, allow_redirects=False
        ) as resp:
            return resp.headers.get("Location")
    except Exception:  # noqa: BLE001
        return None


def _extract_balanced_json(html: str, marker: str) -> str | None:
    """从 marker 后第一个 '{' 起做括号配平，取出完整 JSON 字面量。

    兼容字符串内括号（双引号/单引号、转义），对应原 JS extractBalancedJsonFrom。
    """
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


# 平台优先级：bilibili -> douyin -> xiaohongshu -> kuaishou
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
    # 末尾兜底：纯文本中的裸 BV 号（置于所有 URL 模式之后，避免抢占 URL 平台优先级）
    ("bilibili", r"(?<![a-zA-Z0-9])BV[a-zA-Z0-9]{10}"),
]


def _match(text: str) -> tuple[str, str] | None:
    """按优先级匹配平台，返回 (平台名, 清洗后链接)；无法识别返回 None。"""
    cleaned = _strip_tags(text or "")
    for platform, pattern in _PLATFORM_PATTERNS:
        matched = re.search(pattern, cleaned, re.IGNORECASE)
        if matched:
            return platform, _clean_url_tail(matched.group(0).strip())
    return None


def match_platform(text: str) -> str | None:
    """按 b23.tv/bilibili -> v.douyin -> xhslink/xiaohongshu -> v.kuaishou 优先级提取链接。

    返回清洗后的 URL（去掉尾部标点）；无法识别时返回 None。
    """
    result = _match(text)
    return result[1] if result else None


async def parse(text: str) -> dict:
    """识别平台并分发到对应模块解析，统一返回结构：

    {"title": str, "author": str, "cover": str, "url": str,
     "type": "video|image|live", "images": list, "music": dict | None}

    解析失败抛出 RuntimeError（中文信息）。
    """
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
