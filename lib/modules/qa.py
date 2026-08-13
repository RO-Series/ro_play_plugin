"""问答系统模块（QaModule）。

对应原 index.mjs 的以下功能：
- 指令侧：L15107「(添加|删除|清空)(精准|模糊)问答#问题#答案」、
  L15165「问答词列表 / 详细问答词列表」（原 sendForward 三条节点）。
- 被动侧：L17862「([\\s\\S]*)」全消息匹配——精准 = 消息全等，
  模糊 = 关键词 includes 包含匹配，首个命中即回复。
- 图片支持：答案中的 [CQ:image,...] 被剥离后下载到
  BaiXuan/扩展功能/问答系统/图片数据/{随机}.png，以 [img:xxx.png] 占位存储；
  回复 / 详细列表时把 [img:xxx.png] 还原为本地 file:/// CQ 码。

命名替换：路径前缀「筱筱吖」→「BaiXuan」。
数据：BaiXuan/扩展功能/问答系统/{群号}/精准.json、模糊.json
（均为 {问题: 答案} 字典）。
"""
from __future__ import annotations

import random
import re
from typing import Any, Optional

import aiohttp
from astrbot.api import logger
import astrbot.api.message_components as Comp  # noqa: F401

from lib.cqcode import cq_image, give_images

IMG_PLACEHOLDER_RE = re.compile(r"\[img:([^\]]+)\]")
CQ_IMG_STRIP_RE = re.compile(r"\[CQ:image,file=([^,\]]+)[^\]]*\]")
_QA_DIR = "BaiXuan/扩展功能/问答系统"
_IMG_DIR = f"{_QA_DIR}/图片数据"


class QaModule:
    """问答系统：精准 / 模糊问答的增删查与被动回复。"""

    def __init__(self, star) -> None:
        self.star = star
        self.store = star.store

    # ==================== 工具 ====================

    def _rel(self, gid: str, kind: str) -> str:
        """精准/模糊数据文件相对路径。"""
        return f"{_QA_DIR}/{gid}/{kind}.json"

    async def _is_admin(self, event) -> bool:
        """原 checkOwner3（主人 或 管理模式群内群管理）。"""
        try:
            return await self.star.perm.check_admin(event)
        except Exception as e:  # noqa: BLE001
            logger.error(f"问答权限检查失败: {e}")
            return False

    async def _download_image(self, url: str, save_rel: str) -> bool:
        """用 aiohttp 下载图片（15s 超时），返回是否成功。"""
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return False
                    data = await resp.read()
            if not data:
                return False
            import aiofiles

            p = (self.star.data_path / save_rel).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(p, "wb") as f:
                await f.write(data)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"问答图片下载失败 {url}: {e}")
            return False

    def _restore_images(self, answer: str) -> str:
        """把 [img:xxx.png] 占位还原为本地 file:/// CQ 图片码。"""
        def _repl(m: re.Match) -> str:
            filename = m.group(1)
            p = self.star.data_path / _IMG_DIR / filename
            return cq_image(p.as_uri())
        return IMG_PLACEHOLDER_RE.sub(_repl, answer)

    async def _add(self, event, kind: str, args: str) -> Optional[str]:
        """添加精准/模糊问答（原「添加X问答#问题#答案」）。"""
        if not await self._is_admin(event):
            return "你没有权限使用此指令哦～"
        parts = (args or "").split("#", 1)
        question = (parts[0] or "").strip()
        answer = parts[1].strip() if len(parts) > 1 else ""
        if not question or not answer:
            return "必填参数缺失！格式：#问题#答案"
        gid = str(event.get_group_id() or "")
        if not gid:
            return "请在群聊中使用～"
        rel = self._rel(gid, kind)
        data = await self.store.read_json(rel, {}) or {}
        if question in data:
            return f"【{kind}问答】中已存在该词语啦～！如需修改请先删除哦～"
        # 提取消息内的图片（含 CQ 码与消息段两种来源）
        image_urls = give_images(answer)
        text = CQ_IMG_STRIP_RE.sub("", answer)
        # 消息段中的图片（AstrBot 组件）
        try:
            for seg in getattr(event, "message", None) or []:
                url = getattr(seg, "url", None) or getattr(seg, "file", None)
                if url and str(url).startswith(("http://", "https://")):
                    image_urls.append(str(url))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"读取问答图片段失败: {e}")
        written = text
        for url in image_urls:
            name = f"{random.randint(10000, 99999)}.png"
            if await self._download_image(url, f"{_IMG_DIR}/{name}"):
                written += f"[img:{name}]"
        data[question] = written
        await self.store.write_json(rel, data)
        show = self._restore_images(written)
        return f"已新增【{kind}问答】\n问:{question}\n答:{show}"

    async def _del(self, event, kind: str, args: str) -> Optional[str]:
        """删除精准/模糊问答（原「删除X问答#问题」）。"""
        if not await self._is_admin(event):
            return "你没有权限使用此指令哦～"
        question = (args or "").strip()
        if not question:
            return "必填参数缺失！格式：#问题"
        gid = str(event.get_group_id() or "")
        if not gid:
            return "请在群聊中使用～"
        rel = self._rel(gid, kind)
        if not await self.store.has_key(rel, question):
            return "好像木有这个哎～要不你仔细看看列表？"
        await self.store.delete_key(rel, question)
        return f"好哒！这就去把【{kind}问答】的「{question}」这个原值删除！"

    async def _clear(self, event, kind: str) -> Optional[str]:
        """清空精准/模糊问答（原「清空X问答」）。"""
        if not await self._is_admin(event):
            return "你没有权限使用此指令哦～"
        gid = str(event.get_group_id() or "")
        if not gid:
            return "请在群聊中使用～"
        await self.store.write_json(self._rel(gid, kind), {})
        return f"这就把【{kind}问答】的词语通通清空！"

    # ==================== 指令方法（main.py 调用） ====================

    async def add_exact(self, event, args: str = "") -> Any:
        """添加精准问答：/添加精准问答 #问题 #答案"""
        try:
            return await self._add(event, "精准", args)
        except Exception as e:  # noqa: BLE001
            logger.error(f"添加精准问答失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    async def del_exact(self, event, args: str = "") -> Any:
        """删除精准问答：/删除精准问答 #问题"""
        try:
            return await self._del(event, "精准", args)
        except Exception as e:  # noqa: BLE001
            logger.error(f"删除精准问答失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    async def add_fuzzy(self, event, args: str = "") -> Any:
        """添加模糊问答：/添加模糊问答 #关键词 #答案"""
        try:
            return await self._add(event, "模糊", args)
        except Exception as e:  # noqa: BLE001
            logger.error(f"添加模糊问答失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    async def del_fuzzy(self, event, args: str = "") -> Any:
        """删除模糊问答：/删除模糊问答 #关键词"""
        try:
            return await self._del(event, "模糊", args)
        except Exception as e:  # noqa: BLE001
            logger.error(f"删除模糊问答失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    async def list(self, event, detailed: bool = False) -> Any:
        """问答词列表 / 详细问答词列表（原 L15165）。"""
        try:
            gid = str(event.get_group_id() or "")
            if not gid:
                return "请在群聊中使用～"
            exact = await self.store.read_json(self._rel(gid, "精准"), {}) or {}
            fuzzy = await self.store.read_json(self._rel(gid, "模糊"), {}) or {}
            if not exact and not fuzzy:
                return "好像木有过数据哎～无论是【精准】还是【模糊】我都没找到唉～～"
            lines1: list[str] = [f"精准问答 :【{len(exact)}】个", "══════════════"]
            for i, (q, a) in enumerate(exact.items(), 1):
                ans = self._restore_images(str(a)) if detailed else str(a)
                lines1.append(f"{i}. [{q}] → {ans}")
                lines1.append("----------------------" if i != len(exact) else "══════════════")
            lines2: list[str] = [f"模糊问答 :【{len(fuzzy)}】个", "══════════════"]
            for i, (q, a) in enumerate(fuzzy.items(), 1):
                ans = self._restore_images(str(a)) if detailed else str(a)
                lines2.append(f"{i}. [{q}] → {ans}")
                lines2.append("----------------------" if i != len(fuzzy) else "══════════════")
            head = [
                "══════════════",
                "删除时请删除「问题」参数",
                "也就是[]里面的，就“→”之前的",
                "══════════════",
            ]
            blocks = [head, lines1, lines2]
            nodes = [
                self.star.sender.build_node("[问答系统]", event.get_sender_id(), "\n".join(b))
                for b in blocks
            ]
            if (len(exact) + len(fuzzy)) >= 15:
                await self.star.sender.send_forward(event, nodes)
                return None
            return "\n".join(lines1 + lines2)
        except Exception as e:  # noqa: BLE001
            logger.error(f"问答词列表失败: {e}")
            return f"指令执行出错：{type(e).__name__}: {e}"

    # ==================== 被动回复 ====================

    async def on_message(self, event) -> None:
        """被动：精准=消息全等，模糊=includes 包含匹配，首个命中回复。"""
        try:
            gid = str(event.get_group_id() or "")
            if not gid:
                return
            message = (event.message_str or "").strip()
            if not message:
                return
            exact = await self.store.read_json(self._rel(gid, "精准"), {}) or {}
            fuzzy = await self.store.read_json(self._rel(gid, "模糊"), {}) or {}
            answer: Optional[str] = None
            if message in exact:
                answer = str(exact[message])
            else:
                for keyword, ans in (fuzzy or {}).items():
                    if keyword and message.__contains__(str(keyword)):
                        answer = str(ans)
                        break
            if answer is None:
                return
            content = self._restore_images(answer)
            await self.star.sender.send_reply(event, content)
        except Exception as e:  # noqa: BLE001
            logger.error(f"问答被动回复失败: {e}")

    # ==================== 无前缀 legacy ====================

    async def legacy(self, event, message: str) -> Any:
        """正则匹配无前缀指令（原 L15107/L15165）。"""
        try:
            m = re.match(r"^(添加|删除|清空)(精准|模糊)问答(?:#(.+?)(?:#(.+))?)?$", message)
            if m:
                operation, kind, q, ans = m.group(1), m.group(2), m.group(3) or "", m.group(4) or ""
                if operation == "添加":
                    if q and ans:
                        return await self._add(event, kind, f"{q}#{ans}")
                    return "必填参数缺失！格式：添加精准问答#问题#答案"
                if operation == "删除":
                    return await self._del(event, kind, q)
                if operation == "清空":
                    return await self._clear(event, kind)
                return None
            m2 = re.match(r"^(问答词列表|详细问答词列表)$", message)
            if m2:
                return await self.list(event, detailed=m2.group(1) == "详细问答词列表")
        except Exception as e:  # noqa: BLE001
            logger.error(f"问答 legacy 异常: {e}")
        return None
