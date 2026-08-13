"""伪造聊天模块（FakeChatModule）。

对应原 index.mjs 的以下功能：
- L13198「(开启|关闭)伪造声明」。
- L13223「伪造聊天[JSON]」（含独立 JSON 数组直发）：
  解析 JSON 数组（text/face/mface/image/video 段 + CQ 码 + 嵌套 forward），
  声明开启时插入声明节点，媒体按「图片 25s / 视频 35s / 整批 600s」超时预算
  用 aiohttp 下载到 star.data_path 下的临时目录，最后合并转发展送。
- 表情点赞回执（set_msg_emoji_like）在 AstrBot 平台不可用时安全跳过。

数据：BaiXuan/伪造聊天/{群号}/声明.json（{"开关": "开启"}）。

命名替换：路径前缀「筱筱吖」→「BaiXuan」，MKbot → RO_Play。
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Any, Optional

import aiohttp
from astrbot.api import logger
import astrbot.api.message_components as Comp

_IMG_TIMEOUT_SEC = 25
_VIDEO_TIMEOUT_SEC = 35
_BATCH_MAX_SEC = 600
_CLASSIC_FACE_ID_MAX = 103
_TMP_REL = "临时目录"
_DECLARE_REL = "BaiXuan/伪造聊天"


class FakeChatModule:
    """伪造聊天：解析 JSON 构造合并转发。"""

    def __init__(self, star) -> None:
        self.star = star
        self.store = star.store

    # ==================== 工具 ====================

    @staticmethod
    def _is_http(url: Any) -> bool:
        return isinstance(url, str) and re.match(r"^https?://", url, re.I) is not None

    def _tmp_dir(self) -> Path:
        d = self.star.data_path / _TMP_REL
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _ext_from_url(url: str, fallback: str) -> str:
        try:
            from urllib.parse import urlparse
            ext = Path(urlparse(url).path).suffix
            return ext or fallback
        except Exception:  # noqa: BLE001
            return fallback

    async def _download_media(self, url: str, kind: str, batch_start: float, batch_budget: float) -> Optional[Path]:
        """按超时预算下载媒体，成功返回本地路径。"""
        remaining = batch_budget - (time.time() - batch_start)
        if remaining <= 0:
            return None
        per_link = _IMG_TIMEOUT_SEC if kind == "image" else _VIDEO_TIMEOUT_SEC
        timeout = aiohttp.ClientTimeout(total=max(1, min(per_link, remaining)))
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.read()
            if not data:
                return None
            ext = self._ext_from_url(url, ".png" if kind == "image" else ".mp4")
            name = f"{random.randint(10000000, 99999999)}{ext}"
            p = self._tmp_dir() / name
            import aiofiles

            async with aiofiles.open(p, "wb") as f:
                await f.write(data)
            return p
        except Exception as e:  # noqa: BLE001
            logger.warning(f"伪造聊天媒体下载失败 {url}: {e}")
            return None

    def _seg_text(self, value: Any) -> list:
        """text 段：普通文本或含 CQ 码时经 cq_to_chain 拆分。"""
        text = str(value or "")
        if "[CQ:" in text:
            try:
                from lib.sender import cq_to_chain
                return cq_to_chain(text) or [Comp.Plain(text)]
            except Exception as e:  # noqa: BLE001
                logger.warning(f"CQ 文本解析失败: {e}")
        return [Comp.Plain(text)]

    def _seg_face(self, value: Any, index: int, seg_index: int) -> Any:
        id_str = str(value or "").strip()
        if not re.fullmatch(r"\d+", id_str):
            return f"第 {index + 1} 条第 {seg_index + 1} 段：face 的 data 须为数字 ID"
        if int(id_str) < 0 or int(id_str) > _CLASSIC_FACE_ID_MAX:
            return f"第 {index + 1} 条第 {seg_index + 1} 段：表情 ID {id_str} 超出经典表情范围 0-{_CLASSIC_FACE_ID_MAX}"
        return Comp.Face(id=id_str)

    async def _build_node(self, item: Any, index: int, batch_start: float, batch_budget: float) -> Any:
        """把单条 JSON 消息解析为 {name, qq, content: chain, extra: [nodes]}。"""
        if not isinstance(item, dict):
            return f"第 {index + 1} 条消息格式无效"
        name = str(item.get("name") or "").strip()
        qq = str(item.get("qq") or "").strip()
        data = item.get("data")
        if not name:
            return f"第 {index + 1} 条缺少 name"
        if not qq:
            return f"第 {index + 1} 条缺少 qq"
        if not isinstance(data, list) or not data:
            return f"第 {index + 1} 条 data 不能为空数组"
        types = [str(s.get("type", "") if isinstance(s, dict) else "").lower() for s in data]
        if "video" in types and len(data) != 1:
            return f"第 {index + 1} 条：视频仅支持单独一个子消息，不可与文本/表情/图片混用"
        chain: list = []
        extra_nodes: list = []
        for j, seg in enumerate(data):
            if not isinstance(seg, dict):
                return f"第 {index + 1} 条第 {j + 1} 段：段格式无效"
            stype = str(seg.get("type") or "").lower()
            sval = seg.get("data")
            if stype == "text":
                chain += self._seg_text(sval)
            elif stype == "face":
                built = self._seg_face(sval, index, j)
                if isinstance(built, str):
                    return built
                chain.append(built)
            elif stype == "mface":
                built = self._seg_mface(sval, index, j)
                if isinstance(built, str):
                    return built
                chain.append(built)
            elif stype == "image":
                built = await self._seg_media(sval, "image", index, j, batch_start, batch_budget)
                if isinstance(built, str):
                    return built
                chain.append(built)
            elif stype == "video":
                built = await self._seg_media(sval, "video", index, j, batch_start, batch_budget)
                if isinstance(built, str):
                    return built
                chain.append(built)
            elif stype == "forward":
                extra = await self._seg_forward(sval, batch_start, batch_budget)
                if isinstance(extra, str):
                    return extra
                extra_nodes += extra
            else:
                return f"第 {index + 1} 条第 {j + 1} 段：不支持的类型「{stype or '未知'}」"
        if not chain and not extra_nodes:
            return f"第 {index + 1} 条未解析出有效内容"
        return {"name": name, "qq": qq, "content": chain, "extra": extra_nodes}

    def _seg_mface(self, value: Any, index: int, seg_index: int) -> Any:
        if not isinstance(value, dict):
            return f"第 {index + 1} 条第 {seg_index + 1} 段：mface 的 data 须为对象"
        emoji_id = str(value.get("emoji_id") or "").strip()
        pkg = str(value.get("emoji_package_id") or "").strip()
        key = str(value.get("key") or "").strip()
        if not emoji_id or not pkg or not key:
            return f"第 {index + 1} 条第 {seg_index + 1} 段：mface 缺少 emoji_id / emoji_package_id / key"
        mface_cls = getattr(Comp, "Mface", None)
        if mface_cls is None:
            return f"第 {index + 1} 条第 {seg_index + 1} 段：当前 AstrBot 版本不支持 mface 段"
        return mface_cls(emoji_id=emoji_id, emoji_package_id=pkg, key=key,
                         summary=str(value.get("summary") or ""))

    async def _seg_media(self, value: Any, kind: str, index: int, seg_index: int,
                         batch_start: float, batch_budget: float) -> Any:
        url = str(value or "").strip()
        if not url:
            return f"第 {index + 1} 条第 {seg_index + 1} 段：{'图片' if kind == 'image' else '视频'}链接不能为空"
        if self._is_http(url):
            p = await self._download_media(url, kind, batch_start, batch_budget)
            if p is None:
                return f"第 {index + 1} 条{'图片' if kind == 'image' else '视频'}下载失败或超时，请确认链接可访问且为直链"
            uri = p.as_uri()
            return Comp.Image.fromURL(uri) if kind == "image" else Comp.Video.fromURL(uri)
        if url.startswith("file:") or Path(url).is_absolute():
            return Comp.Image.fromURL(url) if kind == "image" else Comp.Video.fromURL(url)
        return f"第 {index + 1} 条第 {seg_index + 1} 段：须为有效的 http(s) 链接或本地路径"

    async def _seg_forward(self, value: Any, batch_start: float, batch_budget: float) -> Any:
        """嵌套 forward：展开为额外节点（content 内联或 get_forward_msg 拉取）。"""
        nodes: list = []
        if not isinstance(value, dict):
            return nodes
        content = value.get("content")
        if isinstance(content, list) and content:
            for i, sub in enumerate(content):
                built = await self._build_node(sub, i, batch_start, batch_budget)
                if isinstance(built, str):
                    logger.warning(f"嵌套转发节点解析失败: {built}")
                    continue
                nodes.append(self.star.sender.build_node(built["name"], built["qq"], built["content"]))
            return nodes
        fid = value.get("id")
        if fid:
            try:
                result = await self.star.api.call_result("get_forward_msg", id=str(fid))
                messages = self._normalize_forward(result)
                for i, sub in enumerate(messages):
                    node = self._ob_node_to_item(sub)
                    if node is None:
                        continue
                    built = await self._build_node(node, i, batch_start, batch_budget)
                    if isinstance(built, str):
                        continue
                    nodes.append(self.star.sender.build_node(built["name"], built["qq"], built["content"]))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"get_forward_msg 失败: {e}")
        return nodes

    @staticmethod
    def _normalize_forward(result: Any) -> list:
        if not isinstance(result, dict):
            return []
        data = result.get("data")
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            return data["messages"]
        if isinstance(data, list):
            return data
        return []

    @staticmethod
    def _ob_node_to_item(node: Any) -> Optional[dict]:
        """把 OneBot node 消息转为伪造聊天条目格式。"""
        if not isinstance(node, dict):
            return None
        if node.get("type") == "node":
            d = node.get("data") or {}
            name = str(d.get("name") or d.get("nickname") or "用户")
            uin = str(d.get("uin") or d.get("user_id") or "")
            content = d.get("content") or d.get("message") or []
        else:
            sender = node.get("sender") or {}
            name = str(sender.get("nickname") or sender.get("card") or "用户")
            uin = str(node.get("user_id") or sender.get("user_id") or "")
            content = node.get("message") or node.get("content") or []
        if not uin or not content:
            return None
        segs = []
        for c in content if isinstance(content, list) else []:
            if not isinstance(c, dict):
                continue
            t = str(c.get("type") or "").lower()
            d = c.get("data") or {}
            if t == "text":
                segs.append({"type": "text", "data": d.get("text", "")})
            elif t == "face":
                segs.append({"type": "face", "data": d.get("id", "0")})
            elif t == "image":
                segs.append({"type": "image", "data": d.get("url") or d.get("file") or ""})
            elif t == "video":
                segs.append({"type": "video", "data": d.get("url") or d.get("file") or ""})
            elif t == "forward":
                segs.append({"type": "forward", "data": d})
        if not segs:
            return None
        return {"name": name, "qq": uin, "data": segs}

    # ==================== 指令方法（main.py 调用） ====================

    async def fake(self, event, payload: str = "") -> Any:
        """伪造聊天：/伪造聊天 JSON数组（原 L13223）。"""
        try:
            gid = str(event.get_group_id() or "")
            if not gid:
                return "请在群聊中使用～"
            body = (payload or "").strip()
            if not body.startswith("["):
                body = self._extract_payload(event, body)
            if not body:
                return self._help_text()
            parsed = self._parse_json(body)
            if isinstance(parsed, str):
                return parsed
            nodes: list = []
            declare = await self.store.read_key(f"{_DECLARE_REL}/{gid}/声明.json", "开关", "开启")
            if str(declare) == "开启":
                text = "本功能由虚拟构造完成\n切勿相信！切勿迷信！\n本次执行人员:" + str(event.get_sender_id())
                nodes.append(self.star.sender.build_node("声明", 1001, text))
            batch_start = time.time()
            image_count, video_count = self._count_media(parsed)
            budget = min(
                image_count * _IMG_TIMEOUT_SEC + video_count * _VIDEO_TIMEOUT_SEC,
                _BATCH_MAX_SEC,
            )
            for i, item in enumerate(parsed):
                built = await self._build_node(item, i, batch_start, budget)
                if isinstance(built, str):
                    return built
                nodes.append(self.star.sender.build_node(built["name"], built["qq"], built["content"]))
                for extra in built["extra"]:
                    nodes.append(extra)
            if len(nodes) <= 1:
                return "未解析出有效内容～"
            ok = await self.star.sender.send_forward(event, nodes)
            if not ok:
                return "合并转发展送失败～"
            return None
        except Exception as e:  # noqa: BLE001
            logger.error(f"伪造聊天失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    def _extract_payload(self, event, body: str) -> str:
        """尝试从事件原文中提取「伪造聊天」后的 JSON。"""
        for src in (body, event.message_str or "", getattr(getattr(event, "message_obj", None), "raw_message", "") or ""):
            m = re.match(r"^伪造聊天([\s\S]*)$", str(src))
            if m:
                candidate = m.group(1).strip()
                if candidate.startswith("["):
                    return candidate
        return ""

    def _parse_json(self, body: str) -> Any:
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return "JSON 解析失败，请检查括号、引号与逗号是否正确"
        if not isinstance(parsed, list) or not parsed:
            return "根节点必须是包含至少一条消息的 JSON 数组"
        return parsed

    @staticmethod
    def _count_media(items: list) -> tuple:
        images = videos = 0
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            for seg in item.get("data", []) if isinstance(item.get("data"), list) else []:
                if not isinstance(seg, dict):
                    continue
                stype = str(seg.get("type") or "").lower()
                val = str(seg.get("data") or "").strip()
                if stype == "image" and re.match(r"^https?://", val, re.I):
                    images += 1
                elif stype == "video" and re.match(r"^https?://", val, re.I):
                    videos += 1
        return images, videos

    @staticmethod
    def _help_text() -> str:
        return (
            "══════════════\n"
            "【伪造聊天】JSON 格式\n"
            "相关事件【伪造聊天】\n"
            "开启|关闭伪造声明\n"
            "\n"
            "指令后紧跟 JSON 数组，例：\n"
            "伪造聊天 [{\"name\":\"BaiXuan\",\"qq\":\"864264375\",\"data\":[{\"type\":\"text\",\"data\":\"你好\"},{\"type\":\"face\",\"data\":\"14\"}]}]\n"
            "\n"
            "说明：\n"
            "· face 经典表情 ID：0-103\n"
            "· 商城表情用 mface，data 为对象\n"
            "· image/video 须填真实可访问的 http(s) 直链\n"
            "· video 每条消息仅允许单独一段\n"
            "· 支持嵌套 forward（data.content 为节点数组）\n"
            "══════════════"
        )

    # ==================== 无前缀 legacy ====================

    async def legacy(self, event, message: str) -> Any:
        """正则匹配无前缀伪造聊天指令（原 L13198/L13223）。"""
        try:
            gid = str(event.get_group_id() or "")
            if not gid:
                return None
            m = re.match(r"^(开启|关闭)伪造声明$", message)
            if m:
                if not await self.star.perm.check_admin(event):
                    return None
                operation = m.group(1)
                rel = f"{_DECLARE_REL}/{gid}/声明.json"
                cur = await self.store.read_key(rel, "开关", "开启")
                if cur == operation:
                    return f"好像也就是【{cur}】了唉～"
                await self.store.write_key(rel, "开关", operation)
                return f"好哒！这就把声明给【{operation}】！"
            if message.startswith("["):
                if self._is_json_array(message):
                    return await self.fake(event, message)
            m = re.match(r"^伪造聊天([\s\S]*)$", message)
            if m:
                return await self.fake(event, message)
        except Exception as e:  # noqa: BLE001
            logger.error(f"伪造聊天 legacy 异常: {e}")
        return None

    @staticmethod
    def _is_json_array(text: str) -> bool:
        try:
            return isinstance(json.loads(text), list)
        except (json.JSONDecodeError, ValueError):
            return False
