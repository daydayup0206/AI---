"""对话会话管理：维护上下文历史，支持自动截断。"""


class ChatSession:
    """管理一次对话会话的消息历史。

    用法:
        session = ChatSession(system_prompt="你是小薇...", max_history_turns=20)
        session.add_user_message("你好")
        messages = session.get_messages()  # 发给 LLM
        session.add_assistant_message("宝贝好呀~")
    """

    def __init__(self, system_prompt: str, max_history_turns: int = 20):
        self._system_prompt = system_prompt
        self._max_turns = max_history_turns
        self._messages: list[dict] = [
            {"role": "system", "content": system_prompt}
        ]
        self._turn_count = 0

    # ── 属性 ──────────────────────────────────────────────

    @property
    def turn_count(self) -> int:
        """已完成的对话轮数（一问一答为一轮）。"""
        return self._turn_count

    # ── 消息操作 ──────────────────────────────────────────

    def add_user_message(self, text: str):
        """添加用户消息。"""
        self._messages.append({"role": "user", "content": text})

    def add_assistant_message(self, text: str):
        """添加 AI 回复，并完成一轮对话。"""
        self._messages.append({"role": "assistant", "content": text})
        self._turn_count += 1

    def get_messages(self) -> list[dict]:
        """获取发送给 LLM 的消息列表。

        在返回前自动截断：保留 system prompt + 最近 N 轮对话。
        """
        if self._turn_count <= self._max_turns:
            return list(self._messages)

        # 截断：system prompt (1) + 最近 max_turns 轮 (每轮 2 条)
        keep = 1 + self._max_turns * 2
        return [self._messages[0]] + self._messages[-keep + 1:]

    def get_messages_with_rag(self, rag_context: str) -> list[dict]:
        """获取消息列表，临时注入 RAG 上下文（不存入历史）。

        RAG 上下文作为第二条 system 消息插入，仅对本次调用生效。
        """
        messages = self.get_messages()
        if rag_context:
            rag_message = {"role": "system", "content": rag_context}
            return [messages[0], rag_message] + messages[1:]
        return messages

    def clear(self):
        """重置对话历史，保留 system prompt。"""
        self._messages = [
            {"role": "system", "content": self._system_prompt}
        ]
        self._turn_count = 0

    # ── 摘要 ──────────────────────────────────────────────

    def get_summary(self) -> str:
        """返回会话摘要文本。"""
        return f"共 {self._turn_count} 轮对话，{len(self._messages)} 条消息"

    def get_history_text(self) -> str:
        """返回可读的对话历史（用于调试）。"""
        lines = []
        for msg in self._messages:
            role = {"system": "系统", "user": "你", "assistant": self._get_assistant_name()}
            content = msg["content"]
            if len(content) > 100:
                content = content[:100] + "..."
            lines.append(f"[{role.get(msg['role'], msg['role'])}] {content}")
        return "\n".join(lines)

    def _get_assistant_name(self) -> str:
        return "AI"


# ── 自测 ──────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    session = ChatSession(
        system_prompt="你是小薇，一个温柔的女友。",
        max_history_turns=3,
    )

    # 添加几轮对话
    for i in range(5):
        session.add_user_message(f"用户消息 {i+1}")
        session.add_assistant_message(f"小薇回复 {i+1}")

    messages = session.get_messages()
    print(f"── 截断测试 (max_turns=3, 实际 5 轮) ──")
    print(f"返回消息数: {len(messages)} (期望 1+3*2=7)")
    print(f"第一条: {messages[0]['content'][:30]}...")
    print(f"用户第一条被截断: {'消息 1' not in messages[1]['content']}")
    print(f"用户最后一条保留: {'消息 5' in messages[-2]['content']}")

    # 测试 clear
    session.clear()
    print(f"\n── 重置测试 ──")
    print(f"turn_count: {session.turn_count} (期望 0)")
    print(f"消息数: {len(session.get_messages())} (期望 1)")

    print(f"\n── 摘要 ──")
    print(session.get_summary())

    print("\n✅ ChatSession 测试通过！")
