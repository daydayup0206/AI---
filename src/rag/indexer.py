"""对话索引器 v2：双数据源（微信+抖音） + 时间权重。"""

import json
import time as time_mod
from datetime import datetime
from pathlib import Path
import chromadb

from .embedder import Embedder


class DialogueIndexer:
    """一次性建库索引器。

    支持微信 JSONL（role: me/them）和抖音 ChatLab JSONL。
    每条对话对标记数据源和时间戳，检索时支持时间衰减。
    """

    def __init__(self, embedder: Embedder):
        self.embedder = embedder

    def build(
        self,
        wechat_path: str,
        douyin_path: str | None,
        chroma_path: str,
        collection_name: str = "chat_exchanges",
        batch_size: int = 500,
    ) -> int:
        print("=" * 50)
        print("   对话索引 v2 — 微信 + 抖音")
        print("=" * 50)

        all_pairs = []

        # ── 微信数据 ──
        if Path(wechat_path).exists():
            print(f"\n[*] 微信: {wechat_path}")
            wx_entries = self._load_jsonl(wechat_path)
            wx_pairs = self._pair_wechat(wx_entries)
            for p in wx_pairs:
                p["source"] = "wechat"
            all_pairs.extend(wx_pairs)
            print(f"    配对 {len(wx_pairs)} 个对话对")
        else:
            print(f"\n[!] 微信数据不存在: {wechat_path}")

        # ── 抖音数据 ──
        if douyin_path and Path(douyin_path).exists():
            print(f"\n[*] 抖音: {douyin_path}")
            dy_entries = self._load_jsonl(douyin_path)
            dy_pairs = self._pair_douyin(dy_entries)
            for p in dy_pairs:
                p["source"] = "douyin"
            all_pairs.extend(dy_pairs)
            print(f"    配对 {len(dy_pairs)} 个对话对")
        else:
            print(f"\n[*] 无抖音数据，仅使用微信")

        if not all_pairs:
            print(f"\n[!] 没有可用的对话对！")
            return 0

        # 按时间排序
        all_pairs.sort(key=lambda p: p["metadata"]["timestamp"])

        total = len(all_pairs)
        print(f"\n[*] 合并: {total} 个对话对")
        wx_count = sum(1 for p in all_pairs if p["source"] == "wechat")
        dy_count = sum(1 for p in all_pairs if p["source"] == "douyin")
        print(f"    微信: {wx_count}  抖音: {dy_count}")

        # ── ChromaDB ──
        chroma_dir = Path(chroma_path)
        chroma_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n[*] 创建 ChromaDB: {chroma_path}")
        client = chromadb.PersistentClient(path=str(chroma_dir))
        try:
            client.delete_collection(collection_name)
            print(f"    已删除旧集合")
        except Exception:
            pass
        collection = client.create_collection(
            name=collection_name,
            metadata={
                "description": "AI女友 双平台对话索引",
                "sources": "wechat,douyin",
                "total_pairs": str(total),
            },
        )

        # ── 分批嵌入写入 ──
        batch_count = (total + batch_size - 1) // batch_size
        print(f"\n[*] 开始索引 {total} 个对话对（{batch_count} 批）...")

        for i in range(0, total, batch_size):
            batch = all_pairs[i : i + batch_size]
            batch_num = i // batch_size + 1

            texts = [p["user_text"] for p in batch]
            ids = [p["id"] for p in batch]
            metadatas = [p["metadata"] for p in batch]

            embeddings = self.embedder.embed(texts)

            collection.add(
                ids=ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            print(f"    批次 {batch_num}/{batch_count} ({len(batch)} 对)... OK")

        count = collection.count()
        print(f"\n[+] 索引完成: {count} 个对话对 → {chroma_path}")
        return count

    # ── 工具 ──────────────────────────────────────────────

    @staticmethod
    def _load_jsonl(path: str) -> list[dict]:
        entries = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    # ── 微信配对 ──────────────────────────────────────────

    @staticmethod
    def _pair_wechat(entries: list[dict]) -> list[dict]:
        """微信 JSONL: role="me"/"them"，交替出现。"""
        pairs = []
        i = 0
        turn_idx = 0
        while i < len(entries):
            entry = entries[i]
            if entry.get("role") != "me":
                i += 1
                continue
            user_text = (entry.get("text") or "").strip()
            if not user_text:
                i += 1
                continue

            her_parts = []
            j = i + 1
            ts = entry.get("timestamp", 0)
            time_str = entry.get("time", "")
            while j < len(entries) and entries[j].get("role") == "them":
                t = (entries[j].get("text") or "").strip()
                if t:
                    her_parts.append(t)
                ts = entries[j].get("timestamp", ts)
                time_str = entries[j].get("time", time_str)
                j += 1

            her_text = "\n".join(her_parts)
            if her_text:
                pairs.append({
                    "id": f"wx_{turn_idx}",
                    "user_text": user_text,
                    "metadata": {
                        "her_reply": her_text,
                        "user_text": user_text,
                        "time": time_str,
                        "timestamp": ts,
                        "source": "wechat",
                        "turn_index": turn_idx,
                    },
                })
                turn_idx += 1
            i = j if j > i + 1 else i + 1
        return pairs

    # ── 抖音配对 ──────────────────────────────────────────

    @staticmethod
    def _pair_douyin(entries: list[dict]) -> list[dict]:
        """抖音 ChatLab JSONL: 提取文本消息 → 按时间排序 → 配对。

        他的 accountName: xhyyyyyyyy (或谢涵宇)
        她的 accountName: 菠萝吹雪
        只提取 type=0（文本）和 type=5（表情，保留文字描述）
        """
        messages = []
        for e in entries:
            if e.get("_type") != "message":
                continue
            content = (e.get("content") or "").strip()
            if not content:
                continue
            # 过滤系统消息和纯分享
            if content.startswith("[系统]") or content.startswith("[分享"):
                continue
            if e.get("type", 0) not in (0, 5):
                continue
            messages.append({
                "is_me": e.get("accountName", "") == "xhyyyyyyyy",
                "content": content,
                "timestamp": e.get("timestamp", 0),
                "time": datetime.fromtimestamp(e.get("timestamp", 0)).strftime("%Y-%m-%d %H:%M:%S"),
            })

        messages.sort(key=lambda m: m["timestamp"])

        # 配对: 他说 → 收集她后续回复
        pairs = []
        i = 0
        turn_idx = 0
        while i < len(messages):
            msg = messages[i]
            if not msg["is_me"]:
                i += 1
                continue
            user_text = msg["content"]
            if len(user_text) < 2:
                i += 1
                continue

            her_parts = []
            j = i + 1
            ts = msg["timestamp"]
            time_str = msg["time"]
            while j < len(messages) and messages[j]["is_me"]:
                j += 1
            # 收集她接下来的回复
            while j < len(messages) and not messages[j]["is_me"]:
                her_parts.append(messages[j]["content"])
                ts = messages[j]["timestamp"]
                time_str = messages[j]["time"]
                j += 1

            her_text = "\n".join(her_parts)
            if her_text and len(her_text) >= 1:
                pairs.append({
                    "id": f"dy_{turn_idx}",
                    "user_text": user_text,
                    "metadata": {
                        "her_reply": her_text,
                        "user_text": user_text,
                        "time": time_str,
                        "timestamp": ts,
                        "source": "douyin",
                        "turn_index": turn_idx,
                    },
                })
                turn_idx += 1
            i = j if j > i + 1 else i + 1
        return pairs
