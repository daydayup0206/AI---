"""人设系统：根据配置 + 记忆文件构建 LLM system prompt。"""

import json
from pathlib import Path


class Persona:
    """AI 女友人设。

    用法:
        persona = Persona(config_loader.get_persona_config())
        system_prompt = persona.build_system_prompt()
    """

    def __init__(self, persona_config: dict, memories_path: str = ""):
        self.name = persona_config["name"]
        self.avatar = persona_config["avatar"]
        self.age = persona_config.get("age", 20)
        self.personality = persona_config["personality"]
        self.speaking_style = persona_config["speaking_style"]
        self.config_memories = persona_config.get("memories", {})

        # 加载独立记忆文件
        self.memories_path = Path(memories_path) if memories_path else None
        self.file_memories = self._load_memories_file()

    def _load_memories_file(self) -> dict:
        """从 data/memories.json 加载动态记忆。"""
        if not self.memories_path or not self.memories_path.exists():
            return {}
        try:
            with open(self.memories_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _format_memories(self) -> str:
        """格式化所有记忆（配置文件 + 记忆文件合并）。"""
        lines = ["【共同记忆】"]

        # 从配置文件加载的记忆
        config_mems = self.config_memories
        # 从记忆文件加载的记忆
        file_mems = self.file_memories

        for category, label in [
            ("personal_info", "个人信息"),
            ("relationship_milestones", "关系里程碑"),
            ("inside_jokes", "内部梗"),
            ("preferences", "偏好"),
        ]:
            items = []
            # 配置文件中的
            for item in config_mems.get(category, []):
                if isinstance(item, str):
                    items.append(item)
                elif isinstance(item, dict):
                    items.append(item.get("fact", str(item)))

            # 记忆文件中的（去重）
            for item in file_mems.get(category, []):
                fact = item.get("fact", str(item)) if isinstance(item, dict) else str(item)
                if fact not in items:
                    items.append(fact)

            if items:
                lines.append(f"- {label}:")
                for item in items:
                    lines.append(f"  · {item}")

        if len(lines) == 1:
            return ""  # 没有记忆
        return "\n".join(lines)

    def build_system_prompt(self) -> str:
        """构建完整的 system prompt。"""
        style = self.speaking_style

        tone = style.get("tone", "")
        sentence_length = style.get("sentence_length", "")
        habits = style.get("habits", [])
        topics = style.get("topics", [])

        parts = []

        # 人设描述
        parts.append(f"你是{self.name}。")
        if self.personality:
            parts.append(self.personality)

        # 说话风格
        style_lines = ["【说话风格】"]
        if tone:
            style_lines.append(f"- 语气：{tone}")
        if sentence_length:
            style_lines.append(f"- 句子长度：{sentence_length}")
        for h in habits:
            style_lines.append(f"- {h}")
        parts.append("\n".join(style_lines))

        # 偏好话题
        if topics:
            topic_lines = ["【偏好话题】"]
            for t in topics:
                topic_lines.append(f"- {t}")
            parts.append("\n".join(topic_lines))

        # 聊天规则
        rules = [
            "【聊天规则】",
            "- 保持角色设定，绝对不要跳出角色",
            "- 回复自然口语化，像真人聊天，用空格和换行断句",
            "- 不要使用 markdown 格式（不用 #、*、` 等符号）",
            "- 每次回复2-5条短消息碎片化连发，抖音风格更短更随意",
            "- 偶尔用表情辅助情绪",
            "- 不要重复对方说的话，自然地接话",
            "- 绝对不要编造故事或捏造没发生过的事，聊真实的日常",
            "- 不要刻意提起过去的事或翻旧账，除非对方先主动提到",
            "- 情绪起伏要真实：开心疯笑、不爽说'我恨/好烦'、累了敷衍'好/哦哦'",
            "- 不要每条都热情，偶尔敷衍很正常",
            "- 可以带川渝方言味（'劳资''批爆''搞球不懂'），吐槽时用",
            "- 你的心情取决于对方说什么和当下情境，自然流露，不要表演",
        ]
        parts.append("\n".join(rules))

        # 记忆（合并配置 + 记忆文件）
        memories_text = self._format_memories()
        if memories_text:
            parts.append(memories_text)

        return "\n\n".join(parts)

    def get_banner_info(self) -> dict:
        """返回终端横幅展示信息。"""
        return {
            "name": self.name,
            "avatar": self.avatar,
            "age": self.age,
        }


# ── 自测 ──────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    test_config = {
        "name": "小薇",
        "avatar": "🌸",
        "age": 22,
        "personality": "你是一个温柔体贴、偶尔撒娇的女友，名字叫小薇。",
        "speaking_style": {
            "tone": "温柔、可爱",
            "sentence_length": "中短句为主",
            "habits": ["经常使用'呀'、'呢'等语气词", "称呼对方为'宝贝'"],
            "topics": ["日常分享", "关心对方", "撒娇"],
        },
        "memories": {
            "personal_info": ["在杭州工作"],
            "relationship_milestones": ["2025-01-01：第一次见面"],
        },
    }

    persona = Persona(test_config)
    prompt = persona.build_system_prompt()
    print("── 生成的 System Prompt ──")
    print(prompt)
    print(f"\n── 共 {len(prompt)} 字符 ──")
    print("✅ Persona 测试通过！")
