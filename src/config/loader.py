"""配置加载器：从 YAML 文件加载配置，支持环境变量覆盖。"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv


class ConfigError(Exception):
    """配置相关错误。"""

    pass


class ConfigLoader:
    """加载和校验 config.yaml。"""

    def __init__(self, config_path: str | Path = "config.yaml"):
        self.config_path = Path(config_path)
        self._config: dict = {}
        self._load()

    # ── 公开方法 ──────────────────────────────────────────

    def get_api_config(self) -> dict:
        """返回 API 配置（api_key 已被环境变量覆盖）。"""
        api = self._require_section("api")
        api_key = os.getenv("DEEPSEEK_API_KEY") or api.get("api_key", "")
        if not api_key:
            raise ConfigError(
                "api_key 未设置。请在 config.yaml 中设置 api.api_key，"
                "或设置环境变量 DEEPSEEK_API_KEY"
            )
        return {
            "base_url": api.get("base_url", "https://api.deepseek.com"),
            "api_key": api_key,
            "model": api.get("model", "deepseek-chat"),
            "max_tokens": api.get("max_tokens", 1024),
            "temperature": api.get("temperature", 0.9),
            "top_p": api.get("top_p", 0.95),
        }

    def get_persona_config(self) -> dict:
        """返回人设配置。"""
        persona = self._require_section("persona")
        name = persona.get("name", "").strip()
        if not name:
            raise ConfigError("persona.name 不能为空")
        return {
            "name": name,
            "avatar": persona.get("avatar", "💕"),
            "age": persona.get("age", 20),
            "personality": persona.get("personality", "").strip(),
            "speaking_style": persona.get("speaking_style", {}),
        }

    def get_chat_config(self) -> dict:
        """返回聊天设置。"""
        chat = self._config.get("chat", {})
        return {
            "max_history_turns": chat.get("max_history_turns", 20),
        }

    def get_rag_config(self) -> dict:
        """返回 RAG 检索增强配置。若未配置则返回 disabled 默认值。"""
        rag = self._config.get("rag", {})
        return {
            "enabled": rag.get("enabled", False),
            "chroma_db_path": rag.get("chroma_db_path", "data/chroma_db"),
            "embedding_model": rag.get(
                "embedding_model",
                "paraphrase-multilingual-MiniLM-L12-v2",
            ),
            "n_results": rag.get("n_results", 5),
            "similarity_threshold": rag.get("similarity_threshold", 0.4),
        }

    # ── 内部方法 ──────────────────────────────────────────

    def _load(self):
        """加载 YAML 和 .env 文件。"""
        # 尝试加载 .env（在项目根目录）
        env_path = self.config_path.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)

        if not self.config_path.exists():
            raise ConfigError(
                f"配置文件不存在: {self.config_path}\n"
                f"请复制 config.example.yaml 为 config.yaml 并填入你的设置"
            )

        with open(self.config_path, "r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f) or {}

    def _require_section(self, name: str) -> dict:
        section = self._config.get(name)
        if not section:
            raise ConfigError(f"配置文件中缺少 [{name}] 节")
        return section


# ── 自测 ──────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Windows 终端 UTF-8 支持
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    print(f"加载配置: {config_path}")
    loader = ConfigLoader(config_path)

    print("\n── API 配置 ──")
    api = loader.get_api_config()
    for k, v in api.items():
        if k == "api_key":
            v = v[:8] + "..." if len(v) > 8 else v
        print(f"  {k}: {v}")

    print("\n── 人设配置 ──")
    persona = loader.get_persona_config()
    for k, v in persona.items():
        if k == "personality":
            v = v[:60] + "..." if len(v) > 60 else v
        elif k == "speaking_style":
            v = f"tone={v.get('tone')}, habits={len(v.get('habits', []))}条"
        print(f"  {k}: {v}")

    print("\n── 聊天设置 ──")
    chat = loader.get_chat_config()
    for k, v in chat.items():
        print(f"  {k}: {v}")

    print("\n✅ 配置加载成功！")
