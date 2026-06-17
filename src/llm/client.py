"""DeepSeek API 客户端：封装 OpenAI SDK，支持流式和非流式调用。"""

from openai import OpenAI


# ── 自定义异常体系 ────────────────────────────────────────

class DeepSeekError(Exception):
    """DeepSeek 客户端通用错误。"""

    pass


class DeepSeekAuthError(DeepSeekError):
    """API Key 无效。"""

    pass


class DeepSeekRateLimitError(DeepSeekError):
    """请求频率超限。"""

    pass


class DeepSeekConnectionError(DeepSeekError):
    """网络连接失败。"""

    pass


class DeepSeekAPIError(DeepSeekError):
    """其他 API 错误。"""

    pass


# ── 客户端 ────────────────────────────────────────────────

class DeepSeekClient:
    """DeepSeek Chat API 客户端。

    用法:
        client = DeepSeekClient(api_key="sk-xxx", model="deepseek-chat")
        reply = client.chat([{"role": "user", "content": "你好"}])
        for chunk in client.chat(messages, stream=True):
            print(chunk, end="")
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        temperature: float = 0.9,
        max_tokens: int = 1024,
        top_p: float = 0.95,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p

        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(self, messages: list[dict], stream: bool = False):
        """发送消息，返回回复文本（非流式）或文本块生成器（流式）。

        Args:
            messages: [{"role": "system|user|assistant", "content": "..."}]
            stream: True 时返回生成器，逐块产出文本。

        Returns:
            str | Iterator[str]
        """
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                top_p=self.top_p,
                stream=stream,
            )

            if stream:
                return self._stream_response(response)
            else:
                return response.choices[0].message.content or ""

        except Exception as e:
            self._raise_error(e)

    def _stream_response(self, response):
        """处理流式响应，逐块产出 delta 文本。"""
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    def _raise_error(self, error: Exception):
        """将 OpenAI SDK 异常转换为自定义异常。"""
        from openai import (
            AuthenticationError,
            RateLimitError,
            APIConnectionError,
            APIError,
        )

        msg = str(error)

        if isinstance(error, AuthenticationError):
            raise DeepSeekAuthError(
                f"API Key 无效，请检查 DEEPSEEK_API_KEY 或 config.yaml 中的 api_key\n"
                f"原始错误: {msg}"
            ) from error
        elif isinstance(error, RateLimitError):
            raise DeepSeekRateLimitError(
                f"请求频率超限，请稍后重试\n原始错误: {msg}"
            ) from error
        elif isinstance(error, APIConnectionError):
            raise DeepSeekConnectionError(
                f"无法连接 DeepSeek API，请检查网络\n原始错误: {msg}"
            ) from error
        elif isinstance(error, APIError):
            raise DeepSeekAPIError(f"DeepSeek API 错误: {msg}") from error
        else:
            raise DeepSeekError(f"未知错误: {msg}") from error


# ── 自测 ──────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    import sys

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("⚠️  请先设置环境变量 DEEPSEEK_API_KEY")
        sys.exit(1)

    client = DeepSeekClient(api_key=api_key)

    # 非流式测试
    print("── 非流式测试 ──")
    reply = client.chat([{"role": "user", "content": "你好，用一句话介绍你自己"}])
    print(f"回复: {reply}")

    # 流式测试
    print("\n── 流式测试 ──")
    print("回复: ", end="", flush=True)
    for chunk in client.chat(
        [{"role": "user", "content": "说一句甜甜的话"}], stream=True
    ):
        print(chunk, end="", flush=True)
    print("\n\n✅ DeepSeekClient 测试通过！")
