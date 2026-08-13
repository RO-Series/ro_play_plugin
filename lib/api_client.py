from __future__ import annotations

from typing import Any

from astrbot.api import logger

class ApiClient:

    def __init__(self, star: Any) -> None:
        self.star = star

    async def call(self, action: str, **params: Any) -> bool:

        try:
            result = await self.call_result(action, **params)
            if result is None:
                return False
            if isinstance(result, dict):
                return str(result.get("retcode", -1)) == "0"
            return str(getattr(result, "retcode", -1)) == "0"
        except Exception as e:
            logger.warning(f"API {action} 调用失败: {e}")
            return False

    async def call_result(self, action: str, **params: Any) -> Any:

        for k in ("group_id", "user_id", "message_id"):
            if k in params and params[k] is not None:
                try:
                    params[k] = int(params[k])
                except (TypeError, ValueError):
                    pass
        client = await self._client()
        if client is None:
            return None
        try:
            return await client.api.call_action(action, **params)
        except Exception as e:
            logger.warning(f"API {action} 调用失败: {e}")
            return None

    async def _client(self) -> Any | None:

        try:
            platform = self.star.context.get_platform_inst("aiocqhttp")
            return platform.get_client()
        except Exception as e:
            logger.warning(f"获取 aiocqhttp 平台实例失败: {e}")
            return None

    async def send_msg(
        self, message_type: str, target_id: Any, message: Any, **extra: Any
    ) -> bool:

        key = "group_id" if message_type == "group" else "user_id"
        return await self.call("send_msg", **{key: target_id, "message": message}, **extra)

    async def get_group_list(self) -> list:
        r = await self.call_result("get_group_list")
        if isinstance(r, dict):
            return r.get("data", []) or []
        return r or []

    async def get_friend_list(self) -> list:
        r = await self.call_result("get_friend_list")
        if isinstance(r, dict):
            return r.get("data", []) or []
        return r or []

    async def get_group_member_list(self, group_id: Any) -> list:
        r = await self.call_result("get_group_member_list", group_id=group_id)
        if isinstance(r, dict):
            return r.get("data", []) or []
        return r or []

    async def get_group_member_info(self, group_id: Any, user_id: Any) -> dict | None:
        r = await self.call_result(
            "get_group_member_info", group_id=group_id, user_id=user_id, no_cache=True
        )
        if isinstance(r, dict):
            return r.get("data") or None
        return r or None

    async def get_group_info(self, group_id: Any) -> dict | None:
        r = await self.call_result("get_group_info", group_id=group_id, no_cache=True)
        if isinstance(r, dict):
            return r.get("data") or None
        return r or None

    async def get_login_info(self) -> dict | None:
        r = await self.call_result("get_login_info")
        if isinstance(r, dict):
            return r.get("data") or None
        return r or None
