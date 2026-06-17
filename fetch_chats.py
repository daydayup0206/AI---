"""
WeFlow API 客户端 - 聊天记录导入
===============================
依赖 WeFlow 的 HTTP API 拉取聊天记录，转换为 AI 女友风格学习格式。

前提条件:
  1. WeFlow 已启动 (npm run electron:dev)
  2. 在 WeFlow 设置中开启 "API 服务" (端口 5031)
  3. 设置 Access Token

使用方法:
  python fetch_chats.py list                     # 列出所有会话
  python fetch_chats.py fetch <会话ID>            # 拉取指定会话
  python fetch_chats.py fetch-all                # 批量拉取所有私聊
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import URLError

# ============================================================
# 配置
# ============================================================
BASE_URL = "http://127.0.0.1:5031"
API_TOKEN = os.environ.get("WEFLOW_TOKEN", "weflow-token-change-me")
OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "chat_imports"

# 项目中的风格学习输出目录
STYLE_DATA_DIR = Path(__file__).resolve().parent / "data" / "style_learning"


def api_request(method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict | list:
    """发送 WeFlow API 请求"""
    url = f"{BASE_URL}{path}"
    if params:
        # 过滤 None 值
        clean_params = {k: v for k, v in params.items() if v is not None}
        url = f"{url}?{urlencode(clean_params)}"

    data = None
    headers = {"Authorization": f"Bearer {API_TOKEN}"}

    if method == "POST" and body:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except URLError as e:
        print(f"[!] API 请求失败: {e}")
        if hasattr(e, "code") and e.code == 401:
            print("[!] Token 验证失败，请检查 WEFLOW_TOKEN 环境变量或 WeFlow 设置")
        if hasattr(e, "reason") and "Connection refused" in str(e.reason):
            print("[!] 无法连接到 WeFlow，请确认:")
            print("    1. WeFlow 已启动")
            print("    2. 设置 → API 服务 → 已开启")
            print(f"    3. 端口为 5031")
        sys.exit(1)


def list_sessions(keyword: str | None = None, limit: int = 200) -> list[dict]:
    """列出所有会话"""
    params = {"limit": limit}
    if keyword:
        params["keyword"] = keyword
    result = api_request("GET", "/api/v1/sessions", params=params)
    if isinstance(result, dict):
        return result.get("sessions", [])
    return result


def get_messages(
    talker: str,
    limit: int = 5000,
    offset: int = 0,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """获取指定会话的消息"""
    params = {
        "talker": talker,
        "limit": limit,
        "offset": offset,
        "start": start,
        "end": end,
    }
    return api_request("GET", "/api/v1/messages", params=params)


def get_contacts(keyword: str | None = None, limit: int = 200) -> list[dict]:
    """获取联系人列表"""
    params = {"limit": limit}
    if keyword:
        params["keyword"] = keyword
    result = api_request("GET", "/api/v1/contacts", params=params)
    if isinstance(result, dict):
        return result.get("contacts", [])
    return result


def fetch_all_messages(talker: str, display_name: str = "", batch_size: int = 5000) -> list[dict]:
    """分页拉取全部消息"""
    all_messages = []
    offset = 0

    # 先拉第一页
    result = get_messages(talker, limit=batch_size, offset=0)
    if isinstance(result, dict):
        messages = result.get("messages", [])
        total = result.get("count", 0)
        has_more = result.get("hasMore", True)
    else:
        messages = result if isinstance(result, list) else []
        total = len(messages)
        has_more = len(messages) >= batch_size

    all_messages.extend(messages)

    name = display_name or talker
    print(f"  [{name}] 总计 {total} 条, 已拉取 {len(messages)} 条", end="")

    while has_more:
        offset += batch_size
        result = get_messages(talker, limit=batch_size, offset=offset)
        if isinstance(result, dict):
            messages = result.get("messages", [])
            has_more = result.get("hasMore", False)
        else:
            messages = result if isinstance(result, list) else []
            has_more = len(messages) >= batch_size

        all_messages.extend(messages)
        print(f"\r  [{name}] 已拉取 {len(all_messages)} 条", end="")

    print(f"\r  [{name}] ✅ 全部拉取完成: {len(all_messages)} 条消息")
    return all_messages


def convert_to_style_format(messages: list[dict], my_wxid: str = "") -> list[dict]:
    """
    将 WeFlow 消息格式转换为风格学习格式。

    风格学习需要的字段:
      - role: "me" | "them"
      - content: 消息文本
      - timestamp: Unix 时间戳
      - msg_type: text | image | voice | video | emoji | other
    """
    records = []
    for msg in messages:
        is_send = msg.get("isSend", 0)
        content = msg.get("content", "") or ""
        parsed = msg.get("parsedContent", "") or ""

        # 优先用 parsedContent（已解析的纯文本）
        text = parsed if parsed else content

        # 判断消息类型
        media_type = msg.get("mediaType", "")
        local_type = msg.get("localType", 0)

        if media_type == "image" or "[图片]" in content:
            msg_type = "image"
        elif media_type == "voice" or "[语音]" in content:
            msg_type = "voice"
        elif media_type == "video" or "[视频]" in content:
            msg_type = "video"
        elif media_type == "emoji" or "[表情]" in content:
            msg_type = "emoji"
        elif text.strip():
            msg_type = "text"
        else:
            msg_type = "other"

        records.append({
            "role": "me" if is_send else "them",
            "content": text.strip(),
            "timestamp": msg.get("createTime", 0),
            "msg_type": msg_type,
            "server_id": msg.get("serverId", ""),
        })

    return records


def save_style_data(records: list[dict], session_name: str, session_id: str):
    """保存为风格学习数据"""
    STYLE_DATA_DIR.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(c for c in session_name if c.isalnum() or c in " _-")[:40].strip()
    if not safe_name:
        safe_name = session_id.replace("@", "_")

    # JSONL 格式（每行一条，方便训练）
    jsonl_path = STYLE_DATA_DIR / f"{safe_name}.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 统计
    my_msgs = sum(1 for r in records if r["role"] == "me")
    their_msgs = sum(1 for r in records if r["role"] == "them")
    text_msgs = sum(1 for r in records if r["msg_type"] == "text")

    print(f"  📁 JSONL: {jsonl_path}")
    print(f"  📊 统计: 我={my_msgs} 条, 对方={their_msgs} 条, 文本={text_msgs} 条")

    return jsonl_path


# ============================================================
# 命令行
# ============================================================

def cmd_list():
    """列出所有会话"""
    print("正在拉取会话列表...")
    sessions = list_sessions()
    if not sessions:
        print("未获取到会话 (请确认 WeFlow API 已开启)")
        return

    # 分类
    privates = [s for s in sessions if s.get("type") != 2]
    groups = [s for s in sessions if s.get("type") == 2]

    print(f"\n{'='*60}")
    print(f"  私聊 ({len(privates)} 个)")
    print(f"{'='*60}")
    for s in sorted(privates, key=lambda x: x.get("lastTimestamp", 0) or 0, reverse=True):
        name = s.get("displayName", "") or s["username"]
        ts = s.get("lastTimestamp", 0)
        last_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "无"
        unread = s.get("unreadCount", 0)
        print(f"  {name:30s} | 最后: {last_time} | 未读: {unread}")
        print(f"    ID: {s['username']}")

    if groups:
        print(f"\n{'='*60}")
        print(f"  群聊 ({len(groups)} 个)")
        print(f"{'='*60}")
        for s in sorted(groups, key=lambda x: x.get("lastTimestamp", 0) or 0, reverse=True)[:10]:
            name = s.get("displayName", "") or s["username"]
            ts = s.get("lastTimestamp", 0)
            last_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "无"
            print(f"  {name:30s} | 最后: {last_time}")
            print(f"    ID: {s['username']}")

    print(f"\n💡 下一步: python fetch_chats.py fetch <会话ID>")


def cmd_fetch(talker_id: str):
    """拉取指定会话的全部消息并保存"""
    # 获取会话名
    sessions = list_sessions()
    display_name = talker_id
    for s in sessions:
        if s.get("username") == talker_id:
            display_name = s.get("displayName", "") or talker_id
            break

    print(f"正在拉取: {display_name} ({talker_id})")

    messages = fetch_all_messages(talker_id, display_name)

    if not messages:
        print("未获取到消息")
        return

    # 转换为风格学习格式
    records = convert_to_style_format(messages)

    # 保存
    save_style_data(records, display_name, talker_id)

    # 同时保存原始 JSON
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = OUTPUT_DIR / f"{display_name}_{talker_id}.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)
    print(f"  📄 原始数据: {raw_path}")


def cmd_fetch_all():
    """批量拉取所有私聊会话"""
    sessions = list_sessions()
    privates = [s for s in sessions if s.get("type") != 2]

    if not privates:
        print("没有找到私聊会话")
        return

    # 按消息时间排序，先拉最近聊的
    privates.sort(key=lambda x: x.get("lastTimestamp", 0) or 0, reverse=True)

    print(f"将拉取 {len(privates)} 个私聊会话")
    print("=" * 60)

    for i, s in enumerate(privates):
        name = s.get("displayName", "") or s["username"]
        talker = s["username"]
        print(f"\n[{i+1}/{len(privates)}] {name}")
        try:
            messages = fetch_all_messages(talker, name)
            if messages:
                records = convert_to_style_format(messages)
                save_style_data(records, name, talker)
        except Exception as e:
            print(f"  [!] 拉取失败: {e}")

    print(f"\n{'='*60}")
    print(f"全部完成! 数据保存在: {STYLE_DATA_DIR}")


def main():
    if len(sys.argv) < 2:
        print("使用方法:")
        print("  python fetch_chats.py list             列出所有会话")
        print("  python fetch_chats.py fetch <会话ID>    拉取指定会话")
        print("  python fetch_chats.py fetch-all        批量拉取所有私聊")
        print()
        print("环境变量:")
        print("  WEFLOW_TOKEN  WeFlow API Token (默认: weflow-token-change-me)")
        return

    cmd = sys.argv[1]

    if cmd == "list":
        cmd_list()
    elif cmd == "fetch":
        if len(sys.argv) < 3:
            print("请提供会话ID: python fetch_chats.py fetch <会话ID>")
            sys.exit(1)
        cmd_fetch(sys.argv[2])
    elif cmd == "fetch-all":
        cmd_fetch_all()
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
