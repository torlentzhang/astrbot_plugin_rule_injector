# -*- coding: utf-8 -*-
"""Web API handler 集合。

所有 handler 只做参数校验与调用 core 提供的读写/拼装能力，业务逻辑不在此处重复实现。
"""

from astrbot.api import logger
from astrbot.api.web import request as web_request

from ..core.constants import (
    DEFAULT_THOUGHT_RULE,
    MAX_CONTENT_CHARS,
    MAX_EXAMPLE_REPLY_CHARS,
    MAX_EXAMPLE_THOUGHT_CHARS,
    MAX_EXAMPLE_USER_CHARS,
    MAX_KEYWORD_CHARS,
    MAX_NAME_CHARS,
    MAX_RULES,
    MAX_THOUGHT_CHAINS,
    PLUGIN_NAME,
    SCOPES,
)


class ApiHandlersMixin:
    """9 个 Web API handler 的 mixin，self 即插件实例。"""

    # ---------------------------------------------------------------- Web API

    async def api_get_profiles(self):
        """列出配置文件，供前端切换。"""
        return {"ok": True, "profiles": self._profile_list()}

    async def api_get_config(self):
        """读取指定配置文件的配置。"""
        profile_key = self._profile_from_query()
        if not profile_key:
            return {"ok": False, "error": "缺少 profile 参数"}
        key, err = self._resolve_profile(profile_key)
        if err:
            return {"ok": False, "error": err}

        snapshot = self._snapshot(key)
        return {
            "ok": True,
            "profile": key,
            "rules": snapshot["rules"],
            "thought_chains": snapshot["thought_chains"],
            "thought_example": snapshot["thought_example"],
            "limits": {
                "max_rules": MAX_RULES,
                "max_thought_chains": MAX_THOUGHT_CHAINS,
                "max_name_chars": MAX_NAME_CHARS,
                "max_keyword_chars": MAX_KEYWORD_CHARS,
                "max_content_chars": MAX_CONTENT_CHARS,
                "max_example_thought_chars": MAX_EXAMPLE_THOUGHT_CHARS,
                "max_example_user_chars": MAX_EXAMPLE_USER_CHARS,
                "max_example_reply_chars": MAX_EXAMPLE_REPLY_CHARS,
            },
            "default_thought_rule": DEFAULT_THOUGHT_RULE,
        }

    async def api_preview(self):
        """预览指定配置文件实际注入的两部分；只读，不改变已保存的配置。

        前端可传入未保存的草稿，预览按草稿渲染，source 标明内容来源。
        """
        payload = await web_request.json(default={})
        if not isinstance(payload, dict):
            return {"ok": False, "error": "请求体必须是 JSON 对象"}

        key, err = self._resolve_profile(payload.get("profile"))
        if err:
            return {"ok": False, "error": err}

        scene = payload.get("scene")
        if scene not in ("group", "private"):
            return {"ok": False, "error": "scene 必须是 group 或 private"}

        snapshot = self._snapshot(key)
        source = "saved"
        draft = payload.get("draft")
        if draft is not None:
            if not isinstance(draft, dict):
                return {"ok": False, "error": "draft 必须是 JSON 对象"}
            source = "draft"
            if "rules" in draft:
                snapshot["rules"] = self._normalize_rules(draft["rules"])
            if "thought_chains" in draft:
                snapshot["thought_chains"] = self._normalize_chains(
                    draft["thought_chains"]
                )
            if "thought_example" in draft:
                snapshot["thought_example"] = self._normalize_thought_example(
                    draft["thought_example"]
                )

        result = self._assemble(snapshot, scene)
        return {
            "ok": True,
            "profile": key,
            "scene": scene,
            "source": source,
            "system_prompt_block": result["system_prompt_block"],
            "contexts": result["contexts"],
        }

    async def api_save_config(self):
        """保存指定配置文件的规则配置，立即生效。"""
        payload = await web_request.json(default={})
        if not isinstance(payload, dict):
            return {"ok": False, "error": "请求体必须是 JSON 对象"}

        key, err = self._resolve_profile(payload.get("profile"))
        if err:
            return {"ok": False, "error": err}

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

        ok, err = self._write_bucket(key, {"rules": cleaned})
        if not ok:
            return {"ok": False, "error": f"保存失败: {err}"}

        total = sum(len(r["content"]) for r in cleaned)
        logger.info(
            f"[{PLUGIN_NAME}] 配置已保存（配置文件 {key}，{len(cleaned)} 条规则，"
            f"共 {total} 字符）"
        )
        return {
            "ok": True,
            "profile": key,
            "count": len(cleaned),
            "total_chars": total,
            "rules": cleaned,
        }

    async def api_save_thoughts(self):
        """整体保存指定配置文件的思维链列表及示例场景（原子写入）。"""
        payload = await web_request.json(default={})
        if not isinstance(payload, dict):
            return {"ok": False, "error": "请求体必须是 JSON 对象"}

        key, err = self._resolve_profile(payload.get("profile"))
        if err:
            return {"ok": False, "error": err}

        raw = payload.get("thought_chains")
        if not isinstance(raw, list):
            return {"ok": False, "error": "thought_chains 必须是数组"}

        if len(raw) > MAX_THOUGHT_CHAINS:
            return {"ok": False, "error": f"思维链最多 {MAX_THOUGHT_CHAINS} 条"}

        cleaned: list[dict] = []
        seen_ids: set[str] = set()
        seen_keywords: set[str] = set()
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                return {"ok": False, "error": f"第 {index + 1} 条思维链格式不对"}

            content = item.get("content")
            if not isinstance(content, str):
                return {
                    "ok": False,
                    "error": f"第 {index + 1} 条思维链内容必须是字符串",
                }
            if len(content) > MAX_CONTENT_CHARS:
                return {
                    "ok": False,
                    "error": f"第 {index + 1} 条思维链内容超过 {MAX_CONTENT_CHARS} 字符",
                }
            example = self._clean_example(
                item.get("example_thought"), MAX_EXAMPLE_THOUGHT_CHARS
            )
            keyword = self._clean_keyword(item.get("keyword"))
            if not keyword:
                return {"ok": False, "error": f"第 {index + 1} 条思维链缺少关键词"}
            if keyword.lower() in seen_keywords:
                return {"ok": False, "error": f"关键词「{keyword}」重复"}
            seen_keywords.add(keyword.lower())

            name = str(item.get("name") or "").strip()[:MAX_NAME_CHARS] or keyword

            chain_id = str(item.get("id") or "").strip()
            if not chain_id or chain_id in seen_ids:
                chain_id = self._new_id()
            seen_ids.add(chain_id)

            cleaned.append(
                {
                    "id": chain_id,
                    "name": name,
                    "keyword": keyword,
                    "enabled": bool(item.get("enabled", True)),
                    "content": content,
                    "example_thought": example,
                }
            )

        updates: dict = {"thought_chains": cleaned}
        if "thought_example" in payload:
            raw_example = payload["thought_example"]
            if not isinstance(raw_example, dict):
                return {"ok": False, "error": "thought_example 必须是 JSON 对象"}
            updates["thought_example"] = {
                "user": self._clean_example(
                    raw_example.get("user"), MAX_EXAMPLE_USER_CHARS
                ),
                "reply": self._clean_example(
                    raw_example.get("reply"), MAX_EXAMPLE_REPLY_CHARS
                ),
            }

        ok, err = self._write_bucket(key, updates)
        if not ok:
            return {"ok": False, "error": f"保存失败: {err}"}

        logger.info(
            f"[{PLUGIN_NAME}] 思维链已保存（配置文件 {key}，{len(cleaned)} 条）"
        )
        return {
            "ok": True,
            "profile": key,
            "count": len(cleaned),
            "thought_chains": cleaned,
        }

    # ---------------------------------------------------------------- 单条操作

    async def api_save_rule(self):
        """保存单条规则（新增或更新）。"""
        payload = await web_request.json(default={})
        if not isinstance(payload, dict):
            return {"ok": False, "error": "请求体必须是 JSON 对象"}

        key, err = self._resolve_profile(payload.get("profile"))
        if err:
            return {"ok": False, "error": err}

        content = payload.get("content")
        if not isinstance(content, str):
            return {"ok": False, "error": "content 必须是字符串"}
        if len(content) > MAX_CONTENT_CHARS:
            return {"ok": False, "error": f"内容超过 {MAX_CONTENT_CHARS} 字符"}
        name = str(payload.get("name") or "").strip()[:MAX_NAME_CHARS] or "未命名规则"
        scope = payload.get("scope")
        if scope not in SCOPES:
            scope = "all"

        rules = self._load_rules(key)
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

        ok, err = self._write_rules(key, rules)
        if not ok:
            return {"ok": False, "error": f"保存失败: {err}"}

        logger.info(f"[{PLUGIN_NAME}] 已保存规则「{name}」（配置文件 {key}）")
        return {"ok": True, "profile": key, "id": rule_id, "rules": rules}

    async def api_delete_rule(self):
        """删除单条规则。幂等：id 不存在时也算删除成功。"""
        payload = await web_request.json(default={})
        if not isinstance(payload, dict):
            return {"ok": False, "error": "请求体必须是 JSON 对象"}

        key, err = self._resolve_profile(payload.get("profile"))
        if err:
            return {"ok": False, "error": err}

        rule_id = str(payload.get("id") or "").strip()
        if not rule_id:
            return {"ok": False, "error": "缺少 id"}

        rules = self._load_rules(key)
        remaining = [r for r in rules if r["id"] != rule_id]

        if len(remaining) == len(rules):
            return {"ok": True, "profile": key, "rules": rules}

        ok, err = self._write_rules(key, remaining)
        if not ok:
            return {"ok": False, "error": f"删除失败: {err}"}

        logger.info(f"[{PLUGIN_NAME}] 已删除规则 {rule_id}（配置文件 {key}）")
        return {"ok": True, "profile": key, "rules": remaining}

    # ---------------------------------------------------------------- 思维链

    async def api_save_thought(self):
        """保存单条思维链（新增或更新）。"""
        payload = await web_request.json(default={})
        if not isinstance(payload, dict):
            return {"ok": False, "error": "请求体必须是 JSON 对象"}

        key, err = self._resolve_profile(payload.get("profile"))
        if err:
            return {"ok": False, "error": err}

        content = payload.get("content")
        if not isinstance(content, str):
            return {"ok": False, "error": "content 必须是字符串"}
        if len(content) > MAX_CONTENT_CHARS:
            return {"ok": False, "error": f"内容超过 {MAX_CONTENT_CHARS} 字符"}
        example = self._clean_example(
            payload.get("example_thought"), MAX_EXAMPLE_THOUGHT_CHARS
        )
        keyword = self._clean_keyword(payload.get("keyword"))
        if not keyword:
            return {"ok": False, "error": "关键词不能为空"}
        if keyword.lower() in ("think", "thinking"):
            return {
                "ok": False,
                "error": "关键词不能用 think，会导致只有首轮生效。",
            }

        name = str(payload.get("name") or "").strip()[:MAX_NAME_CHARS] or keyword

        chains = self._normalize_chains(self._bucket(key).get("thought_chains"))
        chain_id = str(payload.get("id") or "").strip()

        existing = None
        if chain_id:
            for chain in chains:
                if chain["id"] == chain_id:
                    existing = chain
                    break

        if existing is not None:
            existing["name"] = name
            existing["keyword"] = keyword
            existing["content"] = content
            existing["example_thought"] = example
        else:
            if len(chains) >= MAX_THOUGHT_CHAINS:
                return {"ok": False, "error": f"最多 {MAX_THOUGHT_CHAINS} 条思维链"}
            if any(c["keyword"].lower() == keyword.lower() for c in chains):
                return {"ok": False, "error": f"关键词「{keyword}」已存在"}
            chain_id = chain_id or self._new_id()
            chains.append(
                {
                    "id": chain_id,
                    "name": name,
                    "keyword": keyword,
                    "enabled": True,
                    "content": content,
                    "example_thought": example,
                }
            )

        ok, err = self._write_thought_chains(key, chains)
        if not ok:
            return {"ok": False, "error": f"保存失败: {err}"}

        logger.info(
            f"[{PLUGIN_NAME}] 已保存思维链「{name}」（配置文件 {key}，关键词 {keyword}）"
        )
        return {"ok": True, "profile": key, "id": chain_id, "thought_chains": chains}

    async def api_delete_thought(self):
        """删除单条思维链。幂等：id 不存在时也返回成功。"""
        payload = await web_request.json(default={})
        if not isinstance(payload, dict):
            return {"ok": False, "error": "请求体必须是 JSON 对象"}

        key, err = self._resolve_profile(payload.get("profile"))
        if err:
            return {"ok": False, "error": err}

        chain_id = str(payload.get("id") or "").strip()
        if not chain_id:
            return {"ok": False, "error": "缺少 id"}

        chains = self._normalize_chains(self._bucket(key).get("thought_chains"))
        remaining = [c for c in chains if c["id"] != chain_id]

        if len(remaining) == len(chains):
            return {"ok": True, "profile": key, "thought_chains": chains}

        ok, err = self._write_thought_chains(key, remaining)
        if not ok:
            return {"ok": False, "error": f"删除失败: {err}"}

        logger.info(f"[{PLUGIN_NAME}] 已删除思维链 {chain_id}（配置文件 {key}）")
        return {"ok": True, "profile": key, "thought_chains": remaining}
