"""RAG 上下文格式化：将检索结果转为 LLM prompt 文本。"""


class RAGContextBuilder:
    """将 ChromaDB 检索结果格式化为 prompt 文本。

    用法:
        builder = RAGContextBuilder()
        prompt = builder.format(results, max_examples=5)
    """

    def format(
        self,
        results: list[dict],
        max_examples: int = 5,
        max_reply_chars: int = 150,
    ) -> str:
        """格式化检索结果为 prompt 文本。

        Args:
            results: retriever.retrieve() 的输出
            max_examples: 最多显示几个例子
            max_reply_chars: 每条回复最多截取字符数

        Returns:
            格式化的 prompt 文本；结果为空时返回 ""
        """
        if not results:
            return ""

        examples = results[:max_examples]
        lines = [
            "【真实对话参考】",
            "以下是她在类似情境下的真实回复，仅供参考她的说话方式、语气和表达习惯。",
            "⚠️ 重要：这只是风格参考，不要照搬内容，不要编造没发生过的故事，仍然要自然地回应对方当前说的话。",
            "",
        ]

        for i, r in enumerate(examples):
            short_time = self._short_time(r.get("time", ""))
            source = r.get("source", "")
            src_tag = {"wechat": "微信", "douyin": "抖音"}.get(source, source)
            user_text = self._truncate(r.get("user_text", ""), max_reply_chars)
            her_reply = self._truncate(r.get("her_reply", ""), max_reply_chars)

            lines.append(f"例{i + 1}（{short_time} {src_tag}）：")
            lines.append(f"对方说：「{user_text}」")
            lines.append(f"她回复：「{her_reply}」")
            lines.append("")

        return "\n".join(lines)

    # ── 工具方法 ──────────────────────────────────────────

    @staticmethod
    def _short_time(time_str: str) -> str:
        """截短时间显示。"""
        if not time_str:
            return ""
        # "2025-09-24 10:43:21" → "2025-09-24"
        parts = time_str.split(" ")
        if parts:
            return parts[0]
        return time_str

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        """截断过长文本。"""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "..."
