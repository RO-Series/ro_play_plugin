"""数据迁移脚本：将旧 MKbot（NapCat）数据迁移到 RO_Play（AstrBot）结构。

用法：
    python migrate_data.py --src "旧NapCat插件数据目录" --dst "AstrBot/data/plugin_data/astrbot_plugin_ro_play"

迁移内容：
1. 旧数据目录下的「筱筱吖/」整目录 → 新结构「BaiXuan/」（内部子目录结构不变）。
2. 旧 config.json 字段 → 新配置键映射，写入 --dst/config.json。
3. 旧 HTML 模板 / 文本资源（如有）复制到 --dst/templates/。

说明：migrate_data.py 在 AstrBot 环境外独立运行（仅用标准库），
迁移完成后建议在 AstrBot WebUI 中重新配置 owner_qqs 等安全敏感项。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

# 旧 config.json 键 → 新 _conf_schema 键
CONFIG_MAP: dict[str, str] = {
    "OwnerQQs": "owner_qqs",
    "nowoner": "non_owner_reply",
    "nowonernr": "non_owner_reply_text",
    "自触开关": "self_trigger",
    "助手模式": "assistant_mode",
    "cs_of": "html_render_enabled",
    "深度娱乐路径": "deep_entertainment_path",
    "group_of": "group_whitelist",
    "haoyou_of": "friend_whitelist",
    "音乐接口": "music_card_api",
    "今日运势失败不发原图": "fortune_no_fallback",
    "绕过授权": "bypass_license",
    "mkbot_render_api_base": "render_api_base",
}


def migrate_tree(src: Path, dst: Path) -> tuple[int, int]:
    """把 src 下的目录整体复制到 dst，返回 (文件数, 目录数)。"""
    files = dirs = 0
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        target = dst / rel
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            dirs += 1
        elif p.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.stat().st_size == p.stat().st_size:
                continue  # 已迁移过，跳过
            shutil.copy2(p, target)
            files += 1
    return files, dirs


def migrate_config(src_cfg: Path, dst_cfg: Path) -> int:
    """映射旧 config.json 字段到新配置，返回迁移的字段数。"""
    if not src_cfg.exists():
        print(f"[跳过] 未找到旧配置文件: {src_cfg}")
        return 0
    try:
        old = json.loads(src_cfg.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[警告] 解析旧配置失败: {e}")
        return 0
    new: dict = {}
    for old_key, new_key in CONFIG_MAP.items():
        if old_key in old and old[old_key] is not None:
            new[new_key] = old[old_key]
    if "深度娱乐路径" in new.get("deep_entertainment_path", ""):
        # 路径前缀统一替换：筱筱吖 → BaiXuan
        new["deep_entertainment_path"] = new["deep_entertainment_path"].replace("筱筱吖", "BaiXuan")
    if new:
        dst_cfg.parent.mkdir(parents=True, exist_ok=True)
        dst_cfg.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[完成] 旧 config.json 已映射 {len(new)} 个字段 → {dst_cfg}")
    return len(new)


def main() -> int:
    parser = argparse.ArgumentParser(description="MKbot(NapCat) → RO_Play(AstrBot) 数据迁移")
    parser.add_argument("--src", required=True, help="旧 NapCat 插件数据目录（含 config.json 与 筱筱吖/ 的目录）")
    parser.add_argument("--dst", required=True, help="目标目录（plugin_data/astrbot_plugin_ro_play）")
    args = parser.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)
    if not src.exists():
        print(f"[错误] 源目录不存在: {src}")
        return 1

    # 1. 迁移「筱筱吖/」→「BaiXuan/」
    old_tree = src / "筱筱吖"
    if old_tree.exists():
        files, dirs = migrate_tree(old_tree, dst / "BaiXuan")
        print(f"[完成] 筱筱吖/ → BaiXuan/：{files} 个文件、{dirs} 个目录")
    else:
        print("[跳过] 源目录中不存在 筱筱吖/，检查是否为其他结构（如 config/plugins/...）")

    # 2. 迁移 config.json
    migrate_config(src / "config.json", dst / "config.json")

    # 3. 迁移默认资源（HTML 模板与文本，如存在）
    res = src / "默认资源"
    if res.exists():
        files, dirs = migrate_tree(res, dst / "templates")
        print(f"[完成] 默认资源/ → templates/：{files} 个文件、{dirs} 个目录")
    else:
        print("[跳过] 未发现 默认资源/ 目录（模板由插件自带，无需迁移）")

    print("\n迁移完成。请到 AstrBot WebUI 的插件配置页检查 owner_qqs 等安全敏感项。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
