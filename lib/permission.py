"""权限校验。

对应原 index.mjs 的 checkOwner2（仅主人）、checkOwner3（主人或「管理模式」开启时的群管理）。
主人名单来自 _conf_schema 的 owner_qqs；管理模式群列表为 admin_mode_groups。
"""
from __future__ import annotations

from typing import Any

from astrbot.api import logger


class Permission:
    """权限工具，挂载在 Star 实例上。"""

    def __init__(self, star: Any) -> None:
        self.star = star

    def _owners(self) -> list:
        raw = self.star.config.get("owner_qqs", "")
        if isinstance(raw, list):
            return [str(x).strip() for x in raw if str(x).strip()]
        return [str(x).strip() for x in str(raw).replace("，", ",").split(",") if str(x).strip()]

    def is_owner(self, uid: Any) -> bool:
        return str(uid) in self._owners()

    async def check_owner(self, event: Any) -> bool:
        """仅主人可用（原 checkOwner2）。"""
        return self.is_owner(event.get_sender_id())

    async def check_admin(self, event: Any) -> bool:
        """主人 或 管理模式群内的群管理可用（原 checkOwner3）。"""
        uid = event.get_sender_id()
        if self.is_owner(uid):
            return True
        gid = event.get_group_id()
        if not gid:
            return False
        admin_groups = [str(x) for x in self.star.config.get("admin_mode_groups", [])]
        if str(gid) in admin_groups:
            role = await self.group_role(event)
            return role in ("owner", "admin")
        return False

    async def group_role(self, event: Any) -> str:
        """返回用户在群的角色：owner / admin / member。"""
        gid = event.get_group_id()
        uid = event.get_sender_id()
        if not gid:
            return "member"
        try:
            info = await self.star.api.get_group_member_info(gid, uid)
            return (info or {}).get("role", "member")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"获取群角色失败: {e}")
            return "member"

    async def check_perm(self, event: Any, level: int) -> bool:
        """通用等级检查：3=owner 2=admin 1=member（原 RC_group_role 对照）。"""
        uid = event.get_sender_id()
        if self.is_owner(uid):
            return True
        if level <= 1:
            return True
        if not event.get_group_id():
            return False
        role = await self.group_role(event)
        role_level = {"owner": 3, "admin": 2, "member": 1}.get(role, 1)
        return role_level >= level
