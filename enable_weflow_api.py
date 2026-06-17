"""Enable WeFlow HTTP API in config."""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

config_path = r"C:\Users\Administrator\AppData\Roaming\weflow\WeFlow-config.json"
with open(config_path, "r", encoding="utf-8") as f:
    config = json.load(f)

# Enable HTTP API
config["httpApiEnabled"] = True
config["httpApiPort"] = 5031
config["httpApiHost"] = "127.0.0.1"
config["httpApiToken"] = "ai-girlfriend-bridge-token"

with open(config_path, "w", encoding="utf-8") as f:
    json.dump(config, f, ensure_ascii=False, indent="\t")

print("API enabled!")
print(f"  Port: {config['httpApiPort']}")
print(f"  Token: {config['httpApiToken']}")
print(f"  myWxid: {config.get('myWxid', 'N/A')}")
print(f"  dbPath: {config.get('dbPath', 'N/A')}")
print()
print("Please restart WeFlow for changes to take effect.")
