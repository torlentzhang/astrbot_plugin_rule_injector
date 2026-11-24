# -*- coding: utf-8 -*-
"""把行为约束类规则按场景注入 system prompt。

on_llm_request 阶段把规则直接追加到 system_prompt，按场景区分。

规则存于配置文件的 rules 数组：
    [{"id": str, "name": str, "enabled": bool, "scope": "group|private|all", "content": str}]

思维链存于 thought_chains 数组，每条自带关键词，关键词决定输出时的开标签：
    [{"id": str, "name": str, "keyword": str, "enabled": bool, "content": str,
      "example_thought": str}]
输出格式要求每段用自闭合标签起头（<关键词/>），正文用 <回复/> 起头；发送前只把
<回复/> 之后的内容发给用户，思考区保留在会话历史里，模型下一轮仍看得到自己想过什么。
example_thought 是可选的示例念头，用来每轮动态拼一条少样本示例注入上下文，
让模型看到「上一次就是这么输出的」；留空时回退复用 content。

全局的 thought_example 存一问一答的示例场景（user / reply），与每段念头一起
拼成少样本：user / reply 留空时回退到内置的「在吗 / 嗯？怎么了」，保持兼容。

规则块与少样本由 _assemble 统一拼装；实际注入与 Web 预览共用它，预览按
前端草稿渲染，不改动已保存配置。
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
MAX_EXAMPLE_USER_CHARS = 500
MAX_EXAMPLE_REPLY_CHARS = 500
SCOPES = ("group", "private", "all")

# 用户没配置 thought_example 时的回退示例，与改前行为一致
DEFAULT_EXAMPLE_USER = "在吗"
DEFAULT_EXAMPLE_REPLY = "嗯？怎么了"

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
    "0.3.0",
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
        context.register_web_api(
            f"/{PLUGIN_NAME}/preview",
            self.api_preview,
            ["POST"],
            "预览规则与少样本示例的拼装结果",
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

    def _load_rules(self) -> list[dict]:
        """读规则列表。"""
        return self._normalize_rules(self.config.get("rules"))

    @staticmethod
    def _scene_of(event: AstrMessageEvent) -> str:
        """把事件映射成场景标识，注入与预览共用这一处口径。"""
        return "group" if RuleInjectorPlugin._is_group(event) else "private"

    def _snapshot(self) -> dict:
        """当前已保存配置的快照，供注入与预览共用。"""
        return {
            "rules": self._load_rules(),
            "thought_chains": self._load_thought_chains(),
            "thought_example": self._load_thought_example(),
        }

    def _assemble(self, snapshot: dict, scene: str) -> dict:
        """把配置快照拼成实际注入的两部分。

        系统提示词块与少样本示例都在这里生成，注入钩子与预览接口共用，
        保证「预览所见」就是「实际所发」。标签与格式按关键词动态生成，
        数量随启用的思维链变化。
        """
        chains = [
            c
            for c in snapshot.get("thought_chains", [])
            if c.get("enabled") and c["content"].strip()
        ]
        is_group = scene == "group"
        rules = [
            r
            for r in snapshot.get("rules", [])
            if r.get("enabled")
            and r["content"].strip()
            and (
                r["scope"] == "all"
                or (r["scope"] == "group") == is_group
            )
        ]

        blocks: list[str] = []
        if not chains:
            # 没有思维链时，规则原样拼上去即可
            blocks.extend(rule["content"].strip() for rule in rules)
        else:
            # 有思维链时：规则自成一个标题，「输出格式」另起一个标题，两者不混排
            if rules:
                blocks.append("# 行为规则")
                blocks.extend(rule["content"].strip() for rule in rules)

            # 按启用的思维链动态生成写作要求与最终格式，数量随配置变化
            lines = [
                "# 输出格式",
                "",
                "每次回复前，按顺序完成下列每一段思考，再输出正文。",
                "这些思考段是递进关系，不是可选项：后一段必须建立在前一段的结论之上；",
                "若各段结论有冲突，只在最后一段消化冲突，并只保留一个最终决定。",
                "你的回复必须是最后一段思考结论的自然表达，不得与之相矛盾。",
                "",
                "各段写作要求：",
            ]
            for chain in chains:
                lines.append(f"- {chain['keyword']}：{chain['content'].strip()}")
            lines.extend(
                [
                    "",
                    "最终格式（每段用一个自闭合标签起头，标签后直接写内容；不要写任何闭标签）：",
                ]
            )
            for chain in chains:
                kw = chain["keyword"]
                lines.append(f"<{kw}/>（写下这一段的思考）")
            lines.extend(
                [
                    "<回复/>你要发给用户的话",
                    "",
                    "【硬约束】",
                    "1. <回复/> 只写一次，且只在所有思考段写完后出现，它之后的内容才是正文。",
                    "2. 正文只表达最后一段定下的决定，不得引入与任一思考段矛盾的新立场。",
                ]
            )
            blocks.append("\n".join(lines))

        block = "\n\n".join(blocks)
        if not block:
            # 与原 inject_rules 的提前返回一致：无可注入内容时两部分都为空
            return {"system_prompt_block": "", "contexts": []}

        contexts: list[dict] = []
        if chains:
            example = snapshot.get("thought_example") or {}
            lines = []
            for chain in chains:
                thought = chain["example_thought"].strip() or chain["content"].strip()
                lines.append(f"<{chain['keyword']}/>{thought}")
            lines.append(f"<回复/>{example.get('reply') or DEFAULT_EXAMPLE_REPLY}")
            contexts = [
                {
                    "role": "user",
                    "content": example.get("user") or DEFAULT_EXAMPLE_USER,
                    "_no_save": True,
                },
                {"role": "assistant", "content": "\n".join(lines), "_no_save": True},
            ]

        return {"system_prompt_block": block, "contexts": contexts}

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

    def _load_thought_chains(self) -> list[dict]:
        """读思维链列表。"""
        return self._normalize_chains(self.config.get("thought_chains"))

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

    def _load_thought_example(self) -> dict:
        """读全局示例场景。"""
        return self._normalize_thought_example(self.config.get("thought_example"))

    def _strip_thought_text(
        self, text: str, chains: list[dict]
    ) -> tuple[str, str | None]:
        """剥掉一段文本里的思考区，返回 (正文, 命中方式)。

        命中方式：reply（<回复/> 自闭合标记）、reply_only（无思考段的孤立
        <回复/>）、marker（回复：标记）、closing（旧闭标签）、fallback（末段
        边界）、drop（无边界，整段丢弃）、None（没有思考区，原文返回）。
        """
        keywords = [c["keyword"] for c in chains]

        # 工具调用后的那一轮可能只输出 <回复/>正文，没有思考段。
        # 这种孤立标记也要剥掉，否则 <回复/> 会原样发给用户。
        lone = re.match(r"\s*<\s*回复\s*/?\s*>", text, re.IGNORECASE)
        if lone:
            body = re.sub(r"^\s*<qq_message_id[^>]*>\s*", "", text[lone.end() :])
            return body.strip(), "reply_only"

        # 按配置顺序定位标签；自闭合 <kw/> 与旧开标签 <kw> 都认，
        # 首标签前只能有空白，避免误判普通消息
        hits: list[tuple[int, int]] = []
        cursor = 0
        for kw in keywords:
            m = re.search(
                rf"<\s*{re.escape(kw)}\s*/?\s*>", text[cursor:], re.IGNORECASE
            )
            if m is None:
                return text, None
            hits.append((cursor + m.start(), cursor + m.end()))
            cursor += m.end()
        if text[: hits[0][0]].strip():
            return text, None

        tail = text[hits[-1][1] :]

        # 主路径：<回复/> 自闭合标记之后就是正文，兼容写成 <回复> 的情况
        reply = re.search(r"<\s*回复\s*/?\s*>", tail, re.IGNORECASE)
        if reply:
            body = tail[reply.end() :]
            body = re.sub(r"^\s*<qq_message_id[^>]*>\s*", "", body)
            return body.strip(), "reply"

        # 兼容上一版：最后一个标签之后的「回复：」是正文起点
        marker = re.search(r"(?m)^\s*回复\s*[：:]\s*", tail) or re.search(
            r"回复\s*[：:]\s*", tail
        )
        if marker:
            body = tail[marker.end() :]
            body = re.sub(r"^\s*<qq_message_id[^>]*>\s*", "", body)
            return body.strip(), "marker"

        # 兼容旧格式：成对或畸形闭标签仍能命中时直接剥掉
        out = text
        for kw in keywords:
            out = re.sub(
                rf"<\s*{re.escape(kw)}\s*>.*?<?\s*/?\s*{re.escape(kw)}\s*>",
                "",
                out,
                flags=re.DOTALL | re.IGNORECASE,
            )
        if out != text:
            out = re.sub(r"^\s*回复\s*[：:]\s*", "", out)
            return out.strip(), "closing"

        # 兜底：末段第一个「其后不是换行」的换行符当边界
        boundary = re.search(r"\n(?=[^\n])", tail)
        if boundary is None:
            return "", "drop"
        body = tail[boundary.end() :]
        body = re.sub(r"^\s*<qq_message_id[^>]*>\s*", "", body)
        return body.strip(), "fallback"

    # ---------------------------------------------------------------- 注入

    @filter.on_llm_request(priority=-1000)
    async def inject_rules(
        self, event: AstrMessageEvent, request: ProviderRequest
    ) -> None:
        """在 LLM 请求前注入规则与少样本示例。"""
        scene_key = self._scene_of(event)
        result = self._assemble(self._snapshot(), scene_key)
        block = result["system_prompt_block"]
        if not block:
            return

        base = (request.system_prompt or "").rstrip()
        request.system_prompt = f"{base}\n\n{block}" if base else block

        fewshot = result["contexts"]
        if fewshot:
            contexts = request.contexts
            if isinstance(contexts, list):
                contexts.extend(fewshot)

        scene = "群聊" if scene_key == "group" else "私聊"
        logger.info(
            f"[{PLUGIN_NAME}] 已注入规则（{scene}，{len(block)} 字符，"
            f"少样本示例 {len(fewshot)} 条）"
        )

    # ---------------------------------------------------------------- 剥离

    @filter.on_decorating_result()
    async def strip_thought(self, event: AstrMessageEvent) -> None:
        """发送前剥掉思考区，只把「回复：」之后的正文发出去。

        思考区本身要留在会话历史里，模型下一轮才看得到格式先例。
        """
        chains = [
            c
            for c in self._load_thought_chains()
            if c["enabled"] and c["content"].strip()
        ]
        if not chains:
            return

        result = event.get_result()
        if result is None or not result.chain:
            return

        stripped = False
        modes: set[str] = set()
        kept: list = []
        for comp in result.chain:
            if isinstance(comp, Plain):
                body, mode = self._strip_thought_text(comp.text, chains)
                if mode is not None:
                    stripped = True
                    modes.add(mode)
                    if not body:
                        continue
                    comp.text = body
            kept.append(comp)

        if not stripped:
            return

        if kept:
            result.chain = kept
        else:
            # 整条回复只有思考区，没有正文，不发送
            event.set_result(None)

        scene = "群聊" if self._is_group(event) else "私聊"
        logger.info(
            f"[{PLUGIN_NAME}] 已剥离思考区（{scene}，方式：{'/'.join(sorted(modes))}）"
        )

    # ---------------------------------------------------------------- Web API

    async def api_get_config(self):
        """读取当前配置。"""
        return {
            "rules": self._load_rules(),
            "thought_chains": self._load_thought_chains(),
            "thought_example": self._load_thought_example(),
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
        """预览实际注入的两部分；只读，不改变已保存的配置。

        前端可传入未保存的草稿，预览按草稿渲染，source 标明内容来源。
        """
        payload = await web_request.json(default={})
        if not isinstance(payload, dict):
            return {"ok": False, "error": "请求体必须是 JSON 对象"}

        scene = payload.get("scene")
        if scene not in ("group", "private"):
            return {"ok": False, "error": "scene 必须是 group 或 private"}

        snapshot = self._snapshot()
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
            "scene": scene,
            "source": source,
            "system_prompt_block": result["system_prompt_block"],
            "contexts": result["contexts"],
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
        """整体保存思维链列表，以及同一页的示例场景（原子写入）。"""
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

        example = None
        if "thought_example" in payload:
            raw_example = payload["thought_example"]
            if not isinstance(raw_example, dict):
                return {"ok": False, "error": "thought_example 必须是 JSON 对象"}
            example = {
                "user": self._clean_example(
                    raw_example.get("user"), MAX_EXAMPLE_USER_CHARS
                ),
                "reply": self._clean_example(
                    raw_example.get("reply"), MAX_EXAMPLE_REPLY_CHARS
                ),
            }

        ok, err = self._write_thought_chains(cleaned, example)
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

    def _write_thought_chains(
        self, chains: list[dict], example: dict | None = None
    ) -> tuple[bool, str]:
        """写思维链列表到配置并持久化；example 非空时一并落盘。"""
        updates: dict = {"thought_chains": chains}
        if example is not None:
            updates["thought_example"] = example
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
