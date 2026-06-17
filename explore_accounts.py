"""Explore both WeChat accounts to identify AI girlfriend's account and chats."""
import sys, io, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pathlib import Path
from export_wechat import WCDBReader, WECHAT_DATA_DIR, load_key_file

info = load_key_file()
if not info:
    print("No key file found!")
    sys.exit(1)

db_key = info["db_key"]
print(f"DB Key: {db_key[:16]}...{db_key[-16:]}")
print(f"Accounts: {info['accounts']}")
print()

reader = WCDBReader()
if not reader.init():
    print("WCDB init failed!")
    sys.exit(1)

try:
    for account_name in info["accounts"]:
        account_dir = WECHAT_DATA_DIR / account_name
        if not account_dir.exists():
            print(f"\n[!] Account dir not found: {account_dir}")
            continue

        print(f"\n{'='*60}")
        print(f"  Account: {account_name}")
        print(f"  Path: {account_dir}")
        print(f"{'='*60}")

        if not reader.open(str(account_dir), db_key):
            print(f"  Failed to open!")
            continue

        try:
            sessions = reader.get_sessions()
            if not sessions:
                print("  No sessions found")
                continue

            # Sort by last message time
            sessions.sort(key=lambda s: s.get("lastTimestamp", 0) or 0, reverse=True)

            print(f"  Total sessions: {len(sessions)}")
            print()

            # Show private chats first (type 0)
            privates = [s for s in sessions if s.get("type", 0) != 2]
            groups = [s for s in sessions if s.get("type", 0) == 2]

            print(f"  --- Private Chats ({len(privates)}) ---")
            for s in privates[:20]:
                name = s.get("displayName", "") or s.get("username", "")
                username = s.get("username", "")
                last_ts = s.get("lastTimestamp", 0)
                last_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(last_ts))) if last_ts else "N/A"
                unread = s.get("unreadCount", 0)
                msg_count = reader.get_message_count(username)
                print(f"  {name[:25]:25s} | msgs:{msg_count:5d} | unread:{unread:3d} | last:{last_time}")
                print(f"    wxid: {username}")

            if groups:
                print(f"\n  --- Group Chats ({len(groups)}) ---")
                for s in groups[:10]:
                    name = s.get("displayName", "") or s.get("username", "")
                    username = s.get("username", "")
                    last_ts = s.get("lastTimestamp", 0)
                    last_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(last_ts))) if last_ts else "N/A"
                    print(f"  {name[:25]:25s} | last:{last_time}")
                    print(f"    id: {username}")

        finally:
            reader.close()

finally:
    reader.shutdown()

print("\nDone.")
