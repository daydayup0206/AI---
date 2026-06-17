"""
记忆提取器：从聊天记录中提取结构化记忆。

策略:
  1. 将对话按时间窗口分批
  2. 每批让 LLM 提取：事件、个人信息、偏好、关系里程碑
  3. 去重合并，存入记忆库
"""

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

# 复用项目的 LLM 客户端
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.llm.client import DeepSeekClient
from src.config.loader import ConfigLoader


# ── 提示词模板 ──────────────────────────────────────────

MEMORY_EXTRACTION_PROMPT = """你是一个对话分析助手。请从以下微信聊天记录中提取值得记住的信息。

聊天对象：{target_name}（昵称"{target_nickname}"）
我的昵称：{my_nickname}

## 聊天记录片段
{conversation_text}

## 请提取以下信息（JSON 格式输出）

请只输出 JSON，不要有其他文字。JSON 格式如下：

{{
  "events": [
    {{
      "date": "YYYY-MM-DD 或未知",
      "summary": "用一句话描述发生了什么",
      "importance": "high/medium/low",
      "participants": ["参与的人"],
      "emotion": "开心/难过/生气/兴奋/温馨/搞笑/普通"
    }}
  ],
  "personal_info": [
    {{
      "person": "谁的信息",
      "field": "信息类型（工作/家庭/爱好/习惯/健康/其他）",
      "content": "具体内容",
      "confidence": "certain/likely/possible"
    }}
  ],
  "preferences": [
    {{
      "person": "谁",
      "category": "食物/音乐/电影/旅行/运动/颜色/品牌/其他",
      "detail": "具体偏好",
      "attitude": "喜欢/讨厌/一般"
    }}
  ],
  "relationship_milestones": [
    {{
      "date": "YYYY-MM-DD 或未知",
      "milestone": "描述里程碑事件",
      "significance": "为什么重要"
    }}
  ],
  "inside_jokes": [
    {{
      "joke": "梗或笑话的内容",
      "context": "出现的背景",
      "used_by": "谁先说/常说的"
    }}
  ],
  "catch_phrases": [
    {{
      "phrase": "口头禅",
      "used_by": "谁说",
      "example": "原文示例"
    }}
  ]
}}

如果没有某类信息，对应的数组留空 []。

只输出 JSON："""

MEMORY_MERGE_PROMPT = """你是一个对话记忆整理助手。请合并以下从不同时间段提取的记忆条目，去重并统一格式。

## 待合并的记忆条目
{memory_entries}

## 请去重合并后输出 JSON（与输入格式相同）

只输出 JSON："""


class MemoryExtractor:
    """从聊天记录中提取结构化记忆。"""

    def __init__(self, client: DeepSeekClient, config: dict):
        self.client = client
        self.target_name = config.get("target_name", "她")
        self.target_nickname = config.get("target_nickname", "")
        self.my_nickname = config.get("my_nickname", "我")
        self.batch_size = config.get("batch_size", 80)
        self.max_batches = config.get("max_batches", 10)

    def _load_dialogues(self) -> list[dict]:
        """加载对话数据。"""
        training_dir = Path(r"E:\new-learning\ai女友\data\training")
        dialogue_files = list(training_dir.glob("*_dialogues.jsonl"))

        # 优先选包含目标名字的
        target_match = None
        for f in dialogue_files:
            if self.target_nickname and self.target_nickname in f.stem:
                target_match = f
                break

        if not target_match and dialogue_files:
            target_match = dialogue_files[0]

        if not target_match:
            raise FileNotFoundError("未找到对话文件")

        print(f"[*] 读取对话: {target_match.name}")
        dialogues = []
        with open(target_match, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    dialogues.append(json.loads(line))
        return dialogues

    def _format_conversation(self, dialogues: list[dict]) -> str:
        """格式化对话为文本。"""
        lines = []
        for d in dialogues:
            role_label = "我" if d["role"] == "me" else self.target_name
            timestamp = d.get("time", "")
            text = d.get("text", "")
            if text.strip():
                lines.append(f"[{timestamp}] {role_label}: {text}")
        return "\n".join(lines)

    def _extract_json(self, response: str) -> dict | None:
        """从 LLM 回复中提取 JSON。"""
        # 尝试找 ```json ... ``` 代码块
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        if json_match:
            response = json_match.group(1)

        # 尝试找第一个 { 到最后一个 }
        start = response.find("{")
        end = response.rfind("}")
        if start >= 0 and end > start:
            response = response[start : end + 1]

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            print(f"  [!] JSON 解析失败，原始回复前200字: {response[:200]}")
            return None

    def extract_batch(self, dialogues: list[dict], batch_index: int = 0) -> dict | None:
        """提取一批对话中的记忆。"""
        conv_text = self._format_conversation(dialogues)

        if len(conv_text) < 100:
            return None  # 太短，跳过

        prompt = MEMORY_EXTRACTION_PROMPT.format(
            target_name=self.target_name,
            target_nickname=self.target_nickname or self.target_name,
            my_nickname=self.my_nickname,
            conversation_text=conv_text[:8000],  # 截断以免超 token
        )

        print(f"  [批次 {batch_index}] 正在提取记忆... ({len(conv_text)} 字符)")

        try:
            response = self.client.chat(
                messages=[{"role": "user", "content": prompt}],
            )
            return self._extract_json(response)
        except Exception as e:
            print(f"  [!] 提取失败: {e}")
            return None

    def merge_memories(self, all_memories: list[dict]) -> dict:
        """合并去重所有批次的记忆。"""
        if len(all_memories) <= 1:
            return all_memories[0] if all_memories else {}

        print(f"\n[*] 合并 {len(all_memories)} 批记忆...")

        entries_text = json.dumps(all_memories, ensure_ascii=False, indent=2)
        prompt = MEMORY_MERGE_PROMPT.format(memory_entries=entries_text[:6000])

        try:
            response = self.client.chat(
                messages=[{"role": "user", "content": prompt}],
            )
            merged = self._extract_json(response)
            if merged:
                return merged
        except Exception as e:
            print(f"  [!] 合并失败: {e}")

        # 回退：简单合并（取所有条目）
        merged = defaultdict(list)
        for mem in all_memories:
            for key in ["events", "personal_info", "preferences", "relationship_milestones", "inside_jokes", "catch_phrases"]:
                merged[key].extend(mem.get(key, []))

        # 简单去重：按 summary/content 去重
        for key in merged:
            seen = set()
            unique = []
            for item in merged[key]:
                identifier = str(item.get("summary") or item.get("content") or item.get("joke") or item.get("phrase") or "")
                if identifier not in seen:
                    seen.add(identifier)
                    unique.append(item)
            merged[key] = unique

        return dict(merged)

    def run(self, max_batches: int | None = None) -> dict:
        """执行完整的记忆提取流程。"""
        if max_batches is not None:
            self.max_batches = max_batches

        dialogues = self._load_dialogues()
        print(f"[+] 共 {len(dialogues)} 轮对话")

        # 分批提取
        batch_size = self.batch_size
        total_batches = min(
            (len(dialogues) + batch_size - 1) // batch_size,
            self.max_batches,
        )

        # 均匀采样 batches（覆盖整个时间范围）
        all_memories = []
        for i in range(total_batches):
            start = i * (len(dialogues) // total_batches)
            end = start + batch_size if i < total_batches - 1 else len(dialogues)
            batch = dialogues[start:end]

            print(f"\n[批次 {i+1}/{total_batches}] 对话 #{start+1}-#{end} "
                  f"({len(batch)} 轮, 时间 {batch[0].get('time','?')} ~ {batch[-1].get('time','?')})")

            memory = self.extract_batch(batch, i + 1)
            if memory:
                all_memories.append(memory)

            # API 限速
            if i < total_batches - 1:
                time.sleep(1.5)

        if not all_memories:
            print("[!] 未能提取任何记忆")
            return {}

        # 合并去重
        merged = self.merge_memories(all_memories)

        # 保存
        output_path = Path(r"E:\new-learning\ai女友\data\training\extracted_memories.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        print(f"\n[+] 记忆已保存: {output_path}")

        # 统计
        for key in merged:
            if merged[key]:
                print(f"  {key}: {len(merged[key])} 条")

        return merged


# ── 简单版：纯文本扫描（不依赖 LLM）──────────────────────

class SimpleMemoryScanner:
    """不依赖 LLM 的快速记忆扫描。用规则从对话中提取关键信息。"""

    def __init__(self, dialogues: list[dict], target_name: str = "她"):
        self.dialogues = dialogues
        self.target_name = target_name

    def extract_dates(self) -> list[dict]:
        """提取提到具体日期/节日的事件。"""
        date_patterns = [
            (r"(\d{4})年(\d{1,2})月(\d{1,2})[日号]", "绝对日期"),
            (r"(\d{1,2})月(\d{1,2})[日号]", "月日"),
            (r"(下周|下个月|明天|后天|昨天|今天|周末|国庆|过年|生日|圣诞|跨年|情人节|七夕)", "相对日期"),
        ]

        events = []
        for d in self.dialogues:
            text = d.get("text", "")
            for pat, date_type in date_patterns:
                matches = re.findall(pat, text)
                for m in matches:
                    if date_type == "相对日期":
                        date_str = m
                    elif len(m) == 3:
                        date_str = f"{m[0]}-{m[1].zfill(2)}-{m[2].zfill(2)}"
                    else:
                        date_str = f"{m[0]}-{m[1].zfill(2)}"

                    # 提取前后句子作为上下文
                    idx = text.find(str(m[0]) if isinstance(m, tuple) else m)
                    context = text[max(0, idx-20):idx+80] if idx >= 0 else text[:80]
                    events.append({
                        "date": date_str,
                        "context": context.strip(),
                        "time": d.get("time", ""),
                    })

        # 去重
        seen = set()
        unique = []
        for e in events:
            key = e["date"] + e["context"][:20]
            if key not in seen:
                seen.add(key)
                unique.append(e)
        return unique

    def extract_keywords(self, top_n: int = 50) -> dict:
        """提取高频关键词（排除停用词）。"""
        from collections import Counter

        # 常见停用词
        stop_words = set("的是不我一有个在上人们来大就到时地以为可以生中这你她他它着之里后去说没也看要了好得还下那出对想自能会过子小么什天起都样而长把话多手面心动如现用开所方前因只从很但点被道让知经种些光可和学又情理与为如当两现体加其相定面于重回此等都月日把")

        words = Counter()
        for d in self.dialogues:
            text = d.get("text", "")
            # 提取中文词组
            for word in re.findall(r"[一-鿿]{2,4}", text):
                # 过滤停用词
                if any(c in stop_words for c in word[:2]):
                    continue
                words[word] += 1

        return {
            "top_keywords": words.most_common(top_n),
            "total_unique": len(words),
        }

    def run(self) -> dict:
        """运行扫描。"""
        dates = self.extract_dates()
        keywords = self.extract_keywords()

        return {
            "date_mentions": dates,
            "keywords": keywords,
            "total_dialogues": len(self.dialogues),
        }


# ── 命令行 ──────────────────────────────────────────────

def main():
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    import argparse
    parser = argparse.ArgumentParser(description="记忆提取器")
    parser.add_argument("--mode", choices=["llm", "simple", "both"], default="both",
                        help="提取模式: llm(深度) / simple(快速扫描) / both(两者)")
    parser.add_argument("--batches", type=int, default=5,
                        help="LLM 模式的批次数（默认5批，覆盖整个时间线）")
    args = parser.parse_args()

    training_dir = Path(r"E:\new-learning\ai女友\data\training")
    dialogue_files = list(training_dir.glob("*_dialogues.jsonl"))

    if not dialogue_files:
        print("[!] 未找到对话文件")
        print("[!] 请先运行 python parse_chat_export.py")
        sys.exit(1)

    dialogue_file = dialogue_files[0]
    target_name = dialogue_file.stem.replace("_dialogues", "")

    dialogues = [json.loads(l) for l in open(dialogue_file, "r", encoding="utf-8") if l.strip()]
    print(f"[+] 加载 {len(dialogues)} 轮对话")

    # 简单扫描（不需要 API）
    if args.mode in ("simple", "both"):
        print("\n" + "=" * 60)
        print("  快速扫描（关键词 + 日期）")
        print("=" * 60)
        scanner = SimpleMemoryScanner(dialogues, target_name)
        result = scanner.run()

        print(f"\n[日期提及] {len(result['date_mentions'])} 处")
        for d in result["date_mentions"][:15]:
            print(f"  {d['date']:12s} | {d['context'][:60]}")

        print(f"\n[高频关键词] Top 20")
        for word, count in result["keywords"]["top_keywords"][:20]:
            print(f"  {word}: {count} 次")

        # 保存
        simple_path = training_dir / f"{target_name}_simple_scan.json"
        with open(simple_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n[+] 快速扫描结果: {simple_path}")

    # LLM 深度提取
    if args.mode in ("llm", "both"):
        print("\n" + "=" * 60)
        print("  LLM 深度记忆提取")
        print("=" * 60)

        try:
            loader = ConfigLoader()
            api_config = loader.get_api_config()
            client = DeepSeekClient(
                api_key=api_config["api_key"],
                base_url=api_config["base_url"],
                model=api_config["model"],
                temperature=0.3,
                max_tokens=2048,
            )

            extractor = MemoryExtractor(
                client,
                config={
                    "target_name": target_name,
                    "target_nickname": target_name,
                    "my_nickname": "我",
                    "batch_size": 80,
                    "max_batches": args.batches,
                },
            )
            # 直接用 dialogues（绕过 _load_dialogues 的文件查找）
            extractor._load_dialogues = lambda: dialogues
            extractor.run(max_batches=args.batches)

        except Exception as e:
            print(f"[!] LLM 提取失败: {e}")
            print("[*] 请确保 config.yaml 中 API key 配置正确")


if __name__ == "__main__":
    main()
