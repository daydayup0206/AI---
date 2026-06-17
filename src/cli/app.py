"""AI女友 CLI 聊天应用。"""

import re
import sys
from pathlib import Path

# 确保 src 在 path 中（支持从任意目录运行）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.config.loader import ConfigLoader, ConfigError
from src.llm.client import (
    DeepSeekClient,
    DeepSeekError,
    DeepSeekAuthError,
    DeepSeekRateLimitError,
    DeepSeekConnectionError,
    DeepSeekAPIError,
)
from src.personality.persona import Persona
from src.chat.session import ChatSession
from src.rag.embedder import Embedder
from src.rag.retriever import DialogueRetriever
from src.rag.context import RAGContextBuilder


# ── 终端颜色（ANSI） ─────────────────────────────────────

class Colors:
    RESET = "\033[0m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    DIM = "\033[2m"


# ── 横幅 ──────────────────────────────────────────────────

WELCOME_BANNER = r"""
╔══════════════════════════════════╗
║    {avatar} {name} - 你的AI女友{' ' * (17 - len(name))}║
║    输入 /help 查看可用命令       ║
╚══════════════════════════════════╝
"""

HELP_TEXT = f"""
{Colors.YELLOW}可用命令:{Colors.RESET}
  {Colors.CYAN}/help{Colors.RESET}     显示此帮助信息
  {Colors.CYAN}/persona{Colors.RESET}  查看当前人设信息
  {Colors.CYAN}/clear{Colors.RESET}    重置对话（清除上下文）
  {Colors.CYAN}/exit{Colors.RESET}     退出聊天
{Colors.DIM}  Ctrl+C      退出聊天{Colors.RESET}
"""


# ── 主应用 ────────────────────────────────────────────────

class CLIApp:
    """CLI 聊天应用。"""

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.session: ChatSession | None = None
        self.client: DeepSeekClient | None = None
        self.persona: Persona | None = None
        self.retriever: DialogueRetriever | None = None
        self.rag_builder = RAGContextBuilder()
        self._rag_enabled = False
        self._running = False

    def run(self):
        """启动 CLI 聊天循环。"""
        try:
            self._init()
        except ConfigError as e:
            self._print_error(f"配置错误: {e}")
            sys.exit(1)
        except DeepSeekAuthError as e:
            self._print_error(str(e))
            sys.exit(1)
        except DeepSeekError as e:
            self._print_error(f"API 连接失败: {e}")
            sys.exit(1)

        self._show_welcome()
        self._chat_loop()

    # ── 初始化 ──────────────────────────────────────────

    def _init(self):
        """加载配置，初始化各组件。"""
        loader = ConfigLoader(self.config_path)

        api = loader.get_api_config()
        persona_cfg = loader.get_persona_config()
        chat_cfg = loader.get_chat_config()
        rag_cfg = loader.get_rag_config()

        self.client = DeepSeekClient(
            api_key=api["api_key"],
            base_url=api["base_url"],
            model=api["model"],
            temperature=api["temperature"],
            max_tokens=api["max_tokens"],
            top_p=api["top_p"],
        )

        self.persona = Persona(persona_cfg)
        system_prompt = self.persona.build_system_prompt()
        self.session = ChatSession(system_prompt, chat_cfg["max_history_turns"])

        # 初始化 RAG 检索（可选，非阻塞）
        self._rag_enabled = rag_cfg["enabled"]
        if self._rag_enabled:
            try:
                embedder = Embedder(model_name=rag_cfg["embedding_model"])
                self.retriever = DialogueRetriever(
                    embedder=embedder,
                    chroma_path=rag_cfg["chroma_db_path"],
                    n_results=rag_cfg["n_results"],
                    similarity_threshold=rag_cfg["similarity_threshold"],
                )
                if self.retriever.is_ready:
                    print(f"  RAG: 已就绪（{rag_cfg['n_results']}条相似对话参考）")
                else:
                    print(f"  RAG: 索引未就绪，运行 python scripts/build_index.py 构建")
            except Exception as e:
                print(f"  RAG: 初始化失败 ({e})，以无参考模式运行")
                self.retriever = None

    # ── 聊天循环 ────────────────────────────────────────

    def _chat_loop(self):
        """主聊天循环。"""
        self._running = True
        while self._running:
            try:
                # 读取用户输入
                user_input = input(f"\n{Colors.CYAN}你 > {Colors.RESET}")
            except (EOFError, KeyboardInterrupt):
                self._handle_exit()
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # 处理命令
            if user_input.startswith("/"):
                self._handle_command(user_input)
                continue

            # 正常聊天
            self._handle_chat(user_input)

    # ── 聊天处理 ────────────────────────────────────────

    def _handle_chat(self, text: str):
        """处理一条用户消息。"""
        self.session.add_user_message(text)

        # RAG 检索：从真实聊天记录中找相似对话
        rag_context = ""
        if self.retriever is not None:
            try:
                results = self.retriever.retrieve(text)
                if results:
                    rag_context = self.rag_builder.format(results)
                    if rag_context:
                        print(
                            f"{Colors.DIM}  📎 匹配到 {len(results)} 条相似对话"
                            f"{Colors.RESET}"
                        )
            except Exception:
                pass  # RAG 失败不阻塞聊天

        messages = self.session.get_messages_with_rag(rag_context)

        # 显示 AI 正在输入
        prompt_name = self.persona.name
        print(f"{Colors.MAGENTA}{prompt_name} > {Colors.RESET}", end="", flush=True)

        full_reply = ""
        try:
            # 流式收集完整回复（不在终端逐字打印，避免打一半删了的问题）
            for chunk in self.client.chat(messages, stream=True):
                full_reply += chunk
        except KeyboardInterrupt:
            print(f"\n{Colors.DIM}(已中断){Colors.RESET}")
            if full_reply:
                self.session.add_assistant_message(full_reply + " [interrupted]")
            return
        except DeepSeekRateLimitError as e:
            self._print_error(f"频率限制: {e}")
            return
        except DeepSeekError as e:
            self._print_error(f"API 错误: {e}")
            return

        # 过滤掉可能导致终端显示异常的控制字符
        full_reply = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', full_reply)

        # 一次性打印完整回复，避免流式打印的显示问题
        print(full_reply)

        self.session.add_assistant_message(full_reply)

    # ── 命令处理 ────────────────────────────────────────

    def _handle_command(self, cmd: str):
        """处理 / 开头的命令。"""
        cmd = cmd.lower()

        if cmd in ("/exit", "/quit", "/q"):
            self._handle_exit()

        elif cmd == "/help":
            print(HELP_TEXT)

        elif cmd == "/persona":
            info = self.persona.get_banner_info()
            print(f"\n{Colors.YELLOW}── 当前人设 ──{Colors.RESET}")
            print(f"  名字: {info['name']}")
            print(f"  头像: {info['avatar']}")
            print(f"  年龄: {info['age']}")
            print(f"  轮次: {self.session.turn_count}")

        elif cmd == "/clear":
            self.session.clear()
            print(f"{Colors.GREEN}✅ 对话已重置，{self.persona.name}不记得之前聊了什么了~{Colors.RESET}")

        else:
            print(f"{Colors.RED}未知命令: {cmd}{Colors.RESET}")
            print(f"输入 {Colors.CYAN}/help{Colors.RESET} 查看可用命令")

    def _handle_exit(self):
        """退出处理。"""
        self._running = False
        summary = self.session.get_summary() if self.session else "0 轮对话"
        print(f"\n{Colors.GREEN}👋 再见！本次会话: {summary}{Colors.RESET}")

    # ── 显示 ────────────────────────────────────────────

    def _show_welcome(self):
        """显示欢迎横幅。"""
        info = self.persona.get_banner_info()
        # 手动填充中文字符（中文字符占 2 列）
        name_len = len(info["name"].encode("utf-8"))  # 中文字符算 3 字节
        # 用简单方式估算：ASCII 算 1，其他算 2
        display_width = sum(2 if ord(c) > 127 else 1 for c in info["name"])
        padding = max(0, 17 - display_width)
        banner = WELCOME_BANNER.format(
            avatar=info["avatar"],
            name=info["name"],
        )
        # 调整空格填充
        banner = banner.replace(
            f"你的AI女友{' ' * (17 - len(info['name']))}║",
            f"你的AI女友{' ' * padding}║",
        )
        print(banner)

    def _print_error(self, msg: str):
        """输出错误消息。"""
        print(f"\n{Colors.RED}❌ {msg}{Colors.RESET}")


# ── 入口 ──────────────────────────────────────────────────

def main():
    """CLI 入口函数。"""
    # Windows 终端 UTF-8 支持
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    app = CLIApp(config_path)
    app.run()


if __name__ == "__main__":
    main()
