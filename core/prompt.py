# -*- coding: utf-8 -*-
"""规则块与少样本示例的统一拼装，注入与 Web 预览共用。"""

from .constants import DEFAULT_EXAMPLE_REPLY, DEFAULT_EXAMPLE_USER


class PromptMixin:
    """负责把配置快照拼成注入内容的 mixin。"""

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
            # 无可注入内容时两部分都为空
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
