"""
微信聊天记录导出脚本 v3
=======================
两阶段流程:
  阶段1: python export_wechat.py extract-key    (提取密钥，需管理员)
  阶段2: python export_wechat.py export           (导出聊天记录，无需管理员)

底层依赖 WeFlow 的 native DLL:
  - wx_key.dll    : 内存注入提取 DB 密钥
  - wcdb_api.dll  : 解密 WCDB 数据库 + 读取消息
"""

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import (
    c_char_p, c_bool, c_uint32, c_int32, c_int64, c_void_p,
    POINTER, byref, create_string_buffer
)
from pathlib import Path

# ============================================================
# 路径配置
# ============================================================
PROJECT_DIR = Path(__file__).resolve().parent
WECHAT_DATA_DIR = Path.home() / "Documents" / "WeChat Files"
WEFLOW_RESOURCES = PROJECT_DIR / "WeFlow-latest-from-hicccc77" / "resources"
WX_KEY_DLL = WEFLOW_RESOURCES / "key" / "win32" / "x64" / "wx_key.dll"
WCDB_API_DLL = WEFLOW_RESOURCES / "wcdb" / "win32" / "x64" / "wcdb_api.dll"
KEY_FILE = PROJECT_DIR / "wechat_db_key.txt"
OUTPUT_DIR = PROJECT_DIR / "data" / "chat_export"


# ============================================================
# 阶段1: 提取 DB 密钥
# ============================================================

def find_wechat_pids():
    """查找所有 Weixin.exe / WeChat.exe 进程 PID"""
    pids = []
    for exe_name in ["Weixin.exe", "WeChat.exe"]:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.strip().split("\n"):
                line = line.strip().strip('"')
                if not line or line.startswith("INFO:"):
                    continue
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2:
                    try:
                        pid = int(parts[1])
                        if pid > 0 and pid not in pids:
                            pids.append(pid)
                    except ValueError:
                        pass
        except Exception:
            pass
    return pids


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def extract_db_key(pid, timeout_seconds=120):
    """
    通过 wx_key.dll Hook 微信进程，轮询提取数据库密钥。
    需要用户在微信中浏览聊天消息以触发密钥计算。
    """
    if not WX_KEY_DLL.exists():
        print(f"[!] 错误: wx_key.dll 不存在于 {WX_KEY_DLL}")
        return None

    print(f"[*] 加载 wx_key.dll ...")
    try:
        dll = ctypes.WinDLL(str(WX_KEY_DLL))
    except Exception as e:
        print(f"[!] 加载 DLL 失败: {e}")
        return None

    # 函数签名
    dll.InitializeHook.argtypes = [c_uint32]
    dll.InitializeHook.restype = c_bool
    dll.PollKeyData.argtypes = [c_char_p, c_int32]
    dll.PollKeyData.restype = c_bool
    dll.GetStatusMessage.argtypes = [c_char_p, c_int32, POINTER(c_int32)]
    dll.GetStatusMessage.restype = c_bool
    dll.CleanupHook.argtypes = []
    dll.CleanupHook.restype = c_bool
    dll.GetLastErrorMsg.argtypes = []
    dll.GetLastErrorMsg.restype = c_char_p

    print(f"[*] 初始化 Hook (目标 PID: {pid})...")
    if not dll.InitializeHook(c_uint32(pid)):
        error_fn = dll.GetLastErrorMsg
        err_str = ""
        try:
            err_raw = error_fn()
            if err_raw:
                err_str = err_raw.decode("utf-8", errors="replace")
        except Exception:
            pass

        # 备选: 获取状态消息
        if not err_str:
            buf = create_string_buffer(256)
            level = c_int32(0)
            dll.GetStatusMessage(buf, len(buf), byref(level))
            err_str = buf.value.decode("utf-8", errors="replace").strip("\x00").strip()

        print(f"[!] Hook 初始化失败: {err_str or '未知错误'}")
        if "ACCESS_DENIED" in (err_str or "") or "权限" in (err_str or ""):
            print("[!] >> 请以管理员身份重新运行此脚本 <<")
        return None

    print("[*] Hook 已安装，开始轮询密钥...")
    print("[*] >>> 请在微信中打开几个聊天窗口，上下滚动消息！<<<")
    print("[*]     这会触发微信在内存中计算数据库密钥。")

    key_buffer = create_string_buffer(128)
    deadline = time.time() + timeout_seconds
    last_status = ""
    last_progress_tick = -1

    while time.time() < deadline:
        if dll.PollKeyData(key_buffer, len(key_buffer)):
            key = key_buffer.value.decode("utf-8", errors="replace").strip("\x00").strip()
            if len(key) == 64 and all(c in "0123456789abcdefABCDEF" for c in key):
                print(f"\n[+] ✅ 密钥获取成功!")
                print(f"    {key[:32]}")
                print(f"    {key[32:]}")
                dll.CleanupHook()
                return key

        # 定期获取状态
        status_buf = create_string_buffer(256)
        level = c_int32(0)
        if dll.GetStatusMessage(status_buf, len(status_buf), byref(level)):
            msg = status_buf.value.decode("utf-8", errors="replace").strip("\x00").strip()
            if msg and msg != last_status:
                print(f"    [{level.value}] {msg}")
                last_status = msg

        # 每秒提示一次
        elapsed = int(timeout_seconds - (deadline - time.time()))
        tick = elapsed // 5
        if tick > last_progress_tick:
            remaining = max(0, int(deadline - time.time()))
            print(f"    ⏳ 等待中... 已 {elapsed}s / {timeout_seconds}s (剩余 {remaining}s)")
            last_progress_tick = tick

        time.sleep(0.15)

    dll.CleanupHook()
    print(f"\n[!] 密钥获取超时 ({timeout_seconds}s)")
    return None


def find_account_dirs():
    """查找所有微信账号目录（包含 MSG*.db 的 wxid_* 目录）"""
    accounts = []
    if not WECHAT_DATA_DIR.exists():
        return accounts

    for d in sorted(WECHAT_DATA_DIR.iterdir()):
        if not d.is_dir() or not d.name.startswith("wxid_"):
            continue
        msg_dir = d / "Msg" / "Multi"
        if not msg_dir.exists():
            continue
        db_files = list(msg_dir.glob("MSG*.db"))
        if not db_files:
            continue
        total_size = sum(f.stat().st_size for f in db_files)
        if total_size > 0:
            accounts.append({
                "name": d.name,
                "path": str(d),
                "msg_dir": str(msg_dir),
                "db_size_mb": round(total_size / 1024 / 1024, 1),
                "db_count": len(db_files),
            })
    return accounts


def cmd_extract_key():
    """阶段1: 提取数据库密钥"""
    print("=" * 60)
    print("  阶段1: 提取微信数据库密钥")
    print("=" * 60)
    print()

    if not is_admin():
        print("[!] ⚠️  未以管理员身份运行!")
        print("[!] 密钥提取需要管理员权限才能注入微信进程。")
        print("[!] 请右键点击 PowerShell/CMD → 以管理员身份运行，然后重试。")
        print()
        # 仍然继续，让用户看到完整流程
        print("[*] 将以普通权限继续（很可能会失败）...")
        print()

    # Step 1: 找微信进程
    print("[1/3] 查找微信进程...")
    pids = find_wechat_pids()
    if not pids:
        print("[!] 未找到微信进程 (Weixin.exe / WeChat.exe)")
        print("[!] 请先启动并登录微信！")
        return None

    pid = min(pids)  # 主进程通常 PID 最小
    print(f"[+] 找到 {len(pids)} 个微信进程: {pids}")
    print(f"[+] 使用主进程 PID: {pid}")

    # Step 2: 找账号目录
    print("\n[2/3] 查找微信账号目录...")
    accounts = find_account_dirs()
    if not accounts:
        print("[!] 未找到包含聊天记录的账号目录")
        return None

    print(f"[+] 找到 {len(accounts)} 个账号:")
    for acc in accounts:
        print(f"    {acc['name']}  (数据库: {acc['db_size_mb']} MB, {acc['db_count']} 文件)")

    # Step 3: 提取密钥
    print(f"\n[3/3] 提取数据库密钥...")
    print(f"[!] ⚠️  请在微信中打开聊天窗口、滚动消息来触发密钥计算!")
    print()

    db_key = extract_db_key(pid, timeout_seconds=120)

    if not db_key:
        # 保存已获信息供手动排查
        print("\n[*] 保存已获取的信息...")
        info = {"pid": pid, "accounts": [a["name"] for a in accounts]}
        with open(KEY_FILE, "w", encoding="utf-8") as f:
            f.write(f"pid={info['pid']}\n")
            for name in info["accounts"]:
                f.write(f"account={name}\n")
            f.write("db_key=NONE_EXTRACTED\n")
        print(f"[*] 信息已保存到: {KEY_FILE}")
        print()
        print("💡 提示：如果一直超时，可以尝试:")
        print("   1. 关闭微信，重新打开，立即运行此脚本")
        print("   2. 在微信中多打开几个不同的聊天窗口")
        print("   3. 确认以管理员身份运行")
        print("   4. 临时关闭杀毒软件/防火墙")
        return None

    # 保存密钥
    print(f"\n[*] 保存密钥...")
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        f.write(f"db_key={db_key}\n")
        f.write(f"pid={pid}\n")
        for acc in accounts:
            f.write(f"account={acc['name']}\n")
            f.write(f"account_path={acc['path']}\n")
            f.write(f"account_msg_dir={acc['msg_dir']}\n")
    print(f"[+] ✅ 密钥已保存到: {KEY_FILE}")
    print()
    print("=" * 60)
    print("  下一步: python export_wechat.py export")
    print("=" * 60)
    return db_key


# ============================================================
# 阶段2: 解密数据库 + 导出聊天记录
# ============================================================

def load_key_file():
    """加载已保存的密钥和账号信息"""
    if not KEY_FILE.exists():
        print(f"[!] 密钥文件不存在: {KEY_FILE}")
        print("[!] 请先运行: python export_wechat.py extract-key")
        return None

    info = {"db_key": None, "accounts": []}
    with open(KEY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("db_key="):
                info["db_key"] = line.split("=", 1)[1]
            elif line.startswith("account="):
                info["accounts"].append(line.split("=", 1)[1])
            elif line.startswith("account_path="):
                pass  # 暂时只用 account name

    if not info["db_key"] or info["db_key"] == "NONE_EXTRACTED":
        print("[!] 密钥尚未提取成功")
        print("[!] 请先运行: python export_wechat.py extract-key")
        return None

    return info


class WCDBReader:
    """通过 wcdb_api.dll 读取微信加密数据库"""

    def __init__(self):
        if not WCDB_API_DLL.exists():
            raise FileNotFoundError(f"wcdb_api.dll 不存在: {WCDB_API_DLL}")

        self.dll = ctypes.WinDLL(str(WCDB_API_DLL))
        self._setup_functions()
        self.handle = None
        self._initialized = False

    def _setup_functions(self):
        """设置所有 wcdb_api 函数签名"""
        dll = self.dll

        dll.wcdb_init.argtypes = []
        dll.wcdb_init.restype = c_int32

        dll.wcdb_shutdown.argtypes = []
        dll.wcdb_shutdown.restype = c_int32

        dll.wcdb_open_account.argtypes = [c_char_p, c_char_p, POINTER(c_int64)]
        dll.wcdb_open_account.restype = c_int32

        dll.wcdb_close_account.argtypes = [c_int64]
        dll.wcdb_close_account.restype = c_int32

        dll.wcdb_get_sessions.argtypes = [c_int64, POINTER(c_void_p)]
        dll.wcdb_get_sessions.restype = c_int32

        dll.wcdb_get_messages.argtypes = [
            c_int64, c_char_p, c_int32, c_int32, POINTER(c_void_p)
        ]
        dll.wcdb_get_messages.restype = c_int32

        dll.wcdb_get_message_count.argtypes = [c_int64, c_char_p, POINTER(c_int32)]
        dll.wcdb_get_message_count.restype = c_int32

        dll.wcdb_get_contacts_compact.argtypes = [c_int64, c_char_p, POINTER(c_void_p)]
        dll.wcdb_get_contacts_compact.restype = c_int32

        dll.wcdb_get_display_names.argtypes = [c_int64, c_char_p, POINTER(c_void_p)]
        dll.wcdb_get_display_names.restype = c_int32

        dll.wcdb_free_string.argtypes = [c_void_p]
        dll.wcdb_free_string.restype = None

        # 可选函数
        try:
            dll.wcdb_get_group_members.argtypes = [c_int64, c_char_p, POINTER(c_void_p)]
            dll.wcdb_get_group_members.restype = c_int32
            self._has_group_members = True
        except Exception:
            self._has_group_members = False

        try:
            dll.wcdb_get_group_nicknames.argtypes = [c_int64, c_char_p, POINTER(c_void_p)]
            dll.wcdb_get_group_nicknames.restype = c_int32
            self._has_group_nicknames = True
        except Exception:
            self._has_group_nicknames = False

    def _check(self, status: int, operation: str) -> bool:
        if status == 0:
            return True
        print(f"  [!] wcdb {operation} 失败 (status={status})")
        return False

    def _read_json(self, ptr) -> dict | list | None:
        """从原生指针读取 JSON 字符串并解析"""
        if not ptr:
            return None
        try:
            raw = ctypes.cast(ptr, c_char_p).value
            if raw:
                return json.loads(raw.decode("utf-8", errors="replace"))
        except Exception as e:
            print(f"  [!] JSON 解析失败: {e}")
        finally:
            try:
                self.dll.wcdb_free_string(ptr)
            except Exception:
                pass
        return None

    def init(self):
        if self._initialized:
            return True
        status = self.dll.wcdb_init()
        if status != 0:
            print(f"[!] wcdb_init 失败 (status={status})")
            return False
        self._initialized = True
        return True

    def open(self, account_dir: str, db_key: str):
        """打开微信账号数据库"""
        if not self._initialized:
            self.init()

        handle = c_int64(0)
        path = os.path.join(account_dir, "Msg")
        status = self.dll.wcdb_open_account(
            path.encode("utf-8"), db_key.encode("utf-8"), byref(handle)
        )
        if status != 0:
            print(f"[!] 无法打开账号数据库: {account_dir} (status={status})")
            return False

        self.handle = handle.value
        print(f"[+] 账号已打开 (handle={self.handle})")
        return True

    def close(self):
        if self.handle:
            self.dll.wcdb_close_account(self.handle)
            self.handle = None

    def shutdown(self):
        self.close()
        if self._initialized:
            self.dll.wcdb_shutdown()
            self._initialized = False

    def get_sessions(self) -> list:
        """获取所有会话列表"""
        out = c_void_p(0)
        status = self.dll.wcdb_get_sessions(self.handle, byref(out))
        if status != 0:
            print(f"[!] 获取会话列表失败 (status={status})")
            return []
        result = self._read_json(out)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "sessions" in result:
            return result["sessions"]
        return []

    def get_messages(self, username: str, limit=100, offset=0) -> list:
        """获取指定会话的消息"""
        out = c_void_p(0)
        status = self.dll.wcdb_get_messages(
            self.handle, username.encode("utf-8"), limit, offset, byref(out)
        )
        if status != 0:
            return []
        result = self._read_json(out)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "messages" in result:
            return result["messages"]
        return []

    def get_message_count(self, username: str) -> int:
        """获取会话消息总数"""
        count = c_int32(0)
        status = self.dll.wcdb_get_message_count(
            self.handle, username.encode("utf-8"), byref(count)
        )
        if status != 0:
            return -1
        return count.value

    def get_contacts(self, usernames: list | None = None) -> list:
        """获取联系人信息"""
        usernames_json = json.dumps(usernames) if usernames else json.dumps([])
        out = c_void_p(0)
        status = self.dll.wcdb_get_contacts_compact(
            self.handle, usernames_json.encode("utf-8"), byref(out)
        )
        if status != 0:
            return []
        result = self._read_json(out)
        if isinstance(result, list):
            return result
        return []

    def get_display_names(self, usernames: list) -> dict:
        """批量获取用户显示名称"""
        usernames_json = json.dumps(usernames)
        out = c_void_p(0)
        status = self.dll.wcdb_get_display_names(
            self.handle, usernames_json.encode("utf-8"), byref(out)
        )
        if status != 0:
            return {}
        result = self._read_json(out)
        if isinstance(result, dict):
            return result
        return {}


def cmd_export():
    """阶段2: 导出聊天记录"""
    print("=" * 60)
    print("  阶段2: 导出微信聊天记录")
    print("=" * 60)
    print()

    # 加载密钥
    info = load_key_file()
    if not info:
        return None

    db_key = info["db_key"]
    print(f"[+] 已加载密钥: {db_key[:16]}...{db_key[-16:]}")
    print(f"[+] 账号: {info['accounts']}")

    # 初始化 WCDB reader
    print("\n[*] 初始化 WCDB 引擎...")
    reader = WCDBReader()

    if not reader.init():
        print("[!] WCDB 引擎初始化失败")
        return None

    exported_any = False
    output_root = OUTPUT_DIR
    output_root.mkdir(parents=True, exist_ok=True)

    try:
        for account_name in info["accounts"]:
            account_dir = WECHAT_DATA_DIR / account_name
            if not account_dir.exists():
                print(f"\n[!] 账号目录不存在: {account_dir}")
                continue

            print(f"\n{'=' * 60}")
            print(f"  账号: {account_name}")
            print(f"{'=' * 60}")

            if not reader.open(str(account_dir), db_key):
                continue

            try:
                # 获取会话列表
                print("\n[*] 获取会话列表...")
                sessions = reader.get_sessions()
                if not sessions:
                    print("[!] 未获取到会话列表")
                    continue

                print(f"[+] 找到 {len(sessions)} 个会话")
                print()

                # 按最后消息时间排序
                sessions.sort(
                    key=lambda s: s.get("lastTimestamp", 0) or 0,
                    reverse=True,
                )

                # 显示会话概览
                for i, sess in enumerate(sessions[:30]):
                    name = sess.get("displayName", "") or sess.get("username", "")
                    sess_type = sess.get("type", 0)
                    type_str = {"0": "私聊", "1": "群聊", "2": "群聊"}.get(
                        str(sess_type), f"type={sess_type}"
                    )
                    unread = sess.get("unreadCount", 0)
                    last_ts = sess.get("lastTimestamp", 0)
                    last_time = ""
                    if last_ts:
                        try:
                            last_time = time.strftime(
                                "%Y-%m-%d %H:%M", time.localtime(int(last_ts))
                            )
                        except Exception:
                            last_time = str(last_ts)
                    print(f"  [{i+1:2d}] [{type_str}] {name[:30]:30s}  "
                          f"未读:{unread}  最后:{last_time}")

                if len(sessions) > 30:
                    print(f"  ... 还有 {len(sessions) - 30} 个会话")

                # 询问要导出哪个会话
                print()
                print("-" * 60)
                print("请输入要导出的会话编号（多个用逗号分隔，0=全部，Enter=跳过此账号）:")
                choice = input("> ").strip()

                if not choice:
                    reader.close()
                    continue

                selected = []
                if choice == "0":
                    selected = sessions
                else:
                    indices = [int(x.strip()) for x in choice.split(",") if x.strip().isdigit()]
                    for idx in indices:
                        if 1 <= idx <= len(sessions):
                            selected.append(sessions[idx - 1])

                if not selected:
                    print("[!] 无效选择，跳过")
                    reader.close()
                    continue

                # 导出选中会话
                for sess in selected:
                    username = sess.get("username", "")
                    display_name = sess.get("displayName", "") or username
                    msg_count = reader.get_message_count(username)

                    print(f"\n[*] 导出会话: {display_name} ({username})")
                    print(f"    消息总数: {msg_count}")

                    if msg_count <= 0:
                        print("    (无消息，跳过)")
                        continue

                    # 安全文件名
                    safe_name = "".join(
                        c for c in display_name if c.isalnum() or c in " _-"
                    )[:50].strip()
                    if not safe_name:
                        safe_name = username.replace("@", "_")

                    account_out = output_root / account_name
                    account_out.mkdir(parents=True, exist_ok=True)

                    # 导出为 JSONL (每行一个 JSON 对象，方便流式处理)
                    jsonl_path = account_out / f"{safe_name}.jsonl"
                    json_path = account_out / f"{safe_name}.json"

                    all_messages = []
                    offset = 0
                    batch_size = 2000
                    exported_count = 0

                    with open(jsonl_path, "w", encoding="utf-8") as f_jsonl:
                        while offset < msg_count:
                            msgs = reader.get_messages(username, batch_size, offset)
                            if not msgs:
                                break

                            for msg in msgs:
                                # 标准化格式
                                record = {
                                    "localId": msg.get("localId"),
                                    "serverId": msg.get("serverId", ""),
                                    "createTime": msg.get("createTime", 0),
                                    "isSend": msg.get("isSend", 0),
                                    "sender": msg.get("senderUsername", ""),
                                    "content": msg.get("content", ""),
                                    "parsedContent": msg.get("parsedContent", ""),
                                    "mediaType": msg.get("mediaType", ""),
                                    "mediaFileName": msg.get("mediaFileName", ""),
                                    "localType": msg.get("localType", 0),
                                }
                                f_jsonl.write(json.dumps(record, ensure_ascii=False) + "\n")
                                all_messages.append(record)

                            offset += len(msgs)
                            exported_count += len(msgs)
                            pct = min(100, round(exported_count / msg_count * 100))
                            print(f"    ... {exported_count}/{msg_count} ({pct}%)")

                    # 同时保存一份完整的 JSON
                    with open(json_path, "w", encoding="utf-8") as f_json:
                        json.dump(
                            {
                                "account": account_name,
                                "sessionId": username,
                                "displayName": display_name,
                                "messageCount": exported_count,
                                "exportedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "messages": all_messages,
                            },
                            f_json,
                            ensure_ascii=False,
                            indent=2,
                        )

                    print(f"    ✅ 已导出 {exported_count} 条消息")
                    print(f"       JSONL: {jsonl_path}")
                    print(f"       JSON:  {json_path}")
                    exported_any = True

            finally:
                reader.close()

    finally:
        reader.shutdown()

    if exported_any:
        print(f"\n{'=' * 60}")
        print(f"  导出完成！文件保存在: {output_root}")
        print(f"{'=' * 60}")

    return exported_any


# ============================================================
# 命令行入口
# ============================================================

def main():
    # 设置控制台编码
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    cmd = sys.argv[1] if len(sys.argv) > 1 else ""

    if cmd == "extract-key":
        result = cmd_extract_key()
        if not result:
            sys.exit(1)

    elif cmd == "export":
        result = cmd_export()
        if not result:
            sys.exit(1)

    elif cmd == "status":
        # 查看当前状态
        print("=" * 60)
        print("  微信聊天记录导出 - 状态")
        print("=" * 60)

        print("\n[微信进程]")
        pids = find_wechat_pids()
        if pids:
            print(f"  运行中: PID={pids}")
        else:
            print("  未运行")

        print("\n[微信账号]")
        accounts = find_account_dirs()
        for acc in accounts:
            print(f"  {acc['name']}: {acc['db_size_mb']} MB ({acc['db_count']} DB)")

        print("\n[密钥状态]")
        if KEY_FILE.exists():
            info = load_key_file()
            if info and info.get("db_key") and info["db_key"] != "NONE_EXTRACTED":
                print(f"  ✅ 已提取: {info['db_key'][:16]}...")
            else:
                print("  ❌ 尚未成功提取")
        else:
            print("  ❌ 密钥文件不存在 (需运行 extract-key)")

        print("\n[导出数据]")
        if OUTPUT_DIR.exists():
            total_files = 0
            for f in OUTPUT_DIR.rglob("*.jsonl"):
                total_files += 1
                lines = sum(1 for _ in open(f, "r", encoding="utf-8"))
                print(f"  {f.relative_to(OUTPUT_DIR)}: {lines} 条消息")
            if total_files == 0:
                print("  (无导出文件)")
        else:
            print("  (无导出目录)")

    else:
        print("使用说明:")
        print("  python export_wechat.py extract-key   阶段1: 提取数据库密钥 (需管理员)")
        print("  python export_wechat.py export        阶段2: 导出聊天记录")
        print("  python export_wechat.py status        查看当前状态")
        sys.exit(0)


if __name__ == "__main__":
    main()
