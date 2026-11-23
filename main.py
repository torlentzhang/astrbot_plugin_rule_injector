# -*- coding: utf-8 -*-
"""把行为约束类规则按场景注入 system prompt。

on_llm_request 阶段把规则直接追加到 system_prompt，按场景区分。

规则存于配置文件的 rules 数组：
    [{"id": str, "name": str, "enabled": bool, "scope": "group|private|all", "content": str}]

思维链存于 thought_chains 数组，每条自带关键词，关键词决定剥离用的标签：
    [{"id": str, "name": str, "keyword": str, "enabled": bool, "content": str,
      "example_thought": str}]
发送前会剥掉 <关键词>…</关键词>，但内容保留在会话历史里，模型下一轮仍看得到自己想过什么。
example_thought 是可选的示例念头，用来每轮动态拼一条少样本示例注入上下文，
让模型看到「上一次就是这么输出的」；留空时回退复用 content。
"""

import re
import uuid

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.api.web import request as web_request
from astrbot.core.config.astrbot_config import AstrBotConfig

PLUGIN_NAME = "astrbot_plugin_rule_injector"
MAX_RULES = 10
MAX_THOUGHT_CHAINS = 5
MAX_NAME_CHARS = 60
MAX_KEYWORD_CHARS = 12
MAX_CONTENT_CHARS = 20000
MAX_EXAMPLE_THOUGHT_CHARS = 500
SCOPES = ("group", "private", "all")

# 新增思维链时预填的内容。与 _conf_schema.json 里的默认值保持一致。
DEFAULT_THOUGHT_RULE = (
    "这里是你的内心想法：写得比说话长、可以写自己的反应、"
    "可以在心里复述他说的话、可以没头没尾，使用第一人称，"
    "别跳出来评价自己演得像不像。"
)


@register(
    PLUGIN_NAME,
    "local",
    "把行为约束类规则按场景注入 system prompt",
    "0.2.2",
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
        context.register_web_api(
            f"/{PLUGIN_NAME}/thought",
            self.api_save_thought,
            ["POST"],
            "保存单条思维链",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/thoughts",
            self.api_save_thoughts,
            ["POST"],
            "整体保存思维链列表",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/thought/delete",
            self.api_delete_thought,
            ["POST"],
            "删除单条思维链",
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

    def _collect(self, event: AstrMessageEvent) -> str:
        """收集当前场景该注入的内容并拼装。

        思维链的标签与格式由这里按关键词自动生成，用户只需要写
        「怎么想」，不必自己操心标记和格式。
        """
        chains = [
            c
            for c in self._load_thought_chains()
            if c["enabled"] and c["content"].strip()
        ]

        is_group = self._is_group(event)
        rules = [
            r
            for r in self._load_rules()
            if r["enabled"]
            and r["content"].strip()
            and (
                r["scope"] == "all"
                or (r["scope"] == "group") == is_group
            )
        ]

        if not chains and not rules:
            return ""

        blocks: list[str] = []

        # 没有思维链时，规则原样拼上去即可
        if not chains:
            blocks.extend(rule["content"].strip() for rule in rules)
            return "\n\n".join(blocks)

        # 有思维链时：规则在前，最终格式在后
        blocks.append("# 输出格式")
        blocks.extend(rule["content"].strip() for rule in rules)

        # 按关键词逐条生成最终格式，结尾的格式块位置最靠后、权重最高
        blocks.append("**每次都必须按照如下最终格式输出**")
        format_lines = ["最终格式："]
        for chain in chains:
            kw = chain["keyword"]
            format_lines.append(f"<{kw}>{chain['content'].strip()}</{kw}>")
        format_lines.append("你说的话")
        blocks.append("\n".join(format_lines))

        return "\n\n".join(blocks)

    def _load_thought_chains(self) -> list[dict]:
        """读思维链列表。"""
        raw = self.config.get("thought_chains")
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
                example = item.get("example_thought")
                example = (
                    example.strip()[:MAX_EXAMPLE_THOUGHT_CHARS]
                    if isinstance(example, str)
                    else ""
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

    def _thought_patterns(self) -> list[re.Pattern[str]]:
        """按已启用的关键词编译剥离用的正则。

        开标签要求完整，避免正文里出现关键词时被误伤；闭合标签容错，
        尖括号左括号与斜杠都可选，兼容模型偶尔漏写斜杠的情况。
        """
        patterns = []
        for chain in self._load_thought_chains():
            if not chain["enabled"]:
                continue
            kw = re.escape(chain["keyword"])
            patterns.append(
                re.compile(
                    rf"<\s*{kw}\s*>.*?<?\s*/?\s*{kw}\s*>",
                    re.DOTALL | re.IGNORECASE,
                )
            )
        return patterns

    # ---------------------------------------------------------------- 注入

    def _build_fewshot(self) -> list[dict] | None:
        """按当前启用的思维链拼一组一问一答的少样本示例。

        标签名跟随 keyword，标签内容优先用 example_thought，留空时回退 content，
        所以增删思维链后示例会自动同步，不用改人设配置或改代码。每条消息都带
        _no_save，只进本轮请求、不写会话历史，不会逐轮累积。
        """
        chains = [
            c
            for c in self._load_thought_chains()
            if c["enabled"] and c["content"].strip()
        ]
        if not chains:
            return None

        lines = []
        for chain in chains:
            thought = chain["example_thought"].strip() or chain["content"].strip()
            lines.append(f"<{chain['keyword']}>{thought}</{chain['keyword']}>")
        lines.append("嗯？怎么了")

        return [
            {"role": "user", "content": "在吗", "_no_save": True},
            {"role": "assistant", "content": "\n".join(lines), "_no_save": True},
        ]

    @filter.on_llm_request(priority=-1000)
    async def inject_rules(
        self, event: AstrMessageEvent, request: ProviderRequest
    ) -> None:
        """在 LLM 请求前注入规则与少样本示例。"""
        block = self._collect(event)
        if not block:
            return

        base = (request.system_prompt or "").rstrip()
        request.system_prompt = f"{base}\n\n{block}" if base else block

        fewshot = self._build_fewshot()
        if fewshot:
            contexts = request.contexts
            if isinstance(contexts, list):
                contexts.extend(fewshot)

        scene = "群聊" if self._is_group(event) else "私聊"
        logger.info(
            f"[{PLUGIN_NAME}] 已注入规则（{scene}，{len(block)} 字符，"
            f"少样本示例 {len(fewshot) if fewshot else 0} 条）"
        )

    # ---------------------------------------------------------------- 剥离

    @filter.on_decorating_result()
    async def strip_thought(self, event: AstrMessageEvent) -> None:
        """发送前剥掉思维链段，只把正文发出去。

        思维链本身要留在会话历史里，模型下一轮才看得到格式先例。
        """
        patterns = self._thought_patterns()
        if not patterns:
            return

        result = event.get_result()
        if result is None or not result.chain:
            return

        stripped = False
        kept: list = []
        for comp in result.chain:
            if isinstance(comp, Plain):
                text = comp.text
                for pattern in patterns:
                    text = pattern.sub("", text)
                if text != comp.text:
                    stripped = True
                    text = text.strip()
                    if text:
                        comp.text = text
                        kept.append(comp)
                    continue
            kept.append(comp)

        if not stripped:
            return

        if kept:
            result.chain = kept
        else:
            # 整条回复只有思维链，没有正文，不发送
            event.set_result(None)

        scene = "群聊" if self._is_group(event) else "私聊"
        logger.info(f"[{PLUGIN_NAME}] 已剥离思维链（{scene}）")

    # ---------------------------------------------------------------- Web API

    async def api_get_config(self):
        """读取当前配置。"""
        return {
            "rules": self._load_rules(),
            "thought_chains": self._load_thought_chains(),
            "limits": {
                "max_rules": MAX_RULES,
                "max_thought_chains": MAX_THOUGHT_CHAINS,
                "max_name_chars": MAX_NAME_CHARS,
                "max_keyword_chars": MAX_KEYWORD_CHARS,
                "max_content_chars": MAX_CONTENT_CHARS,
            },
            "default_thought_rule": DEFAULT_THOUGHT_RULE,
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

    async def api_save_thoughts(self):
        """整体保存思维链列表（顺序与启用状态）。"""
        payload = await web_request.json(default={})
        if not isinstance(payload, dict):
            return {"ok": False, "error": "请求体必须是 JSON 对象"}

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
            example = item.get("example_thought")
            example = (
                example.strip()[:MAX_EXAMPLE_THOUGHT_CHARS]
                if isinstance(example, str)
                else ""
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

        ok, err = self._write_thought_chains(cleaned)
        if not ok:
            return {"ok": False, "error": f"保存失败: {err}"}

        logger.info(f"[{PLUGIN_NAME}] 思维链已保存（{len(cleaned)} 条）")
        return {"ok": True, "count": len(cleaned), "thought_chains": cleaned}

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
        """删除单条规则。

        幂等：id 不存在时也算删除成功。前端新建的规则可能在还没保存
        内容时就被删掉，这时配置里根本没有它，不该报错。
        """
        payload = await web_request.json(default={})
        rule_id = str((payload or {}).get("id") or "").strip()
        if not rule_id:
            return {"ok": False, "error": "缺少 id"}

        rules = self._load_rules()
        remaining = [r for r in rules if r["id"] != rule_id]

        if len(remaining) == len(rules):
            # 本来就不在配置里，直接返回成功
            return {"ok": True, "rules": rules}

        ok, err = self._write_rules(remaining)
        if not ok:
            return {"ok": False, "error": f"删除失败: {err}"}

        logger.info(f"[{PLUGIN_NAME}] 已删除规则 {rule_id}")
        return {"ok": True, "rules": remaining}

    # ---------------------------------------------------------------- 思维链

    def _write_thought_chains(self, chains: list[dict]) -> tuple[bool, str]:
        """写思维链列表到配置并持久化。"""
        updates = {"thought_chains": chains}
        try:
            self.config.save_config(updates)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[{PLUGIN_NAME}] 保存思维链失败: {exc}")
            return False, str(exc)
        for key, value in updates.items():
            self.config[key] = value
        return True, ""

    async def api_save_thought(self):
        """保存单条思维链（新增或更新）。"""
        payload = await web_request.json(default={})
        if not isinstance(payload, dict):
            return {"ok": False, "error": "请求体必须是 JSON 对象"}

        content = payload.get("content")
        if not isinstance(content, str):
            return {"ok": False, "error": "content 必须是字符串"}
        if len(content) > MAX_CONTENT_CHARS:
            return {"ok": False, "error": f"内容超过 {MAX_CONTENT_CHARS} 字符"}
        example = payload.get("example_thought")
        example = (
            example.strip()[:MAX_EXAMPLE_THOUGHT_CHARS]
            if isinstance(example, str)
            else ""
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

        chains = self._load_thought_chains()
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

        ok, err = self._write_thought_chains(chains)
        if not ok:
            return {"ok": False, "error": f"保存失败: {err}"}

        logger.info(f"[{PLUGIN_NAME}] 已保存思维链「{name}」（关键词 {keyword}）")
        return {"ok": True, "id": chain_id, "thought_chains": chains}

    async def api_delete_thought(self):
        """删除单条思维链。幂等：id 不存在时也返回成功。"""
        payload = await web_request.json(default={})
        chain_id = str((payload or {}).get("id") or "").strip()
        if not chain_id:
            return {"ok": False, "error": "缺少 id"}

        chains = self._load_thought_chains()
        remaining = [c for c in chains if c["id"] != chain_id]

        if len(remaining) == len(chains):
            return {"ok": True, "thought_chains": chains}

        ok, err = self._write_thought_chains(remaining)
        if not ok:
            return {"ok": False, "error": f"删除失败: {err}"}

        logger.info(f"[{PLUGIN_NAME}] 已删除思维链 {chain_id}")
        return {"ok": True, "thought_chains": remaining}

    async def terminate(self):
        """插件卸载时调用。"""
        logger.info(f"[{PLUGIN_NAME}] 已卸载")
