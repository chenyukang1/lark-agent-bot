# Lark Agent Bot

## 简介

这是一个基于飞书（Lark）OpenAPI 的机器人项目，集成了本地 Agent/LLM 诊断能力。它能够：

- 监听飞书消息事件
- 向用户发送“分析中”卡片
- 异步调用本地 Agent 进行故障诊断
- 将分析结果更新回飞书卡片

该项目使用 `lark-oapi` 作为飞书 SDK，并通过 `langchain` / `langchain-openai` 调用本地分析 Agent。

## 效果展示

![jenkins构建失败](docs/jenkins-lark.jpeg)

## 许可

- Apache 2.0
