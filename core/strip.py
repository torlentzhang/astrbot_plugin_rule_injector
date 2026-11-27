# -*- coding: utf-8 -*-
"""发送前剥离思考区的正则逻辑。"""

import re


class StripMixin:
    """负责从模型输出中剥离思考区的 mixin。"""

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
        lone = re.match(r"\s*<\s*回复\s*/?\s*>", text, re.IGNORECASE)
        if lone:
            body = re.sub(r"^\s*<qq_message_id[^>]*>\s*", "", text[lone.end() :])
            return body.strip(), "reply_only"

        # 按配置顺序定位标签；自闭合 <kw/> 与旧开标签 <kw> 都认
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
