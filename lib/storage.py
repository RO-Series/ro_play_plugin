"""数据存储封装。

对应原 index.mjs 的 readA / readB / writeA / writeB / deleteKey / getKeys / clear，
由 Node 同步 fs 改写为异步 aiofiles 实现，并挂到 plugin_data 目录下。
所有相对路径禁止逃逸根目录；写盘采用临时文件 + 原子替换防止并发损坏。

存储根目录：Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_ro_play"
业务子路径沿用原结构，仅将路径前缀「筱筱吖」替换为「BaiXuan」。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiofiles


class DataStore:
    """以相对路径操作数据根目录下的 JSON / 文本文件。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, rel: str) -> asyncio.Lock:
        if rel not in self._locks:
            self._locks[rel] = asyncio.Lock()
        return self._locks[rel]

    def _path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError(f"非法相对路径: {rel}")
        return p

    # ---------- JSON 整体 ----------

    async def read_json(self, rel: str, default: Any = None) -> Any:
        """读取 JSON 文件，文件不存在或解析失败返回 default（原 readB 无键时的行为）。"""
        async with self._lock(rel):
            try:
                async with aiofiles.open(self._path(rel), "r", encoding="utf-8") as f:
                    return json.loads(await f.read())
            except (FileNotFoundError, json.JSONDecodeError, ValueError):
                return default

    async def write_json(self, rel: str, data: Any) -> None:
        """整体写 JSON 文件（临时文件 + 原子替换）。"""
        async with self._lock(rel):
            p = self._path(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".tmp")
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
            tmp.replace(p)

    # ---------- JSON 键值 ----------

    async def read_key(self, rel: str, key: str, default: Any = None) -> Any:
        """读取 JSON 文件中的单个键（原 readB）。"""
        data = await self.read_json(rel, None)
        if isinstance(data, dict):
            return data.get(key, default)
        return default

    async def write_key(self, rel: str, key: str, value: Any) -> None:
        """写入 JSON 文件中的单个键，自动合并旧数据（原 writeB）。"""
        data = await self.read_json(rel, {})
        if not isinstance(data, dict):
            data = {}
        data[key] = value
        await self.write_json(rel, data)

    async def delete_key(self, rel: str, key: str) -> None:
        """删除 JSON 文件中的单个键（原 deleteKey）。"""
        data = await self.read_json(rel, {})
        if isinstance(data, dict) and key in data:
            del data[key]
            await self.write_json(rel, data)

    async def has_key(self, rel: str, key: str) -> bool:
        """判断键是否存在（原 hasKey）。"""
        data = await self.read_json(rel, {})
        return isinstance(data, dict) and key in data

    async def get_keys(self, rel: str) -> list:
        """获取 JSON 文件全部键（原 getKeys）。"""
        data = await self.read_json(rel, {})
        return list(data.keys()) if isinstance(data, dict) else []

    async def clear(self, rel: str) -> None:
        """清空 JSON 文件为 {}（原 clear）。"""
        await self.write_json(rel, {})

    # ---------- 文本 ----------

    async def read_text(self, rel: str, default: str = "") -> str:
        """读取文本文件（原 readA），不存在返回 default。"""
        async with self._lock(rel):
            try:
                async with aiofiles.open(self._path(rel), "r", encoding="utf-8") as f:
                    return await f.read()
            except FileNotFoundError:
                return default

    async def write_text(self, rel: str, text: str) -> None:
        """写入文本文件，自动建目录（原 writeA）。"""
        async with self._lock(rel):
            p = self._path(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(p, "w", encoding="utf-8") as f:
                await f.write(text)

    # ---------- 文件级 ----------

    async def delete(self, rel: str) -> None:
        """删除文件（原删除整个文件场景）。"""
        async with self._lock(rel):
            try:
                self._path(rel).unlink(missing_ok=True)
            except OSError:
                pass

    async def list_files(self, rel_dir: str) -> list:
        """列出目录下的文件名。"""
        d = self.root / rel_dir
        if not d.exists():
            return []
        return sorted(p.name for p in d.iterdir() if p.is_file())

    async def read_all_json(self, rel_dir: str) -> dict:
        """读取目录下所有 JSON 文件，返回 {文件名(去扩展名): 内容}。"""
        result: dict = {}
        d = self.root / rel_dir
        if not d.exists():
            return result
        for p in d.iterdir():
            if p.is_file() and p.suffix == ".json":
                result[p.stem] = await self.read_json(f"{rel_dir}/{p.name}", {})
        return result
