# -*- coding: utf-8 -*-
"""配置文件与配置桶的读写、旧数据迁移以及配置规整。

这里的每个方法都是插件实例的 mixin 方法：``self.config`` / ``self.context``
仍然是插件实例上的属性，因此调用方无需感知方法来自哪个模块。
"""

import os
import uuid

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.web import request as web_request

from .constants import (
    DEFAULT_PROFILE_KEY,
    MAX_EXAMPLE_REPLY_CHARS,
    MAX_EXAMPLE_THOUGHT_CHARS,
    MAX_EXAMPLE_USER_CHARS,
    MAX_KEYWORD_CHARS,
    MAX_NAME_CHARS,
    MAX_RULES,
    MAX_THOUGHT_CHAINS,
    MIGRATED_KEY,
    PLUGIN_NAME,
    SCOPES,
)


class StoreMixin:
    """配置文件解析、配置桶读写与配置规整的 mixin。"""

    # ---------------------------------------------------------------- 配置文件

    @staticmethod
    def _key_of_path(path: object) -> str:
        """配置路径转配置文件 key：取文件名，空路径兜底为默认配置文件。"""
        text = str(path or "").strip()
        return os.path.basename(text) or DEFAULT_PROFILE_KEY

    def _profile_list(self) -> list[dict]:
        """当前配置文件列表，供前端下拉选择。"""
        profiles: list[dict] = []
        mgr = getattr(self.context, "astrbot_config_mgr", None)
        if mgr is not None:
            try:
                infos = mgr.get_conf_list()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[{PLUGIN_NAME}] 读取配置文件列表失败: {exc}")
                infos = []
            for info in infos:
                if not isinstance(info, dict):
                    continue
                profiles.append(
                    {
                        "key": self._key_of_path(info.get("path")),
                        "name": str(info.get("name") or "默认配置"),
                        "is_default": info.get("id") == "default",
                    }
                )
        if not profiles:
            conf = self.context.get_config()
            profiles.append(
                {
                    "key": self._key_of_path(getattr(conf, "config_path", "")),
                    "name": "默认配置",
                    "is_default": True,
                }
            )
        # 按 key 去重，保留首次出现顺序
        seen: set[str] = set()
        unique: list[dict] = []
        for item in profiles:
            if item["key"] in seen:
                continue
            seen.add(item["key"])
            unique.append(item)
        return unique

    def _active_profile_key(self) -> str:
        """当前被会话绑定的配置文件；没有绑定时用默认配置文件。仅用于旧数据迁移。"""
        mgr = getattr(self.context, "astrbot_config_mgr", None)
        if mgr is not None:
            ucr = getattr(mgr, "ucr", None)
            routes = getattr(ucr, "umop_to_conf_id", None) or {}
            conf_id = next(iter(routes.values()), None)
            if conf_id:
                confs = getattr(mgr, "confs", None) or {}
                conf = confs.get(conf_id)
                if conf is not None:
                    return self._key_of_path(getattr(conf, "config_path", ""))
        return self._key_of_path(
            getattr(self.context.get_config(), "config_path", "")
        )

    def _profile_key_of(self, event: AstrMessageEvent) -> str:
        """按当前会话解析配置文件 key；注入与剥离共用这一处口径。"""
        umo = getattr(event, "unified_msg_origin", "") or ""
        conf = self.context.get_config(umo or None)
        return self._key_of_path(getattr(conf, "config_path", ""))

    def _all_profiles(self) -> dict:
        raw = self.config.get("profiles")
        return raw if isinstance(raw, dict) else {}

    def _bucket(self, profile_key: str) -> dict:
        bucket = self._all_profiles().get(profile_key)
        return bucket if isinstance(bucket, dict) else {}

    def _migrate_legacy(self) -> None:
        """把旧版顶层配置一次性迁到当前在用的配置文件桶。"""
        if self.config.get(MIGRATED_KEY) is True:
            return

        legacy: dict = {}
        for key in ("rules", "thought_chains", "thought_example"):
            value = self.config.get(key)
            if value is not None:
                legacy[key] = value

        profiles = dict(self._all_profiles())
        if any(legacy.values()):
            target = self._active_profile_key()
            bucket = dict(profiles.get(target) or {})
            for key, value in legacy.items():
                bucket[key] = value
            profiles[target] = bucket
            logger.info(f"[{PLUGIN_NAME}] 旧配置已迁移到配置文件 {target}")

        try:
            self.config.save_config({"profiles": profiles, MIGRATED_KEY: True})
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[{PLUGIN_NAME}] 配置迁移落盘失败: {exc}")
            return
        self.config["profiles"] = profiles
        self.config[MIGRATED_KEY] = True

    def _write_bucket(self, profile_key: str, updates: dict) -> tuple[bool, str]:
        """写入指定配置文件桶并持久化。"""
        profiles = dict(self._all_profiles())
        bucket = dict(profiles.get(profile_key) or {})
        for key, value in updates.items():
            bucket[key] = value
        profiles[profile_key] = bucket
        try:
            self.config.save_config({"profiles": profiles})
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[{PLUGIN_NAME}] 保存配置失败: {exc}")
            return False, str(exc)
        self.config["profiles"] = profiles
        return True, ""

    @staticmethod
    def _profile_from_query() -> str | None:
        """GET 请求的配置文件 key；未传时返回 None。"""
        value = web_request.query.get("profile")
        return str(value).strip() if value else None

    def _resolve_profile(self, raw: object) -> tuple[str | None, str]:
        """校验配置文件 key 是否属于当前配置文件列表。"""
        key = str(raw or "").strip()
        if not key:
            return None, "缺少 profile"
        if key not in {p["key"] for p in self._profile_list()}:
            return None, "profile 不是有效的配置文件"
        return key, ""

    # ---------------------------------------------------------------- 内部

    @staticmethod
    def _is_group(event: AstrMessageEvent) -> bool:
        """判断当前会话是不是群聊。"""
        umo = getattr(event, "unified_msg_origin", "") or ""
        return "GroupMessage" in umo

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex[:8]

    def _normalize_rules(self, raw: object) -> list[dict]:
        """规整规则列表，配置读取与预览草稿共用同一套口径。"""
        rules: list[dict] = []

        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, str):
                    continue
                scope = item.get("scope")
                if scope not in SCOPES:
                    scope = "all"
                rules.append(
                    {
                        "id": str(item.get("id") or self._new_id()),
                        "name": str(item.get("name") or "未命名规则")[:MAX_NAME_CHARS],
                        "enabled": bool(item.get("enabled", True)),
                        "scope": scope,
                        "content": content,
                    }
                )

        return rules[:MAX_RULES]

    def _load_rules(self, profile_key: str) -> list[dict]:
        """读指定配置文件的规则列表。"""
        return self._normalize_rules(self._bucket(profile_key).get("rules"))

    @staticmethod
    def _scene_of(event: AstrMessageEvent) -> str:
        """把事件映射成场景标识，注入与预览共用这一处口径。"""
        return "group" if StoreMixin._is_group(event) else "private"

    def _snapshot(self, profile_key: str) -> dict:
        """指定配置文件已保存配置的快照，供注入与预览共用。"""
        bucket = self._bucket(profile_key)
        return {
            "rules": self._normalize_rules(bucket.get("rules")),
            "thought_chains": self._normalize_chains(bucket.get("thought_chains")),
            "thought_example": self._normalize_thought_example(
                bucket.get("thought_example")
            ),
        }

    def _normalize_chains(self, raw: object) -> list[dict]:
        """规整思维链列表，配置读取与预览草稿共用同一套口径。"""
        chains: list[dict] = []

        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, str):
                    continue
                keyword = self._clean_keyword(item.get("keyword"))
                if not keyword:
                    continue
                example = self._clean_example(
                    item.get("example_thought"), MAX_EXAMPLE_THOUGHT_CHARS
                )
                chains.append(
                    {
                        "id": str(item.get("id") or self._new_id()),
                        "name": str(item.get("name") or keyword)[:MAX_NAME_CHARS],
                        "keyword": keyword,
                        "enabled": bool(item.get("enabled", True)),
                        "content": content,
                        "example_thought": example,
                    }
                )

        return chains[:MAX_THOUGHT_CHAINS]

    @staticmethod
    def _clean_keyword(raw: object) -> str:
        """规整关键词：去掉尖括号与空白，只留裸词。"""
        text = str(raw or "").strip()
        for token in ("<", ">", "/", " ", "\t", "\n"):
            text = text.replace(token, "")
        return text[:MAX_KEYWORD_CHARS]

    @staticmethod
    def _clean_example(raw: object, limit: int) -> str:
        """规整示例文本：去首尾空白并截断，非字符串一律当留空。"""
        return raw.strip()[:limit] if isinstance(raw, str) else ""

    def _normalize_thought_example(self, raw: object) -> dict:
        """规整全局示例场景；留空的字段不在这里补默认值，交给拼装处回退。"""
        if not isinstance(raw, dict):
            raw = {}
        return {
            "user": self._clean_example(raw.get("user"), MAX_EXAMPLE_USER_CHARS),
            "reply": self._clean_example(raw.get("reply"), MAX_EXAMPLE_REPLY_CHARS),
        }

    # ---------------------------------------------------------------- 单条操作

    def _write_rules(self, profile_key: str, rules: list[dict]) -> tuple[bool, str]:
        """写规则列表到指定配置文件桶并持久化。"""
        return self._write_bucket(profile_key, {"rules": rules})

    def _write_thought_chains(
        self, profile_key: str, chains: list[dict], example: dict | None = None
    ) -> tuple[bool, str]:
        """写思维链列表到指定配置文件桶并持久化；example 非空时一并落盘。"""
        updates: dict = {"thought_chains": chains}
        if example is not None:
            updates["thought_example"] = example
        return self._write_bucket(profile_key, updates)
