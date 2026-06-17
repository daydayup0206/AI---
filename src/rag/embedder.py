"""嵌入模型封装：基于 sentence-transformers，懒加载。"""

from sentence_transformers import SentenceTransformer


class Embedder:
    """文本嵌入器。

    用法:
        embedder = Embedder()
        vec = embedder.embed_single("你好")
        vecs = embedder.embed(["你好", "今天好累"])
    """

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self._model_name = model_name
        self._model: SentenceTransformer | None = None

    def _ensure_loaded(self):
        """懒加载模型（首次使用时加载，约 118MB）。"""
        if self._model is None:
            print(f"[*] 加载嵌入模型: {self._model_name}...")
            self._model = SentenceTransformer(self._model_name)
            print(f"[+] 模型加载完成")

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量文本嵌入，返回归一化向量列表。"""
        self._ensure_loaded()
        embeddings = self._model.encode(
            texts,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return embeddings.tolist()

    def embed_single(self, text: str) -> list[float]:
        """单条文本嵌入。"""
        return self.embed([text])[0]

    @property
    def is_loaded(self) -> bool:
        """模型是否已加载。"""
        return self._model is not None
