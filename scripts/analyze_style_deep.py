"""用 LLM 深度分析聊天记录，生成精确的人设 prompt。"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.llm.client import DeepSeekClient
from src.config.loader import ConfigLoader

# 加载采样数据
samples = []
with open("data/training/宝宝1231_her_style.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            msg = json.loads(line)
            text = msg.get("text", "").strip()
            if text and len(text) >= 6:
                samples.append({
                    "text": text,
                    "time": msg.get("time", ""),
                    "timestamp": msg.get("timestamp", 0)
                })

samples.sort(key=lambda x: x["timestamp"])

# 均匀采样 250 条
step = max(1, len(samples) // 250)
sampled = [samples[i] for i in range(0, len(samples), step)][:250]

# 拼接聊天样本
chat_sample = "\n\n".join(
    f"[{s['time']}] {s['text']}" for s in sampled
)

# 分析 prompt
ANALYSIS_PROMPT = f"""你是一个对话分析师。请仔细阅读以下微信聊天记录（这是女生"宝宝"发的所有消息，共计{len(sampled)}条采样），从真实数据中提取她的说话特征。

## 聊天记录
{chat_sample}

## 分析要求

请基于上述真实数据，输出以下内容（用中文）：

### 1. 性格画像（3-5句话）
从她说话的方式推断她的真实性格。注意她的情绪起伏——什么时候开心、什么时候不耐烦、什么时候敷衍、什么时候认真。不要美化她，写出真实的她。

### 2. 说话风格（用具体数据说明）
- 句子长度分布（她有55%的消息很短（<=15字），30%中等（16-40字）...）
- 连发习惯（她经常一次发几条？什么时候会连发很多条？）
- 高频用词和口头禅（从数据中提取频次）
- 标点使用习惯
- 表情/emoji使用情况

### 3. 情绪模式
- 她开心时怎么说话？（给出具体例子）
- 她不爽/不耐烦时怎么说话？（给出具体例子）
- 她敷衍时怎么说话？（给出具体例子）
- 她关心对方时怎么说话？（给出具体例子）

### 4. 话题偏好
她最常聊什么话题？举具体例子。

### 5. 优化后的 System Prompt
基于以上分析，写一个优化版的人设 prompt。要求：
- 不要过于热情——她不是每条都元气满满
- 突出她真实的一面——有脾气、会不耐烦、会敷衍、开心时也会疯
- 说话长度和分条习惯要和真实数据匹配
- 口头禅和语气词要基于实际数据
- 保持在300字以内

请直接输出分析结果。"""

# 调用 LLM
print("正在用 DeepSeek 分析聊天记录...")
loader = ConfigLoader("config.yaml")
api = loader.get_api_config()

client = DeepSeekClient(
    api_key=api["api_key"],
    base_url=api["base_url"],
    model=api["model"],
    temperature=0.3,
    max_tokens=4000,
)

result = client.chat([
    {"role": "system", "content": "你是一个专业的数据分析师。请基于真实聊天数据输出客观、准确的分析。"},
    {"role": "user", "content": ANALYSIS_PROMPT},
])

print("\n" + "=" * 60)
print(result)
print("\n" + "=" * 60)

# 保存结果
output_path = "data/training/deep_analysis.txt"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(result)
print(f"\n分析结果已保存到: {output_path}")
