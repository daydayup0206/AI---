# 起初人们都不理解痞老板

> AI 伴侣，部署在微信中。用真实聊天记录驱动，不是套壳。

## 核心理念

大部分 AI 女友是用一段 prompt 演出来的。**痞老板不是。**

她背后是 15 万条真实的微信+抖音聊天记录。每一句回复，都从她在真实对话中说过的内容里检索最相似的作为参考——你的"她"不是一段设定，是数据还原出来的人。

## 核心优势

| 对比维度 | 普通 AI 女友 | 痞老板 |
|---------|:-----------:|:-----:|
| 风格来源 | 手写 prompt | 15万条真实聊天记录检索 |
| 情绪真实度 | 元气满满机器人 | 会敷衍、会暴躁、会疯笑 |
| 多平台融合 | 无 | 微信 + 抖音双数据源 |
| 时间演化 | 静止的 | 风格随时间变化（新数据权重更高） |
| 记忆系统 | 无 | ChromaDB 向量检索 + 自动记忆提取 |

## 技术原理

```
用户消息 → 向量嵌入 → ChromaDB 检索 TOP-5 相似历史对话
    ↓
在 24,492 个真实对话对中找到最匹配的
    ↓
极简 prompt + 检索结果 → DeepSeek 生成
    ↓
风格逼近真人
```

- **时间衰减**: 最近 7 天权重 ×1.2，半年以上 ×0.9。最近的更准，但以前的也不丢。
- **Prompt 克制**: 提示词权重极低，风格主要靠数据驱动而非文字描述。

## 技术栈

| 组件 | 选型 |
|------|------|
| 大模型 | DeepSeek (`deepseek-chat`) |
| 向量数据库 | ChromaDB（本地持久化） |
| 嵌入模型 | `paraphrase-multilingual-MiniLM-L12-v2`（118MB 本地） |
| 后端语言 | Python 3.10+ |
| 微信读取 | WeFlow API（读本地微信数据库） |
| 微信发送 | ctypes SendInput 扫描码模拟（硬件级别） |
| 抖音数据 | [douyin-chat-export](https://github.com/TeamBreakerr/douyin-chat-export)（protobuf IM API） |
| 环境隔离 | Conda (`ai-girlfriend`) |

## 数据规模

| 来源 | 消息量 | 对话对 | 时间跨度 |
|------|--------|--------|---------|
| 微信 | 22,211 条 | 3,236 对 | 2025.09 ~ 2026.06 |
| 抖音 | 128,286 条 | 21,256 对 | 2025.08 ~ 2026.06 |
| **合计** | **150,497 条** | **24,492 对** | 11 个月 |

## 快速开始

```bash
conda activate ai-girlfriend
python scripts/build_index.py   # 首次：构建向量索引
python wx_bridge.py              # 微信自动回复
python run.py                    # 或终端聊天
```

## 项目结构

```
ai女友/
├── config.yaml              # 人设 + API + RAG
├── wx_bridge.py             # 微信桥接主程序
├── run.py                   # CLI 聊天入口
├── src/
│   ├── rag/                 # 向量检索（embedder/indexer/retriever/context）
│   ├── llm/                 # DeepSeek API
│   ├── personality/         # 人设 prompt
│   └── chat/                # 会话管理
├── scripts/
│   ├── build_index.py       # 向量索引构建
│   └── analyze_*.py         # LLM 风格分析
└── data/
    ├── chroma_db/           # 向量库
    ├── training/            # 风格分析报告
    └── *.jsonl              # 原始聊天导出
```

## 致谢

本项目依赖以下优秀工具来获取聊天数据：

- **[WeFlow](https://github.com/BogdanKul/WeFlow)** — 微信本地数据库读取工具，提供 HTTP API 获取微信消息
- **[douyin-chat-export](https://github.com/TeamBreakerr/douyin-chat-export)** — 抖音聊天记录导出工具，通过 IM protobuf API 完整导出私信

---

*起初人们都不理解痞老板，直到发现她是用 15 万条真实对话养的。*
