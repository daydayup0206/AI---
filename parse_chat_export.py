"""
解析 WeFlow JSON 导出 → AI 女友风格学习数据
=============================================
从 WeFlow 导出的 JSON 中提取对话对，清洗并格式化为风格学习训练数据。

输出:
  data/training/
    ├── raw_dialogues.jsonl    # 完整对话（时序排列）
    ├── her_messages.jsonl     # 只含目标人物的消息（人设学习）
    └── my_messages.jsonl      # 只含"我"的消息（可选）
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# ============================================================
# 配置
# ============================================================
INPUT_FILE = Path(r"E:\new-learning\ai女友\data\私聊_宝宝（1231）.json")
OUTPUT_DIR = Path(r"E:\new-learning\ai女友\data\training")

# 系统消息类型（需过滤）
SYSTEM_TYPES = {"系统消息", "时间分隔符"}
SKIP_TYPES = SYSTEM_TYPES | set()

# 纯符号/无意义消息正则
EMPTY_PATTERNS = [
    re.compile(r"^\[.*\]$"),           # [图片] [表情包] [语音]
    re.compile(r"^<msg>.*</msg>$"),    # XML 消息
    re.compile(r"^[\s​-‏ -  　]+$"),  # 纯空白
]


def is_skip_message(msg: dict) -> bool:
    """判断是否应跳过该消息"""
    msg_type = msg.get("type", "")
    if msg_type in SKIP_TYPES:
        return True

    content = (msg.get("content") or "").strip()
    if not content:
        return True

    for pat in EMPTY_PATTERNS:
        if pat.match(content):
            return True

    return False


def extract_emoji_info(msg: dict) -> dict | None:
    """提取表情包信息"""
    if msg.get("type") == "动画表情" and msg.get("emojiMd5"):
        return {
            "md5": msg.get("emojiMd5"),
            "cdn_url": msg.get("emojiCdnUrl", ""),
        }
    return None


def classify_message(msg: dict) -> str:
    """消息分类"""
    msg_type = msg.get("type", "")
    type_map = {
        "文本消息": "text",
        "动画表情": "emoji",
        "图片": "image",
        "语音": "voice",
        "视频": "video",
        "文件": "file",
        "链接": "link",
        "引用回复": "text",  # 引用回复本质是文本
    }
    return type_map.get(msg_type, "other")


def parse_export(filepath: Path) -> dict:
    """解析 WeFlow JSON 导出文件"""
    print(f"[*] 读取: {filepath} ({filepath.stat().st_size / 1024 / 1024:.1f} MB)")

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    session = data.get("session", {})
    messages = data.get("messages", [])

    print(f"[+] 会话: {session.get('displayName')} ({session.get('wxid')})")
    print(f"[+] 对方昵称: {session.get('nickname')}, 备注: {session.get('remark')}")
    print(f"[+] 总消息数: {len(messages)}")

    return {
        "session": session,
        "messages": messages,
    }


def build_dialogues(messages: list[dict]) -> list[dict]:
    """
    构建对话对：将相邻的多条同作者消息合并成一轮。

    WeChat 聊天中经常一人连发多条（如："在吗" "周末有空吗" 连发），
    把这些合并成一轮对话，更符合自然对话习惯。
    """
    dialogues = []
    current = None  # 当前轮次

    for msg in messages:
        if is_skip_message(msg):
            continue

        role = "me" if msg.get("isSend") == 1 else "them"
        content = (msg.get("content") or "").strip()
        msg_type = classify_message(msg)
        emoji = extract_emoji_info(msg)

        if current is None:
            # 第一轮
            current = {
                "role": role,
                "messages": [{"content": content, "type": msg_type, "emoji": emoji}],
                "start_time": msg.get("createTime", 0),
                "formatted_time": msg.get("formattedTime", ""),
            }
        elif current["role"] == role:
            # 同一人连发，追加
            current["messages"].append(
                {"content": content, "type": msg_type, "emoji": emoji}
            )
        else:
            # 角色切换，保存上一轮，开始新一轮
            dialogues.append(current)
            current = {
                "role": role,
                "messages": [{"content": content, "type": msg_type, "emoji": emoji}],
                "start_time": msg.get("createTime", 0),
                "formatted_time": msg.get("formattedTime", ""),
            }

    if current:
        dialogues.append(current)

    return dialogues


def format_style_records(dialogues: list[dict], target_name: str = "") -> list[dict]:
    """
    转换为风格学习格式。

    输出格式:
      - role: "me" | "them"
      - text: 合并后的消息文本
      - messages: 拆分后的单条消息列表
      - timestamp: 时间戳
    """
    records = []
    for d in dialogues:
        texts = [m["content"] for m in d["messages"] if m["type"] == "text"]
        emojis = [m["emoji"]["md5"] for m in d["messages"] if m.get("emoji")]

        combined_text = "\n".join(texts).strip()
        if not combined_text and not emojis:
            continue

        records.append({
            "role": d["role"],
            "text": combined_text,
            "raw_messages": [
                {
                    "content": m["content"],
                    "type": m["type"],
                }
                for m in d["messages"]
            ],
            "has_emoji": len(emojis) > 0,
            "emoji_md5s": emojis,
            "timestamp": d["start_time"],
            "time": d.get("formatted_time", ""),
        })

    return records


def save_outputs(records: list[dict], session: dict):
    """保存所有输出文件"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    target_name = session.get("displayName", "") or session.get("nickname", "")
    safe_name = "".join(c for c in target_name if c.isalnum() or c in " _-")[:30]

    # 1. 完整对话 JSONL
    full_path = OUTPUT_DIR / f"{safe_name}_dialogues.jsonl"
    with open(full_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[+] 完整对话: {full_path} ({len(records)} 轮)")

    # 2. 只含"她"的消息（用于学习她的说话风格）
    her_records = [r for r in records if r["role"] == "them"]
    her_path = OUTPUT_DIR / f"{safe_name}_her_style.jsonl"
    with open(her_path, "w", encoding="utf-8") as f:
        for r in her_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[+] 她的消息: {her_path} ({len(her_records)} 轮)")

    # 3. 只含"我"的消息
    my_records = [r for r in records if r["role"] == "me"]
    my_path = OUTPUT_DIR / f"{safe_name}_me.jsonl"
    with open(my_path, "w", encoding="utf-8") as f:
        for r in my_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[+] 我的消息: {my_path} ({len(my_records)} 轮)")

    # 4. 简单文本格式（方便直接看）
    txt_path = OUTPUT_DIR / f"{safe_name}_text.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        for r in records:
            label = "我" if r["role"] == "me" else target_name
            f.write(f"[{label}] {r['text']}\n")
    print(f"[+] 纯文本: {txt_path}")

    # 5. 统计摘要
    print(f"\n{'='*50}")
    print(f"  导出统计")
    print(f"{'='*50}")
    print(f"  会话: {target_name} ({session.get('wxid')})")
    print(f"  总对话轮次: {len(records)}")
    print(f"  对方消息: {len(her_records)} 轮 ({len(her_records)/max(1,len(records))*100:.1f}%)")
    print(f"  我方消息: {len(my_records)} 轮 ({len(my_records)/max(1,len(records))*100:.1f}%)")

    # 文本统计
    her_texts = [r["text"] for r in her_records if r["text"]]
    if her_texts:
        her_chars = [len(t) for t in her_texts]
        print(f"\n  对方文本特征:")
        print(f"    总字数: {sum(her_chars)}")
        print(f"    平均每条: {sum(her_chars)/len(her_chars):.1f} 字")
        print(f"    最短/最长: {min(her_chars)}/{max(her_chars)} 字")

    her_emojis = sum(1 for r in her_records if r.get("has_emoji"))
    if her_emojis:
        print(f"    含表情消息: {her_emojis} 条 ({her_emojis/max(1,len(her_records))*100:.1f}%)")

    # 时间范围
    if records:
        first_ts = records[-1]["timestamp"]
        last_ts = records[0]["timestamp"]
        import time
        first_date = time.strftime("%Y-%m-%d", time.localtime(first_ts))
        last_date = time.strftime("%Y-%m-%d", time.localtime(last_ts))
        print(f"\n  时间范围: {first_date} ~ {last_date}")


def main():
    if not INPUT_FILE.exists():
        print(f"[!] 文件不存在: {INPUT_FILE}")
        print("[!] 请用 WeFlow 导出 JSON 格式聊天记录放到 data/ 目录")
        sys.exit(1)

    data = parse_export(INPUT_FILE)
    dialogues = build_dialogues(data["messages"])
    records = format_style_records(dialogues, data["session"].get("displayName", ""))

    if not records:
        print("[!] 无有效消息")
        sys.exit(1)

    save_outputs(records, data["session"])

    print(f"\n✅ 完成! 文件保存在: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
