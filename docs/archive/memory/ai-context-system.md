---
name: ai-context-system
description: AI Context 三级知识体系（Operating Manual → Scene Context → Knowledge）
metadata:
  type: project
---

# AI Context 知识体系

建立了 `ai-context/` 目录，用于存放给 AI 阅读的"模型启动包"，解决"每次新对话都要重新介绍自己"的问题。

## 体系结构

```
ai-context/
├── README.md                    ← 总索引
├── persona/profile.md           ← Operating Manual：你是谁、怎么协作
├── scenes/interview.md          ← 面试场景启动包（上传即进入面试官模式）
├── scenes/eia-development.md    ← EIA 开发场景（待提炼）
├── scenes/ai-learning.md        ← AI 学习场景（待提炼）
└── kits/                        ← 子场景加速包（待提炼）
```

## 设计原则

- Context 不是独立于 Knowledge 的另一套文件，而是 Knowledge 的精炼视图
- 分层：Operating Manual（你是谁）→ Scene Context（当前场景）→ Kit（子场景加速包）
- 不同 AI 工具应有不同 Context 优化方向（Claude Code 看 `CLAUDE.md`，ChatGPT 看 `ai-context/`）
- V1 先做面试场景，V2 扩展到 EIA 开发，V3 铺满完整体系

**当前状态**：V1 完成（Operating Manual + Interview Context）
**下一步**：如果面试进入实战阶段，可以加 `kits/boka-story.md` 和 `kits/eia-tech-deep.md`

参见：[[feature-flags-v4]]
