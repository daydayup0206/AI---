# 起初人们都不理解痞老板

> AI 伴侣，部署在微信中。用人话训练，不是用 prompt 演。

## 它是什么

一个能自动回复微信消息的 AI 伴侣。和大多数 AI 女友不同，它不是靠一段精心编写的 prompt 来扮演角色，而是从你和 ta 的真实聊天记录中检索最相似的对话作为参考来生成回复。

简单说：你给聊天记录，它帮你"还原"那个人说话的方式。

## 工作流程

```
收到微信消息 → 向量检索 TOP-5 最相似历史对话 → 注入 prompt → LLM 生成 → 自动发送
                                   ↑
                    24,000+ 个真实对话对（微信 + 抖音）
```

- 检索到的真实对话作为风格参考，prompt 只给人物锚点
- 时间衰减权重：最近的消息参考价值更高，但老的也不丢
- 支持微信 + 抖音双平台聊天记录混合索引

## 技术栈

| 层 | 选型 |
|------|------|
| 大模型 | DeepSeek（OpenAI 兼容，可替换为其他模型） |
| 向量检索 | ChromaDB + sentence-transformers（本地运行） |
| 微信接入 | WeFlow API 读取 + Windows SendInput 模拟输入 |
| 数据导入 | douyin-chat-export 导出抖音聊天 |
| 语言 | Python 3.10+ |

## 复现步骤

### 1. 准备聊天数据

**微信**：用 WeFlow 导出聊天记录为 JSON。本项目提供了解析脚本 `parse_chat_export.py`，处理为对话对格式。

**抖音**：用 [douyin-chat-export](https://github.com/TeamBreakerr/douyin-chat-export) 导出 ChatLab JSONL。

### 2. 安装依赖

```bash
conda create -n ai-girlfriend python=3.10
conda activate ai-girlfriend
pip install -r requirements.txt
```

### 3. 配置

```bash
cp config.example.yaml config.yaml
```

填入：
- DeepSeek API Key
- 人设描述（建议先用 `scripts/analyze_style_deep.py` 分析聊天记录，用数据驱动的方式写）
- RAG 参数（默认即可）

### 4. 构建向量索引

```bash
python scripts/build_index.py
```

这一步会把对话对嵌入为向量存入 ChromaDB。

### 5. 启动

```bash
python wx_bridge.py    # 微信自动回复模式
# 或
python run.py          # 终端聊天测试
```

微信模式需要 WeFlow 在后台运行（`127.0.0.1:5031`），且微信 PC 客户端保持打开。

## 目录结构

```
├── config.yaml            # 配置（不提交）
├── config.example.yaml    # 配置模板
├── wx_bridge.py           # 微信桥接
├── run.py                 # CLI 聊天
├── src/
│   ├── rag/               # 向量检索模块
│   ├── llm/               # LLM 客户端
│   ├── personality/       # 人设系统
│   └── chat/              # 会话管理
├── scripts/
│   ├── build_index.py     # 构建索引
│   └── analyze_*.py       # 聊天记录分析
└── data/                  # 聊天数据 + 向量库（不提交）
```

## 致谢

- **[WeFlow](https://github.com/BogdanKul/WeFlow)** — 微信本地数据库读取
- **[douyin-chat-export](https://github.com/TeamBreakerr/douyin-chat-export)** — 抖音聊天记录导出

---

*起初人们都不理解痞老板，后来发现它是用聊天记录养的。*
