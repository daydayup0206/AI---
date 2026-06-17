"""
微信 AI 女友桥接 v6
==================
v6 改进:
  - 随机轮询间隔（避免固定频率被检测）
  - ctypes SendInput 模拟真实键盘（硬件扫描码级别）
  - 鼠标微抖动（真人操作特征）
  - 阅读+思考延迟（根据消息长度动态计算）
  - 可编辑记忆文件 (data/memories.json)
  - 对话自动沉淀记忆（每 10 轮）

用法:
  python wx_bridge.py                  # 自动回复
  python wx_bridge.py --dry-run        # 演习模式
  python wx_bridge.py --memory-edit    # 打开记忆文件编辑
"""

import ctypes
import json
import os
import random
import sys
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pyautogui
pyautogui.FAILSAFE = False  # 服务端自动运行，不需要鼠标角落停止保护
import pyperclip
import win32gui
import win32con

from src.config.loader import ConfigLoader
from src.llm.client import DeepSeekClient
from src.personality.persona import Persona
from src.chat.session import ChatSession

# ============================================================
# 配置
# ============================================================
MULTI_PART_MIN_GAP = 0.8       # 多段消息最短间隔
MULTI_PART_MAX_GAP = 2.0       # 多段消息最长间隔
POLL_INTERVAL_MIN = 1.8        # 轮询间隔最小值
POLL_INTERVAL_MAX = 4.5        # 轮询间隔最大值
POLL_LONG_PAUSE_MIN = 15.0     # 偶尔长暂停（秒），模拟放下手机
POLL_LONG_PAUSE_MAX = 45.0
LONG_PAUSE_PROBABILITY = 0.05  # 5% 概率触发长暂停
MAX_HISTORY = 30               # 保留对话轮数
AUTO_MEMORY_INTERVAL = 10      # 每 N 轮自动提取记忆
WE_CHAT_WINDOW_TITLE = "微信"
WEFLOW_API_BASE = "http://127.0.0.1:5031"
WEFLOW_API_TOKEN = "ai-girlfriend-bridge-token"
MEMORIES_FILE = str(Path(__file__).resolve().parent / "data" / "memories.json")
MAX_CONSECUTIVE_ERRORS = 5

# 回复延迟配置（真人行为模拟）
READING_SPEED_CPM = 500         # 阅读速度（字/分钟，中等偏快）
MIN_THINKING_TIME = 1.0         # 最短思考时间（秒）
MAX_THINKING_TIME = 3.5         # 最长思考时间（秒）
BASE_TYPING_CPM = 250           # 基础打字速度（字/分钟，拼音输入）


# ============================================================
# Windows SendInput 底层键盘模拟（扫描码级别，比 pyautogui 更难检测）
# ============================================================

# Win32 常量
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

# 键盘扫描码（Scan Code Set 1）
SCANCODES = {
    "ctrl": 0x1D, "enter": 0x1C, "a": 0x1E, "v": 0x2F,
    "shift": 0x2A, "backspace": 0x0E, "left": 0x4B, "right": 0x4D,
    "home": 0x47, "end": 0x4F, "delete": 0x53,
    "escape": 0x01,
}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", INPUT_UNION),
    ]


def _send_key(scancode: int, keydown: bool = True):
    """通过 SendInput 发送单个键盘扫描码（硬件级别模拟）。"""
    extra = ctypes.c_ulong(0)
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = 0
    inp.union.ki.wScan = scancode
    inp.union.ki.dwFlags = KEYEVENTF_SCANCODE
    if not keydown:
        inp.union.ki.dwFlags |= KEYEVENTF_KEYUP
    inp.union.ki.time = 0
    inp.union.ki.dwExtraInfo = ctypes.pointer(extra)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _send_hotkey(*scancodes):
    """发送组合键（如 Ctrl+V = _send_hotkey('ctrl', 'v')）。
    每个键之间有微延迟，模拟真实手指按键间隔。
    """
    for sc in scancodes:
        _send_key(SCANCODES[sc], keydown=True)
        time.sleep(0.02 + random.random() * 0.04)
    for sc in reversed(scancodes):
        _send_key(SCANCODES[sc], keydown=False)
        time.sleep(0.01 + random.random() * 0.02)


def _send_press(scancode: str):
    """按下并释放单键。"""
    _send_key(SCANCODES[scancode], keydown=True)
    time.sleep(0.03 + random.random() * 0.05)
    _send_key(SCANCODES[scancode], keydown=False)


class Colors:
    RESET = "\033[0m"; CYAN = "\033[36m"; MAGENTA = "\033[35m"
    YELLOW = "\033[33m"; RED = "\033[31m"; GREEN = "\033[32m"
    BLUE = "\033[34m"; DIM = "\033[2m"


def _ensure_utf8():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass


# ============================================================
# 记忆管理
# ============================================================

class MemoryStore:
    """管理可编辑的记忆文件。"""

    def __init__(self, path: str = MEMORIES_FILE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._save({"personal_info": [], "relationship_milestones": [],
                         "inside_jokes": [], "preferences": []})

    def load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"personal_info": [], "relationship_milestones": [],
                     "inside_jokes": [], "preferences": []}

    def _save(self, data: dict):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save(self, data: dict):
        self._save(data)

    def add_fact(self, category: str, fact: str):
        """添加一条记忆。"""
        data = self.load()
        if category not in data:
            data[category] = []
        existing = {item.get("fact", "") if isinstance(item, dict) else str(item)
                     for item in data[category]}
        if fact not in existing:
            data[category].append({
                "fact": fact,
                "source": "auto",
                "added": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })
            self._save(data)

    def extract_from_conversation(self, history: list[str], client) -> list[str]:
        """用 LLM 从对话历史中提取新记忆。返回新增的记忆描述列表。"""
        prompt = """分析以下聊天记录，提取值得记住的信息。只提取明确提到的、重要的内容。

请只输出 JSON，格式如下（如果没有值得记住的就输出空数组）：
{
  "personal_info": [{"fact": "关于她的事实"}],
  "relationship_milestones": [{"fact": "关系中的重要事件"}],
  "inside_jokes": [{"fact": "两人之间的梗或笑话"}],
  "preferences": [{"fact": "她的喜好或厌恶"}]
}

聊天记录：
""" + "\n".join(history[-20:])

        try:
            result = client.chat([
                {"role": "system", "content": "你是对话分析助手。只输出 JSON。"},
                {"role": "user", "content": prompt},
            ])
            json_str = result.strip()
            if "```" in json_str:
                json_str = json_str.split("```")[1]
                if json_str.startswith("json"):
                    json_str = json_str[4:]
            extracted = json.loads(json_str)
        except Exception:
            return []

        new_facts = []
        for category in ["personal_info", "relationship_milestones", "inside_jokes", "preferences"]:
            items = extracted.get(category, [])
            for item in items:
                fact = item.get("fact", str(item)) if isinstance(item, dict) else str(item)
                if fact.strip():
                    self.add_fact(category, fact.strip())
                    new_facts.append(f"[{category}] {fact.strip()}")
        return new_facts

    def get_summary(self) -> str:
        """返回记忆摘要。"""
        data = self.load()
        total = sum(len(v) for v in data.values())
        lines = [f"共 {total} 条记忆:"]
        labels = {"personal_info": "个人信息", "relationship_milestones": "关系里程碑",
                   "inside_jokes": "内部梗", "preferences": "偏好"}
        for key, label in labels.items():
            items = data.get(key, [])
            if items:
                lines.append(f"  [{label}] ({len(items)}条)")
                for item in items[-5:]:
                    fact = item.get("fact", str(item)) if isinstance(item, dict) else str(item)
                    lines.append(f"    · {fact}")
        return "\n".join(lines)


# ============================================================
# WeFlow API 客户端
# ============================================================

class WeFlowClient:
    """WeFlow HTTP API 封装。"""

    def __init__(self, base_url: str = WEFLOW_API_BASE, token: str = WEFLOW_API_TOKEN):
        self.base_url = base_url
        self.token = token

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url = f"{url}?{urlencode(clean)}"
        req = Request(url, headers={"Authorization": f"Bearer {self.token}"})
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_sessions(self, limit: int = 50) -> list[dict]:
        result = self._get("/api/v1/sessions", {"limit": limit})
        return result.get("sessions", []) if isinstance(result, dict) else result

    def get_messages(self, talker: str, limit: int = 20, offset: int = 0) -> list[dict]:
        result = self._get("/api/v1/messages",
                            {"talker": talker, "limit": limit, "offset": offset})
        return result.get("messages", []) if isinstance(result, dict) else result

    def get_contacts(self, keyword: str | None = None) -> list[dict]:
        params = {"limit": 200}
        if keyword:
            params["keyword"] = keyword
        result = self._get("/api/v1/contacts", params)
        return result.get("contacts", []) if isinstance(result, dict) else result


# ============================================================
# 微信发送器（v6: ctypes SendInput + 鼠标抖动）
# ============================================================



class WeChatSender:
    """微信输入发送器 v7 — pyautogui 鼠标 + SendInput 键盘。

    实测验证：
      - pyautogui 鼠标移动+点击可以命中输入框
      - 正确位置：客户区底部往上 70px（已实测确认）
      - 键盘用 ctypes SendInput 硬件模拟
    """

    CHARS_PER_MINUTE_MIN = 180
    CHARS_PER_MINUTE_MAX = 350
    CHUNK_SIZE_MIN = 2
    CHUNK_SIZE_MAX = 5
    INPUT_OFFSET_Y = 70  # 输入框距底部像素（实测值）

    def __init__(self):
        self.hwnd = None
        self._find_window()

    def _find_window(self):
        self.hwnd = win32gui.FindWindow(None, WE_CHAT_WINDOW_TITLE)
        if not self.hwnd:
            self.hwnd = win32gui.FindWindow("Qt51514QWindowIcon", None)
        if not self.hwnd:
            def _enum(h, _):
                if "微信" in win32gui.GetWindowText(h):
                    self.hwnd = h
                    return False
                return True
            win32gui.EnumWindows(_enum, None)
        if not self.hwnd:
            raise RuntimeError("未找到微信窗口！")
        cr = win32gui.GetClientRect(self.hwnd)
        pt = win32gui.ClientToScreen(self.hwnd, (0, 0))
        self.client_w = cr[2]
        self.client_h = cr[3]
        self.origin_x = pt[0]
        self.origin_y = pt[1]
        print(f"{Colors.DIM}  微信窗口: {self.client_w}x{self.client_h}"
              f" @({self.origin_x},{self.origin_y}){Colors.RESET}")

    def focus(self):
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            self._find_window()
        if win32gui.IsIconic(self.hwnd):
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
        # 强制置顶，确保鼠标点击不会点到窗外
        win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST,
                              0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        time.sleep(0.05)
        win32gui.BringWindowToTop(self.hwnd)
        try:
            win32gui.SetForegroundWindow(self.hwnd)
        except Exception:
            pass
        time.sleep(0.2)
        # 取消置顶（留窗口在前台即可，不必一直置顶）
        win32gui.SetWindowPos(self.hwnd, win32con.HWND_NOTOPMOST,
                              0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)

    def is_valid(self) -> bool:
        try:
            return bool(self.hwnd and win32gui.IsWindow(self.hwnd))
        except Exception:
            return False

    def _click_input(self):
        """移动鼠标到输入框并点击（确保坐标在窗口范围内）。"""
        # 重新获取窗口位置（窗口可能被移动过）
        pt = win32gui.ClientToScreen(self.hwnd, (0, 0))
        cr = win32gui.GetClientRect(self.hwnd)
        self.origin_x = pt[0]
        self.origin_y = pt[1]
        self.client_w = cr[2]
        self.client_h = cr[3]

        # 目标坐标
        cx = self.origin_x + self.client_w // 2 + random.randint(-15, 15)
        cy = self.origin_y + self.client_h - self.INPUT_OFFSET_Y + random.randint(-2, 2)

        # 边界保护：确保目标在窗口客户区内
        min_x = self.origin_x + 30
        max_x = self.origin_x + self.client_w - 30
        min_y = self.origin_y + 80
        max_y = self.origin_y + self.client_h - 10
        cx = max(min_x, min(max_x, cx))
        cy = max(min_y, min(max_y, cy))

        # 刷新窗口信息再点
        win32gui.BringWindowToTop(self.hwnd)
        try:
            win32gui.SetForegroundWindow(self.hwnd)
        except Exception:
            pass
        time.sleep(0.05)

        pyautogui.moveTo(cx, cy, duration=0.08 + random.random() * 0.08)
        time.sleep(0.02 + random.random() * 0.03)
        pyautogui.click()
        time.sleep(0.04 + random.random() * 0.04)

    def send(self, text: str) -> bool:
        self.focus()
        self._click_input()

        # Ctrl+A 全选清空
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.04 + random.random() * 0.04)

        # 真人打字速度
        cpm = self.CHARS_PER_MINUTE_MIN + random.random() * (
            self.CHARS_PER_MINUTE_MAX - self.CHARS_PER_MINUTE_MIN
        )
        chunks = self._split_chunks(text)

        for chunk in chunks:
            pyperclip.copy(chunk)
            time.sleep(0.02 + random.random() * 0.03)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.04 + random.random() * 0.04)

            char_delay = len(chunk) / cpm * 60
            char_delay *= 0.7 + random.random() * 0.6
            if random.random() < 0.15:
                char_delay += 0.5 + random.random() * 1.0
            time.sleep(char_delay)

        time.sleep(0.3 + random.random() * 0.7)
        pyautogui.press("enter")
        return True

    def _split_chunks(self, text: str) -> list[str]:
        chunks = []
        i = 0
        while i < len(text):
            if random.random() < 0.1:
                size = random.randint(5, 8)
            else:
                size = random.randint(self.CHUNK_SIZE_MIN, self.CHUNK_SIZE_MAX)
            end = min(i + size, len(text))
            if end < len(text):
                for j in range(end, max(i + 1, end - 3), -1):
                    if text[j - 1] in "，。！？、；：\n)）\"'":
                        end = j
                        break
            chunks.append(text[i:end])
            i = end
        return chunks

class AIWeChatBridge:
    """AI 女友微信桥接器（v6）。"""

    def __init__(self, config_path: str = "config.yaml", dry_run: bool = False):
        self.dry_run = dry_run
        self._running = False
        self._reply_count = 0
        self._consecutive_errors = 0
        self._last_msg_id = 0
        self._last_reply_content = ""
        self._conversation_log: list[str] = []
        self.memory_store = MemoryStore()

        # 初始化组件
        loader = ConfigLoader(config_path)
        api = loader.get_api_config()
        persona_cfg = loader.get_persona_config()
        chat_cfg = loader.get_chat_config()

        self.client = DeepSeekClient(
            api_key=api["api_key"], base_url=api["base_url"],
            model=api["model"], temperature=api.get("temperature", 0.9),
            max_tokens=api.get("max_tokens", 1024), top_p=api.get("top_p", 0.95),
        )
        self.persona = Persona(persona_cfg, memories_path=MEMORIES_FILE)
        system_prompt = self.persona.build_system_prompt()
        self.session = ChatSession(system_prompt,
                                    min(chat_cfg.get("max_history_turns", MAX_HISTORY), MAX_HISTORY))

        self.weflow = WeFlowClient()
        self.sender = WeChatSender()

    # ── 会话发现 ────────────────────────────────────────

    def discover_target(self) -> bool:
        print(f"{Colors.DIM}  查找目标联系人...{Colors.RESET}")
        sessions = self.weflow.get_sessions()
        SYSTEM_IDS = {"filehelper", "weixin", "medianote", "newsapp", "qmessage"}
        privates = [
            s for s in sessions
            if s.get("type") != 2
            and s["username"] not in SYSTEM_IDS
            and "文件传输" not in (s.get("displayName", "") or "")
        ]
        if not privates:
            print(f"{Colors.RED}  ❌ 未找到可用私聊！{Colors.RESET}")
            return False
        privates.sort(key=lambda s: s.get("lastTimestamp", 0) or 0, reverse=True)
        target = privates[0]
        self.target_talker = target["username"]
        self.target_display_name = target.get("displayName", "") or self.target_talker
        print(f"{Colors.GREEN}  ✅ 目标联系人: {self.target_display_name}{Colors.RESET}")
        return True

    # ── 消息获取 ────────────────────────────────────────

    def _get_new_messages(self) -> list[dict]:
        try:
            msgs = self.weflow.get_messages(self.target_talker, limit=10, offset=0)
        except Exception as e:
            print(f"{Colors.RED}[!] 获取消息失败: {e}{Colors.RESET}")
            return []

        if not msgs:
            return []

        new_msgs = []
        for msg in msgs:
            msg_id = msg.get("localId", 0)
            if msg_id <= self._last_msg_id:
                continue
            if msg.get("isSend", 0) != 0:
                self._last_msg_id = max(self._last_msg_id, msg_id)
                continue
            content = msg.get("parsedContent", "") or msg.get("content", "")
            content = content.strip()
            if not content:
                self._last_msg_id = max(self._last_msg_id, msg_id)
                continue
            if content.startswith("<?xml") or content.startswith("<sysmsg"):
                self._last_msg_id = max(self._last_msg_id, msg_id)
                continue

            new_msgs.append({"id": msg_id, "content": content, "time": msg.get("createTime", 0)})
            self._last_msg_id = max(self._last_msg_id, msg_id)

        return new_msgs

    # ── 真人延迟计算 ─────────────────────────────────────

    def _calc_reading_delay(self, text: str) -> float:
        """根据消息长度计算阅读时间。"""
        char_count = len(text)
        base_delay = char_count / READING_SPEED_CPM * 60
        # 加 30% 随机抖动
        return base_delay * (0.7 + random.random() * 0.6)

    def _calc_thinking_delay(self) -> float:
        """随机思考时间（模拟打字前想怎么回）。"""
        return MIN_THINKING_TIME + random.random() * (MAX_THINKING_TIME - MIN_THINKING_TIME)

    # ── 时间段感知 ───────────────────────────────────────

    @staticmethod
    def _get_time_context() -> str:
        """根据当前时间生成情境提示，让回复贴合真实作息。"""
        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()  # 0=周一, 6=周日
        is_weekend = weekday >= 5

        if is_weekend:
            if hour < 9:
                return "现在是周末早上，你还在睡懒觉或者刚醒，回复慵懒简短"
            elif hour < 12:
                return "现在是周末上午，你刚起床没多久，可能在家瘫着"
            elif hour < 14:
                return "现在是周末中午，你可能在吃午饭或者刚吃完"
            elif hour < 18:
                return "现在是周末下午，你可能在外面玩、逛街或者在家休息"
            elif hour < 22:
                return "现在是周末晚上，你可能在看剧、吃好吃的或者和朋友一起"
            else:
                return "现在是周末深夜，你可能在熬夜刷手机或者准备睡了，回复简短慵懒"
        else:
            if hour < 8:
                return "现在是工作日早上，你刚醒或者还在赖床，准备起床上班，回复简短"
            elif hour < 9:
                return "现在是工作日早上，你在通勤路上或者刚到公司"
            elif hour < 12:
                return "现在是工作时间，你在上班摸鱼偷偷回消息"
            elif hour < 14:
                return "现在是午休时间，你在吃午饭或者刚吃完休息"
            elif hour < 18:
                return "现在是下午工作时间，你在上班，可能有点累在摸鱼"
            elif hour < 19:
                return "现在是下班时间，你刚下班或者在路上，终于解放了"
            elif hour < 22:
                return "现在是晚上休息时间，你下班在家，比较放松，可能在看剧吃零食"
            elif hour < 24:
                return "现在是深夜，你可能在刷手机准备睡了，回复会变简短"
            else:
                return "现在是凌晨，你还没睡，但已经很困了，回复非常简短慵懒"

    # ── AI 回复 ─────────────────────────────────────────

    def _generate_reply(self, user_msgs: list[str]) -> str:
        if len(user_msgs) == 1:
            combined = user_msgs[0]
        else:
            combined = "\n".join(f"[{i+1}] {m}" for i, m in enumerate(user_msgs))

        # 注入时间段情境
        time_ctx = self._get_time_context()
        time_msg = f"【当前情境】{time_ctx}\n\n对方说：「{combined}」"

        self.session.add_user_message(time_msg)
        self._conversation_log.append(f"对方: {combined}")

        try:
            reply = self.client.chat(self.session.get_messages())
            reply = reply.strip()
            reply = reply.replace("**", "").replace("##", "").replace("`", "")
            self.session.add_assistant_message(reply)
            self._conversation_log.append(f"{self.persona.name}: {reply}")
            return reply
        except Exception as e:
            print(f"{Colors.RED}[!] LLM 错误: {e}{Colors.RESET}")
            return ""

    # ── 记忆 ────────────────────────────────────────────

    def _maybe_extract_memories(self):
        if self._reply_count > 0 and self._reply_count % AUTO_MEMORY_INTERVAL == 0:
            print(f"\n{Colors.BLUE}🧠 自动提取记忆 (第 {self._reply_count} 轮)...{Colors.RESET}")
            new_facts = self.memory_store.extract_from_conversation(
                self._conversation_log, self.client
            )
            if new_facts:
                for fact in new_facts:
                    print(f"{Colors.BLUE}  + {fact}{Colors.RESET}")
                self._rebuild_prompt()
            else:
                print(f"{Colors.DIM}  (没有新的可提取信息){Colors.RESET}")

    def _rebuild_prompt(self):
        new_prompt = self.persona.build_system_prompt()
        self.session._messages[0] = {"role": "system", "content": new_prompt}

    # ── 发送回复 ────────────────────────────────────────

    def _send_reply(self, text: str):
        if self.dry_run:
            print(f"{Colors.YELLOW}  [演习] {text}{Colors.RESET}")
            self._last_reply_content = text
            return
        self.sender.send(text)
        self._last_reply_content = text
        ts = datetime.now().strftime("%H:%M:%S")
        typing_sec = len(text) / BASE_TYPING_CPM * 60
        print(f"{Colors.MAGENTA}[{ts}] {self.persona.name} > {text}"
              f"{Colors.DIM}  (输入 ~{typing_sec:.1f}s){Colors.RESET}")

    def _send_multipart(self, text: str):
        """像真人一样分行连发，分段之间有随机间隔。"""
        parts = [p.strip() for p in text.split("\n") if p.strip()]
        if not parts:
            return
        if len(parts) == 1:
            self._send_reply(parts[0])
            return

        for i, part in enumerate(parts):
            self._send_reply(part)
            if i < len(parts) - 1:
                gap = MULTI_PART_MIN_GAP + random.random() * (
                    MULTI_PART_MAX_GAP - MULTI_PART_MIN_GAP
                )
                if not self.dry_run:
                    print(f"{Colors.DIM}  (停顿 {gap:.1f}s)...{Colors.RESET}")
                    time.sleep(gap)

    # ── 随机轮询间隔 ────────────────────────────────────

    def _get_poll_interval(self) -> float:
        """获取随机轮询间隔，偶尔插入长暂停模拟放下手机。"""
        return POLL_INTERVAL_MIN + random.random() * (
            POLL_INTERVAL_MAX - POLL_INTERVAL_MIN
        )

    # ── 主循环 ──────────────────────────────────────────

    def run(self):
        mem_summary = self.memory_store.get_summary()
        print(f"\n{Colors.BLUE}{mem_summary}{Colors.RESET}\n")

        print(f"{'='*52}")
        print(f"  {self.persona.avatar} {self.persona.name} 微信 AI 女友 v6")
        print(f"  ")
        print(f"  📡 读取: WeFlow API  |  📤 发送: SendInput(扫描码)")
        print(f"  👤 对方: {self.target_display_name}")
        print(f"  🎯 模式: {'🏃 演习' if self.dry_run else '🤖 自动回复'}")
        print(f"  🧠 记忆: 每 {AUTO_MEMORY_INTERVAL} 轮自动提取")
        print(f"  ⏱️  轮询: {POLL_INTERVAL_MIN}-{POLL_INTERVAL_MAX}s 随机")
        print(f"        偶尔长暂停 {POLL_LONG_PAUSE_MIN}-{POLL_LONG_PAUSE_MAX}s ({int(LONG_PAUSE_PROBABILITY*100)}%)")
        print(f"  ⌨️  输入: SendInput 扫描码 + 鼠标抖动")
        print(f"  💬 延迟: 阅读({READING_SPEED_CPM}字/分) + 思考({MIN_THINKING_TIME}-{MAX_THINKING_TIME}s)")
        print(f"  ")
        print(f"  💡 记忆修改: 编辑 data/memories.json 后桥接自动加载")
        print(f"  ⚠️  保持微信窗口打开，聊天窗口为当前对话")
        print(f"  按 Ctrl+C 停止")
        print(f"{'='*52}\n")

        # 同步初始消息 ID
        msgs = self.weflow.get_messages(self.target_talker, limit=5, offset=0)
        if msgs:
            self._last_msg_id = max(m.get("localId", 0) for m in msgs)
        print(f"{Colors.DIM}  已同步，最新消息 ID: {self._last_msg_id}{Colors.RESET}")
        print(f"{Colors.DIM}  开始监听新消息...{Colors.RESET}\n")

        self._running = True

        while self._running:
            try:
                if not self.sender.is_valid():
                    print(f"{Colors.YELLOW}[!] 微信窗口丢失，重试...{Colors.RESET}")
                    try:
                        self.sender._find_window()
                    except Exception:
                        time.sleep(5)
                        continue

                new_msgs = self._get_new_messages()

                for msg in new_msgs:
                    content = msg["content"]
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"\n{Colors.CYAN}[{ts}] {self.target_display_name} > {content}{Colors.RESET}")

                    # ── 真人延迟: 阅读 + 思考 ──
                    reading_delay = self._calc_reading_delay(content)
                    thinking_delay = self._calc_thinking_delay()
                    total_delay = reading_delay + thinking_delay

                    if not self.dry_run:
                        print(f"{Colors.DIM}  📖 {reading_delay:.1f}s + "
                              f"💭 {thinking_delay:.1f}s = "
                              f"{total_delay:.1f}s{Colors.RESET}")
                        time.sleep(total_delay)

                    # 生成回复（单条消息立即回复）
                    reply = self._generate_reply([content])
                    if not reply:
                        self._consecutive_errors += 1
                        continue

                    self._send_multipart(reply)
                    self._reply_count += 1
                    self._consecutive_errors = 0

                    self._maybe_extract_memories()

                # ── 随机轮询间隔 ──
                poll_interval = self._get_poll_interval()
                if poll_interval > POLL_INTERVAL_MAX:
                    print(f"{Colors.DIM}  😴 长暂停 {poll_interval:.0f}s...{Colors.RESET}")
                time.sleep(poll_interval)

            except KeyboardInterrupt:
                self._running = False
                print(f"\n{Colors.GREEN}👋 {self.persona.name} 已下线，" +
                      f"本次回复 {self._reply_count} 条{Colors.RESET}")
                break
            except Exception as e:
                self._consecutive_errors += 1
                print(f"{Colors.RED}[!] {e}{Colors.RESET}")
                if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(f"{Colors.RED}[!] 连续异常过多，停止{Colors.RESET}")
                    break
                time.sleep(5)


# ============================================================
# 入口
# ============================================================

def main():
    _ensure_utf8()

    import argparse
    parser = argparse.ArgumentParser(description="微信 AI 女友桥接 v6")
    parser.add_argument("--dry-run", action="store_true", help="演习模式")
    parser.add_argument("--config", type=str, default="config.yaml", help="配置文件")
    parser.add_argument("--memory-show", action="store_true", help="显示当前所有记忆")
    parser.add_argument("--profile", action="store_true", help="查看完整人设档案（人设+记忆）")
    parser.add_argument("--profile-edit", action="store_true", help="打开人设和记忆文件进行编辑")
    args = parser.parse_args()

    CONFIG_PATH = args.config
    PROJECT_DIR = Path(__file__).resolve().parent
    MEMORIES_PATH = str(PROJECT_DIR / "data" / "memories.json")

    # ── 档案查看 ──
    if args.profile:
        _ensure_utf8()
        print(f"{Colors.CYAN}{'='*56}{Colors.RESET}")
        print(f"{Colors.CYAN}  🌸 AI 女友 — 完整人设档案{Colors.RESET}")
        print(f"{Colors.CYAN}{'='*56}{Colors.RESET}")

        loader = ConfigLoader(CONFIG_PATH)
        persona_cfg = loader.get_persona_config()
        style = persona_cfg.get("speaking_style", {})

        print(f"\n{Colors.YELLOW}【基础信息】{Colors.RESET}")
        print(f"  名字: {persona_cfg['name']}")
        print(f"  年龄: {persona_cfg.get('age', '?')}")
        print(f"  头像: {persona_cfg.get('avatar', '')}")

        print(f"\n{Colors.YELLOW}【性格描述】{Colors.RESET}")
        personality = persona_cfg.get("personality", "")
        for line in personality.strip().split("\n"):
            print(f"  {line.strip()}")

        print(f"\n{Colors.YELLOW}【说话风格】{Colors.RESET}")
        print(f"  语气: {style.get('tone', '')}")
        print(f"  句长: {style.get('sentence_length', '')}")
        habits = style.get("habits", [])
        if habits:
            print(f"  习惯:")
            for h in habits:
                print(f"    · {h}")
        topics = style.get("topics", [])
        if topics:
            print(f"  话题:")
            for t in topics:
                print(f"    · {t}")

        print(f"\n{Colors.YELLOW}【记忆】{Colors.RESET}")
        store = MemoryStore()
        print(store.get_summary())

        print(f"\n{Colors.DIM}── 文件位置 ──{Colors.RESET}")
        print(f"{Colors.DIM}  人设: {PROJECT_DIR / CONFIG_PATH}{Colors.RESET}")
        print(f"{Colors.DIM}  记忆: {MEMORIES_PATH}{Colors.RESET}")
        print(f"{Colors.DIM}  编辑: python wx_bridge.py --profile-edit{Colors.RESET}")
        return

    # ── 打开编辑 ──
    if args.profile_edit:
        _ensure_utf8()
        import subprocess
        config_file = str(PROJECT_DIR / CONFIG_PATH)
        memories_file = MEMORIES_PATH

        print(f"{Colors.CYAN}📝 人设和记忆文件{Colors.RESET}")
        print()
        print(f"{Colors.YELLOW}  🧑 人设 (性格、说话风格):{Colors.RESET}")
        print(f"     {config_file}")
        print(f"     修改: persona 下的 name / age / personality / speaking_style")
        print()
        print(f"{Colors.YELLOW}  🧠 记忆 (个人信息、里程碑、梗):{Colors.RESET}")
        print(f"     {memories_file}")
        print(f"     修改: 直接编辑 JSON，分类为 personal_info / relationship_milestones")
        print(f"            inside_jokes / preferences")
        print()

        for editor in ["notepad", "code"]:
            try:
                subprocess.Popen([editor, config_file])
                subprocess.Popen([editor, memories_file])
                print(f"{Colors.GREEN}  已用 {editor} 打开两个文件{Colors.RESET}")
                break
            except Exception:
                continue
        else:
            print(f"{Colors.DIM}  手动打开上述路径即可编辑{Colors.RESET}")
        return

    if args.memory_show:
        _ensure_utf8()
        store = MemoryStore()
        print(store.get_summary())
        print(f"\n{Colors.DIM}  文件: {MEMORIES_PATH}{Colors.RESET}")
        return

    print(f"{Colors.YELLOW}╔{'═'*48}╗{Colors.RESET}")
    print(f"{Colors.YELLOW}║  微信 AI 女友 v6 — SendInput + 随机轮询 + 真人延迟{' '*1}║{Colors.RESET}")
    print(f"{Colors.YELLOW}╚{'═'*48}╝{Colors.RESET}")
    print()

    # 检查 WeFlow
    print(f"{Colors.DIM}  检查 WeFlow API...{Colors.RESET}")
    try:
        wf = WeFlowClient()
        wf.get_sessions(limit=1)
        print(f"{Colors.GREEN}  ✅ WeFlow API 已连接{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}  ❌ WeFlow API 不可用: {e}{Colors.RESET}")
        sys.exit(1)

    bridge = AIWeChatBridge(config_path=args.config, dry_run=args.dry_run)
    if not bridge.discover_target():
        sys.exit(1)
    bridge.run()


if __name__ == "__main__":
    main()
