"""HTML 渲染封装。

对应原 index.mjs 的 puppeteer（L7475）、renderHtmlWithCompat（L7627）、
buildSimpleFortuneHtml（L7646）。默认使用 AstrBot Star 内置 html_render()
（内部 Playwright + Jinja2），不再依赖外部 Puppeteer 服务；
保留 render_api_base 配置以兼容原外部渲染服务协议。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import aiohttp
from astrbot.api import logger


class Renderer:
    """模板渲染器，挂载在 Star 实例上。模板位于 data_path/templates/。"""

    def __init__(self, star: Any) -> None:
        self.star = star
        self._cache: dict[str, str] = {}

    def template_path(self, name: str) -> Path:
        return self.star.data_path / "templates" / name

    def load_template(self, name: str) -> str:
        """读取模板文本（带缓存；模板随插件分发，首启由 main 复制到 plugin_data）。"""
        if name not in self._cache:
            self._cache[name] = self.template_path(name).read_text(encoding="utf-8")
        return self._cache[name]

    async def render_html(self, template: str, data: dict, width: int = 750) -> str:
        """渲染模板为图片 URL。

        :raises Exception: 渲染失败时抛出，由调用方回退文本。
        """
        if self.star.config.get("render_api_base"):
            return await self._render_remote(template, data, width)
        tmpl = self.load_template(template)
        return await self.star.html_render(
            tmpl,
            data,
            options={"type": "png", "full_page": True, "animations": "disabled"},
        )

    async def render_simple(self, title: str, lines: list) -> str:
        """简易文本兜底卡片（原 buildSimpleFortuneHtml）。"""
        body = "".join(f"<p style='margin:8px 0;font-size:26px;'>{l}</p>" for l in lines)
        html = (
            "<div style='padding:44px;color:#333;background:linear-gradient(135deg,#fdf6e3,#eee8d5);"
            "border-radius:26px;font-family:sans-serif;'>"
            f"<h1 style='margin-bottom:22px;font-size:34px;'>{title}</h1>{body}</div>"
        )
        return await self.star.html_render(html, {}, options={"type": "png", "full_page": True})

    async def _render_remote(self, template: str, data: dict, width: int) -> str:
        """兼容原外部 Puppeteer 服务协议（napcat-plugin-puppeteer /api/render）。"""
        base = str(self.star.config.get("render_api_base", "")).rstrip("/")
        if not base:
            raise RuntimeError("render_api_base 未配置")
        payload = {
            "html": self.load_template(template),
            "data": data,
            "setViewport": {"width": width, "height": 1080},
            "waitForTimeout": 0,
            "waitForSelector": "",
            "pageGotoParams": {},
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base}/plugin/napcat-plugin-puppeteer/api/render",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=40),
            ) as resp:
                res = await resp.json()
        img = (res or {}).get("data") or (res or {}).get("result", {}).get("data")
        if not img:
            raise RuntimeError("外部渲染服务未返回图片")
        return img if str(img).startswith("data:") else f"data:image/png;base64,{img}"
