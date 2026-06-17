#!/usr/bin/env python
"""构建 ChromaDB 对话索引 v2（微信 + 抖音 + 时间权重）。

用法:
    python scripts/build_index.py
    python scripts/build_index.py --wechat data/training/宝宝1231_dialogues.jsonl
    python scripts/build_index.py --douyin data/抖音导出.jsonl
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag.embedder import Embedder
from src.rag.indexer import DialogueIndexer


def main():
    parser = argparse.ArgumentParser(description="构建 ChromaDB 对话索引 v2")
    parser.add_argument(
        "--wechat",
        default="data/training/宝宝1231_dialogues.jsonl",
        help="微信对话 JSONL",
    )
    parser.add_argument(
        "--douyin",
        default="data/抖音导出.jsonl",
        help="抖音 ChatLab JSONL（留空跳过）",
    )
    parser.add_argument(
        "--chroma-dir",
        default="data/chroma_db",
        help="ChromaDB 存储目录",
    )
    parser.add_argument(
        "--model",
        default="paraphrase-multilingual-MiniLM-L12-v2",
        help="嵌入模型名",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="每批处理的对话对数",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("   AI女友 — ChromaDB 对话索引 v2")
    print("=" * 50)
    print(f"  微信: {args.wechat}")
    print(f"  抖音: {args.douyin or '(跳过)'}")
    print(f"  存储: {args.chroma_dir}")
    print(f"  模型: {args.model}")
    print()

    start = time.time()

    embedder = Embedder(model_name=args.model)
    indexer = DialogueIndexer(embedder)

    try:
        count = indexer.build(
            wechat_path=args.wechat,
            douyin_path=args.douyin or None,
            chroma_path=args.chroma_dir,
            batch_size=args.batch_size,
        )
        elapsed = time.time() - start
        print(f"\n[+] 完成! 总索引 {count} 个对话对")
        print(f"[+] 耗时: {elapsed:.1f}s")
        print(f"[+] 存储位置: {args.chroma_dir}")
        print(f"\n   现在可以运行: python run.py")
    except FileNotFoundError as e:
        print(f"\n[!] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[!] 构建失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
