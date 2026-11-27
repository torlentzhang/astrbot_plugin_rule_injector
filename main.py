# -*- coding: utf-8 -*-
"""按 AstrBot 配置文件注入行为约束规则与思维链。

每个配置文件（cmd_config.json 或 abconf_<uuid>.json）拥有独立的一套规则、
思维链和示例场景，存于插件配置的 profiles 字典里，以配置文件文件名做 key。
on_llm_request 阶段按当前会话绑定的配置文件取桶，注入对应规则；未绑定的会话
走默认配置文件（cmd_config.json）。配置文件之间没有回退：某配置文件没配规则就不注入。

规则数组结构：
    [{"id": str, "name": str, "enabled": bool, "scope": "group|private|all", "content": str}]

思维链存于 thought_chains 数组，每条自带关键词，关键词决定输出时的开标签：
    [{"id": str, "name": str, "keyword": str, "enabled": bool, "content": str,
      "example_thought": str}]
输出格式要求每段用自闭合标签起头（<关键词/>），正文用 <回复/> 起头；发送前只把
<回复/> 之后的内容发给用户，思考区保留在会话历史里，模型下一轮仍看得到自己想过什么。

全局的 thought_example 存一问一答的示例场景（user / reply），与每段念头一起
拼成少样本；user / reply 留空时回退到内置的「在吗 / 嗯？怎么了」。

规则块与少样本由 _assemble 统一拼装；实际注入与 Web 预览共用它，预览按
前端草稿渲染，不改动已保存配置。

从旧版升级时，顶层 rules / thought_chains / thought_example 一次性迁移到
当前实际在用的配置文件桶，迁移标记落盘后不再重复。
"""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig

from .api.handlers import ApiHandlersMixin
from .core.constants import PLUGIN_NAME
from .core.prompt import PromptMixin
from .core.store import StoreMixin
from .core.strip import StripMixin


@register(
    PLUGIN_NAME,
    "local",
    "按配置文件注入行为约束规则与思维链",
    "0.4.0",
)
class RuleInjectorPlugin(
    StoreMixin, PromptMixin, StripMixin, ApiHandlersMixin, Star
):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        context.register_web_api(
            f"/{PLUGIN_NAME}/profiles",
            self.api_get_profiles,
            ["GET"],
            "读取配置文件列表",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/config",
            self.api_get_config,
            ["GET"],
            "读取指定配置文件的规则配置",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/config",
            self.api_save_config,
            ["POST"],
            "保存指定配置文件的规则配置",
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
        self._migrate_legacy()
        logger.info(f"[{PLUGIN_NAME}] 已加载")

    # ---------------------------------------------------------------- 注入

    @filter.on_llm_request(priority=-1000)
    async def inject_rules(
        self, event: AstrMessageEvent, request: ProviderRequest
    ) -> None:
        """在 LLM 请求前按当前会话的配置文件注入规则与少样本示例。"""
        profile_key = self._profile_key_of(event)
        scene_key = self._scene_of(event)
        result = self._assemble(self._snapshot(profile_key), scene_key)
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
            f"[{PLUGIN_NAME}] 已注入规则（配置文件 {profile_key}，{scene}，"
            f"{len(block)} 字符，少样本示例 {len(fewshot)} 条）"
        )

    # ---------------------------------------------------------------- 剥离

    @filter.on_decorating_result()
    async def strip_thought(self, event: AstrMessageEvent) -> None:
        """发送前剥掉思考区，只把正文发出去。

        思考区本身要留在会话历史里，模型下一轮才看得到格式先例。
        """
        profile_key = self._profile_key_of(event)
        chains = [
            c
            for c in self._normalize_chains(
                self._bucket(profile_key).get("thought_chains")
            )
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
            f"[{PLUGIN_NAME}] 已剥离思考区（配置文件 {profile_key}，{scene}，"
            f"方式：{'/'.join(sorted(modes))}）"
        )

    async def terminate(self):
        """插件卸载时调用。"""
        logger.info(f"[{PLUGIN_NAME}] 已卸载")
