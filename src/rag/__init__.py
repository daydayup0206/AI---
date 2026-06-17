"""RAG 模块：基于 ChromaDB 的真实对话检索增强生成。

提供从真实微信聊天记录中检索相似对话、作为 LLM 风格参考的能力。
"""

from .embedder import Embedder
from .indexer import DialogueIndexer
from .retriever import DialogueRetriever
from .context import RAGContextBuilder

__all__ = ["Embedder", "DialogueIndexer", "DialogueRetriever", "RAGContextBuilder"]
