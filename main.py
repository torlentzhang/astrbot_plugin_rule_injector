# -*- coding: utf-8 -*-
"""把行为约束类规则按场景注入 system prompt。

on_llm_request 阶段把规则直接追加到 system_prompt，按场景区分。

规则存于配置文件的 rules 数组：
    [{"id": str, "name": str, "enabled": bool, "scope": "group|private|all", "content": str}]
"""

import uuid

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.api.web import request as web_request
from astrbot.core.config.astrbot_config import AstrBotConfig

PLUGIN_NAME = "astrbot_plugin_rule_injector"
MAX_RULES = 10
MAX_NAME_CHARS = 60
MAX_CONTENT_CHARS = 20000
SCOPES = ("group", "private", "all")


@register(
    PLUGIN_NAME,
    "local",
    "把行为约束类规则按场景注入 system prompt",
    "0.1.0",
)
class RuleInjectorPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        context.register_web_api(
            f"/{PLUGIN_NAME}/config",
            self.api_get_config,
            ["GET"],
            "读取规则配置",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/config",
            self.api_save_config,
            ["POST"],
            "保存规则配置",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/rule",
            self.api_save_rule,
            ["POST"],
            "保存单条规则",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/rule/delete",
            self.api_delete_rule,
            ["POST"],
            "删除单条规则",
        )
        logger.info(f"[{PLUGIN_NAME}] 已加载")

    # ---------------------------------------------------------------- 内部

    @staticmethod
    def _is_group(event: AstrMessageEvent) -> bool:
        """判断当前会话是不是群聊。"""
        umo = getattr(event, "unified_msg_origin", "") or ""
        return "GroupMessage" in umo

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex[:8]

    def _load_rules(self) -> list[dict]:
        """读规则列表。"""
        raw = self.config.get("rules")
        rules: list[dict] = []

        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, str) or not content.strip():
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

    def _collect(self, event: AstrMessageEvent) -> str:
        """收集当前场景该注入的规则内容，按列表顺序拼接。"""
        is_group = self._is_group(event)
        parts: list[str] = []
        for rule in self._load_rules():
            if not rule["enabled"]:
                continue
            scope = rule["scope"]
            if scope == "all" or (scope == "group") == is_group:
                parts.append(rule["content"].strip())
        return "\n\n".join(p for p in parts if p)

    # ---------------------------------------------------------------- 注入

    @filter.on_llm_request(priority=-1000)
    async def inject_rules(
        self, event: AstrMessageEvent, request: ProviderRequest
    ) -> None:
        """在 LLM 请求前把规则追加到 system_prompt 末尾。"""
        block = self._collect(event)
        if not block:
            return

        base = (request.system_prompt or "").rstrip()
        request.system_prompt = f"{base}\n\n{block}" if base else block

        scene = "群聊" if self._is_group(event) else "私聊"
        logger.info(f"[{PLUGIN_NAME}] 已注入规则（{scene}，{len(block)} 字符）")

    # ---------------------------------------------------------------- Web API

    async def api_get_config(self):
        """读取当前配置。"""
        return {
            "rules": self._load_rules(),
            "limits": {
                "max_rules": MAX_RULES,
                "max_name_chars": MAX_NAME_CHARS,
                "max_content_chars": MAX_CONTENT_CHARS,
            },
        }

    async def api_save_config(self):
        """保存配置，立即生效。"""
        payload = await web_request.json(default={})
        if not isinstance(payload, dict):
            return {"ok": False, "error": "请求体必须是 JSON 对象"}

        raw_rules = payload.get("rules")
        if not isinstance(raw_rules, list):
            return {"ok": False, "error": "rules 必须是数组"}

        if len(raw_rules) > MAX_RULES:
            return {"ok": False, "error": f"规则最多 {MAX_RULES} 条"}

        cleaned: list[dict] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(raw_rules):
            if not isinstance(item, dict):
                return {"ok": False, "error": f"第 {index + 1} 条规则格式不对"}

            content = item.get("content")
            if not isinstance(content, str):
                return {"ok": False, "error": f"第 {index + 1} 条规则内容必须是字符串"}
            if len(content) > MAX_CONTENT_CHARS:
                return {
                    "ok": False,
                    "error": f"第 {index + 1} 条规则内容超过 {MAX_CONTENT_CHARS} 字符",
                }
            if not content.strip():
                # 内容为空的规则直接丢弃，避免注入空段
                continue

            name = item.get("name")
            name = str(name).strip()[:MAX_NAME_CHARS] if name else ""
            if not name:
                name = f"规则{index + 1}"

            scope = item.get("scope")
            if scope not in SCOPES:
                scope = "all"

            rule_id = str(item.get("id") or "").strip()
            if not rule_id or rule_id in seen_ids:
                rule_id = self._new_id()
            seen_ids.add(rule_id)

            cleaned.append(
                {
                    "id": rule_id,
                    "name": name,
                    "enabled": bool(item.get("enabled", True)),
                    "scope": scope,
                    "content": content,
                }
            )

        updates: dict = {"rules": cleaned}

        try:
            self.config.save_config(updates)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[{PLUGIN_NAME}] 保存配置失败: {exc}")
            return {"ok": False, "error": f"保存失败: {exc}"}

        for key, value in updates.items():
            self.config[key] = value

        total = sum(len(r["content"]) for r in cleaned)
        logger.info(f"[{PLUGIN_NAME}] 配置已保存（{len(cleaned)} 条规则，共 {total} 字符）")
        return {
            "ok": True,
            "count": len(cleaned),
            "total_chars": total,
            "rules": cleaned,
        }

    # ---------------------------------------------------------------- 单条操作

    def _write_rules(self, rules: list[dict]) -> tuple[bool, str]:
        """写规则列表到配置并持久化。"""
        updates = {"rules": rules}
        try:
            self.config.save_config(updates)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[{PLUGIN_NAME}] 保存失败: {exc}")
            return False, str(exc)
        for key, value in updates.items():
            self.config[key] = value
        return True, ""

    async def api_save_rule(self):
        """保存单条规则（新增或更新）。"""
        payload = await web_request.json(default={})
        if not isinstance(payload, dict):
            return {"ok": False, "error": "请求体必须是 JSON 对象"}

        content = payload.get("content")
        if not isinstance(content, str):
            return {"ok": False, "error": "content 必须是字符串"}
        if len(content) > MAX_CONTENT_CHARS:
            return {"ok": False, "error": f"内容超过 {MAX_CONTENT_CHARS} 字符"}
        if not content.strip():
            return {"ok": False, "error": "内容不能为空"}

        name = str(payload.get("name") or "").strip()[:MAX_NAME_CHARS] or "未命名规则"
        scope = payload.get("scope")
        if scope not in SCOPES:
            scope = "all"

        rules = self._load_rules()
        rule_id = str(payload.get("id") or "").strip()

        existing = None
        if rule_id:
            for rule in rules:
                if rule["id"] == rule_id:
                    existing = rule
                    break

        if existing is not None:
            existing["name"] = name
            existing["scope"] = scope
            existing["content"] = content
        else:
            if len(rules) >= MAX_RULES:
                return {"ok": False, "error": f"最多 {MAX_RULES} 条规则"}
            rule_id = rule_id or self._new_id()
            rules.append(
                {
                    "id": rule_id,
                    "name": name,
                    "enabled": True,
                    "scope": scope,
                    "content": content,
                }
            )

        ok, err = self._write_rules(rules)
        if not ok:
            return {"ok": False, "error": f"保存失败: {err}"}

        logger.info(f"[{PLUGIN_NAME}] 已保存规则「{name}」")
        return {"ok": True, "id": rule_id, "rules": rules}

    async def api_delete_rule(self):
        """删除单条规则。"""
        payload = await web_request.json(default={})
        rule_id = str((payload or {}).get("id") or "").strip()
        if not rule_id:
            return {"ok": False, "error": "缺少 id"}

        rules = self._load_rules()
        remaining = [r for r in rules if r["id"] != rule_id]
        if len(remaining) == len(rules):
            return {"ok": False, "error": "找不到这条规则"}

        ok, err = self._write_rules(remaining)
        if not ok:
            return {"ok": False, "error": f"删除失败: {err}"}

        logger.info(f"[{PLUGIN_NAME}] 已删除规则 {rule_id}")
        return {"ok": True, "rules": remaining}

    async def terminate(self):
        """插件卸载时调用。"""
        logger.info(f"[{PLUGIN_NAME}] 已卸载")
