"""RO_Play 功能模块包。

对应原 index.mjs 的 handleMessage（L8175）中各个功能分区，迁移自 MKbot 2.3.4。
本包导出 16 个功能模块类：
- LicenseModule（授权系统 / 卡密，原 handleCardLicenseCommands L61）
- AdminModule（群管系统，原 群管指令区 L9345-L9898、群发区 L15237-L15543）
- JoinReviewModule（入群审核 + 验证码 + 欢迎词 + 退群通知，原 L9175-L9293、L14319-L14535、handleNotice L17894、handleRequest L18287）
- EntertainmentModule（签到/钓鱼/银行/轮盘/打劫/运势/商店，原 L10832-L11730、L15623-L17109）
- GroupWifeModule（今日老婆/老公，原 handleGroupWifeCommands L503）
- DriftBottleModule（漂流瓶，原 handleDriftBottleCommands L1344）
- CardShopModule（发卡系统，原 发卡区 L16007-L16624）
- MusicModule（音乐系统，原 音乐区 L11750-L12524）
- QaModule（问答系统，原 问答区）
- FirekeepModule（续火系统，原 续火区 L13876-L13998）
- BlacklistModule（黑名单/违禁词/禁发，原 L9133、L13278-L13615、L17310-L17447）
- TalkStatsModule（发言统计，原 L8308、L14660）
- FakeChatModule（伪造聊天，原 L13198-L13223）
- MasqueradeModule（马甲系统，原 L16625-L16655）
- JoinPmModule（入群私聊，原 L8363-L8488、L18046）
- ToolsModule（工具集：三角洲/EPIC/搜饰品/MC/发病文学/图转链接/状态/AI声聊，原 L12542-L17496）

命名替换：路径前缀「筱筱吖」→「BaiXuan」，MK → RO，MKbot → RO_Play，mkbot → ro_play。
"""
from lib.modules.admin import AdminModule
from lib.modules.blacklist import BlacklistModule
from lib.modules.card_shop import CardShopModule
from lib.modules.drift_bottle import DriftBottleModule
from lib.modules.entertainment import EntertainmentModule
from lib.modules.fake_chat import FakeChatModule
from lib.modules.firekeep import FirekeepModule
from lib.modules.group_wife import GroupWifeModule
from lib.modules.join_pm import JoinPmModule
from lib.modules.join_review import JoinReviewModule
from lib.modules.license import LicenseModule
from lib.modules.masquerade import MasqueradeModule
from lib.modules.music import MusicModule
from lib.modules.qa import QaModule
from lib.modules.talk_stats import TalkStatsModule
from lib.modules.tools import ToolsModule

__all__ = [
    "AdminModule",
    "BlacklistModule",
    "CardShopModule",
    "DriftBottleModule",
    "EntertainmentModule",
    "FakeChatModule",
    "FirekeepModule",
    "GroupWifeModule",
    "JoinPmModule",
    "JoinReviewModule",
    "LicenseModule",
    "MasqueradeModule",
    "MusicModule",
    "QaModule",
    "TalkStatsModule",
    "ToolsModule",
]
