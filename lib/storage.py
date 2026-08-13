from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiofiles

class DataStore:

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

    async def read_json(self, rel: str, default: Any = None) -> Any:

        async with self._lock(rel):
            try:
                async with aiofiles.open(self._path(rel), "r", encoding="utf-8") as f:
                    return json.loads(await f.read())
            except (FileNotFoundError, json.JSONDecodeError, ValueError):
                return default

    async def write_json(self, rel: str, data: Any) -> None:

        async with self._lock(rel):
            p = self._path(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".tmp")
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
            tmp.replace(p)

    async def read_key(self, rel: str, key: str, default: Any = None) -> Any:

        data = await self.read_json(rel, None)
        if isinstance(data, dict):
            return data.get(key, default)
        return default

    async def write_key(self, rel: str, key: str, value: Any) -> None:

        data = await self.read_json(rel, {})
        if not isinstance(data, dict):
            data = {}
        data[key] = value
        await self.write_json(rel, data)

    async def delete_key(self, rel: str, key: str) -> None:

        data = await self.read_json(rel, {})
        if isinstance(data, dict) and key in data:
            del data[key]
            await self.write_json(rel, data)

    async def has_key(self, rel: str, key: str) -> bool:

        data = await self.read_json(rel, {})
        return isinstance(data, dict) and key in data

    async def get_keys(self, rel: str) -> list:

        data = await self.read_json(rel, {})
        return list(data.keys()) if isinstance(data, dict) else []

    async def clear(self, rel: str) -> None:

        await self.write_json(rel, {})

    async def read_text(self, rel: str, default: str = "") -> str:

        async with self._lock(rel):
            try:
                async with aiofiles.open(self._path(rel), "r", encoding="utf-8") as f:
                    return await f.read()
            except FileNotFoundError:
                return default

    async def write_text(self, rel: str, text: str) -> None:

        async with self._lock(rel):
            p = self._path(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(p, "w", encoding="utf-8") as f:
                await f.write(text)

    async def delete(self, rel: str) -> None:

        async with self._lock(rel):
            try:
                self._path(rel).unlink(missing_ok=True)
            except OSError:
                pass

    async def list_files(self, rel_dir: str) -> list:

        d = self.root / rel_dir
        if not d.exists():
            return []
        return sorted(p.name for p in d.iterdir() if p.is_file())

    async def read_all_json(self, rel_dir: str) -> dict:

        result: dict = {}
        d = self.root / rel_dir
        if not d.exists():
            return result
        for p in d.iterdir():
            if p.is_file() and p.suffix == ".json":
                result[p.stem] = await self.read_json(f"{rel_dir}/{p.name}", {})
        return result
