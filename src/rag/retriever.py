"""运行时对话检索器 v2：嵌入用户消息 → ChromaDB 查询 → 时间衰减排序。"""

import time as time_mod
from pathlib import Path
import chromadb

from .embedder import Embedder


class DialogueRetriever:
    """运行时检索服务（v2：时间衰减权重）。"""

    def __init__(
        self,
        embedder: Embedder,
        chroma_path: str = "data/chroma_db",
        collection_name: str = "chat_exchanges",
        n_results: int = 5,
        similarity_threshold: float = 0.4,
    ):
        self._embedder = embedder
        self._chroma_path = Path(chroma_path)
        self._collection_name = collection_name
        self._n_results = n_results
        self._similarity_threshold = similarity_threshold
        self._client: chromadb.PersistentClient | None = None
        self._collection = None

    @property
    def is_ready(self) -> bool:
        if not self._chroma_path.is_dir():
            return False
        try:
            return len(list(self._chroma_path.iterdir())) > 0
        except Exception:
            return False

    def _ensure_client(self):
        if self._client is None:
            try:
                self._client = chromadb.PersistentClient(path=str(self._chroma_path))
                self._collection = self._client.get_collection(self._collection_name)
            except Exception as e:
                self._client = None
                self._collection = None
                raise RuntimeError(f"ChromaDB 加载失败: {e}") from e

    def retrieve(self, user_message: str) -> list[dict]:
        if not self.is_ready:
            return []
        if not user_message or not user_message.strip():
            return []

        try:
            self._ensure_client()
        except RuntimeError:
            return []

        try:
            query_embedding = self._embedder.embed_single(user_message)
            # 检索 3 倍候选，再排序截断
            n_candidates = min(self._n_results * 3, self._collection.count())
            raw = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=n_candidates,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            return []

        results = []
        if not raw["ids"] or not raw["ids"][0]:
            return results

        now_ts = int(time_mod.time())

        for i, doc_id in enumerate(raw["ids"][0]):
            distance = raw["distances"][0][i] if raw["distances"] else 1.0
            similarity = 1.0 / (1.0 + distance)

            if similarity < self._similarity_threshold:
                continue

            metadata = raw["metadatas"][0][i] if raw["metadatas"] else {}
            ts = metadata.get("timestamp", 0)

            # 时间衰减权重
            time_weight = self._calc_time_weight(ts, now_ts)
            final_score = similarity * time_weight

            results.append({
                "user_text": metadata.get("user_text", raw["documents"][0][i]),
                "her_reply": metadata.get("her_reply", ""),
                "time": metadata.get("time", ""),
                "timestamp": ts,
                "source": metadata.get("source", ""),
                "similarity_score": round(similarity, 4),
                "time_weight": round(time_weight, 4),
                "final_score": round(final_score, 4),
            })

        # 按最终得分排序，截断
        results.sort(key=lambda r: r["final_score"], reverse=True)
        results = results[: self._n_results]

        return results

    @staticmethod
    def _calc_time_weight(timestamp: int, now_ts: int) -> float:
        """计算时间衰减权重。"""
        if timestamp <= 0:
            return 1.0
        age_days = (now_ts - timestamp) / 86400.0
        if age_days <= 7:
            return 1.20
        elif age_days <= 30:
            return 1.15
        elif age_days <= 90:
            return 1.10
        elif age_days <= 180:
            return 1.00
        else:
            return 0.90
