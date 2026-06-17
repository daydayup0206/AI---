# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

AI女友——部署在微信中的 AI 伴侣，具备以下核心能力：
- **微信集成**：通过微信收发消息，与用户实时对话
- **自定义人设**：自定义头像、名字、性格
- **风格学习**：读取目标人物的微信/抖音聊天记录，学习其说话方式、语气、用词习惯
- **记忆系统**：存储和回忆起两人之间的共同经历、关键事件、偏好

## 技术决策（已确认）

| 决策项 | 选择 | 备注 |
|--------|------|------|
| LLM 后端 | **DeepSeek** (`deepseek-chat`) | OpenAI 兼容 API |
| 后端语言 | **Python 3.10+** | |
| 环境管理 | **Conda env: `ai-girlfriend`** | 独立环境，不污染 base |
| 微信接入 | 待定 | itchat / wechaty / 企业微信 |
| 记忆存储 | **ChromaDB + sentence-transformers** | ✅ 已实现 RAG 检索 |
| 嵌入模型 | `paraphrase-multilingual-MiniLM-L12-v2` | 本地 118MB |
| 抖音数据 | **暂不做** | 获取难度太高 |

## 当前项目结构

```
ai女友/
├── CLAUDE.md
├── config.yaml              # 人设 + API + RAG 配置
├── config.example.yaml      # 配置模板
├── .gitignore
├── .env.example
├── requirements.txt         # openai, pyyaml, chromadb, sentence-transformers 等
├── run.py                   # 入口：python run.py
├── scripts/
│   └── build_index.py       # 一次性建库：python scripts/build_index.py
├── data/
│   ├── chroma_db/           # ChromaDB 向量库（3236 对话对）
│   ├── memories.json        # 手动记忆
│   ├── training/            # 聊天记录导出 + 已提取数据
│   └── 私聊_宝宝（1231）.json # 微信原始导出（11MB）
└── src/
    ├── config/loader.py     # ConfigLoader: YAML + 环境变量
    ├── llm/client.py        # DeepSeekClient: OpenAI SDK 封装
    ├── personality/persona.py # Persona: 构建 system prompt
    ├── chat/session.py      # ChatSession: 对话历史 + 截断 + RAG 注入
    ├── cli/app.py           # CLI 聊天主循环 + RAG 检索
    └── rag/                 # RAG 检索增强模块
        ├── embedder.py      # Embedder: sentence-transformers 封装
        ├── indexer.py       # DialogueIndexer: 对话配对 → ChromaDB
        ├── retriever.py     # DialogueRetriever: 运行时检索
        └── context.py       # RAGContextBuilder: 检索结果 → prompt
```

## 关键数据流

1. **消息循环**：微信消息 → 意图识别 → 记忆检索（相关历史） → 人设 prompt 拼装 → LLM 生成 → 微信回复
2. **风格学习**：聊天记录导入 → 对话清洗 → 特征提取（语气、用词、表情习惯、回复长度） → 写入人设 prompt
3. **记忆沉淀**：每次对话后 → LLM 摘要关键信息 → 存入向量库 + 结构化存储

## 开发路径建议

分阶段推进，每阶段可独立验证：

| 阶段 | 目标 | 产出 |
|------|------|------|
| 1 | LLM 对话跑通 | ✅ 命令行聊天 demo，人设可配置 |
| 2 | 聊天记录导入 | 支持微信导出 txt 解析，提取对话对 |
| 3 | 风格学习 | 从聊天记录生成风格 prompt |
| 4 | 记忆系统 | 短期记忆 + 长期向量检索 |
| 5 | 微信接入 | 微信消息收发联调 |
| 6 | 管理后台 | Web 配置界面 |

## 常用命令

```bash
# 激活环境（每次新终端都要先执行）
conda activate ai-girlfriend

# 安装依赖（首次）
pip install -r requirements.txt

# 构建向量索引（首次或聊天记录更新后）
python scripts/build_index.py

# 运行 CLI 聊天
python run.py

# 指定配置文件
python run.py config.yaml

# 设置 API Key（二选一）
set DEEPSEEK_API_KEY=sk-your-key    # Windows 环境变量
# 或直接在 config.yaml 中填写 api_key 字段
```

## 数据流（更新后）

```
用户消息 → Embedding → ChromaDB 检索(top-5 相似历史对话)
                ↓
        找到她在类似情境下的真实回复
                ↓
        注入 prompt 作为风格参考（第二条 system message）
                ↓
        LLM 生成 → 风格更接近真人
```

## 技术注意事项

- **微信风控**：非官方 API 有封号风险，建议用小号测试；消息频率需加随机延迟
- **聊天记录隐私**：导入的聊天记录包含他人隐私，本地存储需加密，不要上传到第三方服务
- **内容合规**：微信对 AI 自动回复有检测机制，避免高频、重复、敏感内容
- **抖音数据获取**：抖音私信无公开 API，可能需要从手机导出或截图 OCR，数据获取难度较高
