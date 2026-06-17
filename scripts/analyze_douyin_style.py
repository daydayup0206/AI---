"""用 LLM 深度分析抖音 + 微信聊天记录，生成融合人设 prompt。"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.llm.client import DeepSeekClient
from src.config.loader import ConfigLoader

# 加载抖音数据（她的消息）
def load_douyin_her(path):
    msgs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            if e.get("_type") != "message":
                continue
            c = (e.get("content") or "").strip()
            if not c or c.startswith("[系统]") or c.startswith("[分享"):
                continue
            if e.get("accountName", "") == "菠萝吹雪":
                msgs.append({"text": c, "ts": e.get("timestamp", 0)})
    return msgs

# 加载微信数据（她的消息）
def load_wechat_her(path):
    msgs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            if e.get("role") != "them":
                continue
            t = (e.get("text") or "").strip()
            if t:
                msgs.append({"text": t, "ts": e.get("timestamp", 0)})
    return msgs

dy = load_douyin_her("data/抖音导出.jsonl")
wx = load_wechat_her("data/training/宝宝1231_her_style.jsonl")
print(f"抖音: {len(dy)} 条  微信: {len(wx)} 条")

# 排序采样
dy.sort(key=lambda m: m["ts"])
wx.sort(key=lambda m: m["ts"])

# 抖音均匀采样 300 条，微信采样 100 条
dy_step = max(1, len(dy) // 300)
dy_sample = [dy[i] for i in range(0, len(dy), dy_step)][:300]
wx_step = max(1, len(wx) // 100)
wx_sample = [wx[i] for i in range(0, len(wx), wx_step)][:100]

# 标记来源
from datetime import datetime
dy_lines = []
for m in dy_sample:
    t = datetime.fromtimestamp(m["ts"]).strftime("%Y-%m-%d")
    dy_lines.append(f"[DY {t}] {m['text'][:200]}")
wx_lines = []
for m in wx_sample:
    t = datetime.fromtimestamp(m["ts"]).strftime("%Y-%m-%d")
    wx_lines.append(f"[WX {t}] {m['text'][:200]}")

all_text = "\n\n".join(dy_lines + wx_lines)

# 时间范围
dy_dates = sorted(set(datetime.fromtimestamp(m["ts"]).strftime("%Y-%m") for m in dy))
wx_dates = sorted(set(datetime.fromtimestamp(m["ts"]).strftime("%Y-%m") for m in wx))
print(f"抖音跨度: {dy_dates[0]} ~ {dy_dates[-1]} ({len(dy_dates)} 个月)")
print(f"微信跨度: {wx_dates[0]} ~ {wx_dates[-1]} ({len(wx_dates)} 个月)")

PROMPT = f"""你是一个对话分析师。请仔细阅读以下聊天记录，它们来自同一个人（女生"宝宝"/"菠萝吹雪"），分别来自两个平台——抖音（DY）和微信（WX）。总共 {len(dy_sample) + len(wx_sample)} 条采样消息。

时间跨度：抖音 {dy_dates[0]}~{dy_dates[-1]}，微信 {wx_dates[0]}~{wx_dates[-1]}

## 所有聊天记录
{all_text}

## 分析要求

基于真实数据（不要凭空想象），输出以下内容：

### 1. 性格画像（3-5句话）
从她的说话方式推断真实性格。特别注意她的情绪范围和变化规律。

### 2. 抖音 vs 微信风格差异
同一个人的两边说话有差异吗？如果差异大，分别描述；如果基本一致，说明共性。

### 3. 说话风格（用具体数据）
- 句子长度分布（短/中/长的比例）
- 连发习惯（喜欢一次发几条？）
- 高频用词和口头禅（列出 TOP 10）
- 断句习惯（用什么分隔？空格？逗号？）
- 脏话/粗口使用情况（有没有？什么时候会用？）
- 称呼习惯（叫对方什么？）
- 表情/emoji 使用

### 4. 情绪模式
- 开心时怎么说话？（给具体例子）
- 不爽/不耐烦时？（给具体例子）
- 敷衍时？（给具体例子）
- 关心对方时？（给具体例子）

### 5. 话题偏好（TOP 5）

### 6. 优化后的 System Prompt
基于以上分析，写一个融合了两边数据的最终人设 prompt。要求：
- 不要过于热情——她不是每条都元气满满
- 突出真实情绪——有脾气、会不耐烦、会敷衍
- 说话长度和分条习惯匹配真实数据
- 口头禅和语气词基于实际统计
- 提到两个平台不同风格（如果有的话）
- 保持在 350 字以内

请直接输出。"""

print("\n正在用 DeepSeek 分析...")
loader = ConfigLoader("config.yaml")
api = loader.get_api_config()

client = DeepSeekClient(
    api_key=api["api_key"], base_url=api["base_url"],
    model=api["model"], temperature=0.3, max_tokens=4000,
)

result = client.chat([
    {"role": "system", "content": "你是数据分析师。只基于给定的聊天记录输出客观准确的分析。"},
    {"role": "user", "content": PROMPT},
])

print("\n" + "=" * 60)
print(result)
print("=" * 60)

with open("data/training/douyin_deep_analysis.txt", "w", encoding="utf-8") as f:
    f.write(result)
print("\n已保存到 data/training/douyin_deep_analysis.txt")
