# staging 构建 SQL 提醒

Jenkins 在 staging 构建成功后 POST `/webhook/jenkins/staging`：

```json
{
  "job_name": "staging-interlace-assets",
  "build_number": 123,
  "build_url": "https://jenkins.example.com/job/staging-interlace-assets/123/",
  "phase": "COMPLETED"
}
```

`job_name` 支持 `codebase_configs.json` 中的 alias 或唯一的 jenkins_job_name。
`build_number` 必须为正整数。phase 可以省略；提供时仅处理 COMPLETED、FINALIZED、SUCCESS。
接口返回 HTTP 202 表示已加入后台分析，不能据此判断分析或通知成功。
后台会再向 Jenkins 验证该构建已经结束且结果为 SUCCESS。
请只将 staging Job 的成功构建回调配置到此接口。

## 分析和通知

- 使用该构建的 changeSet/changeSets 中的精确 commit ID，支持普通 Job 和 Pipeline。
  不使用最新构建或 HEAD 代替，不会遗漏单提交构建或列表中的首个提交。
- 从配置的本地仓库读取真实 diff 和 Git 作者。对象缺失时执行 git fetch origin，
  不切换分支或覆盖工作区；根提交可分析，merge commit 与第一父提交比较。
  多 SCM 的提交必须都能在配置仓库中解析，否则本次分析失败并记录日志。
- 使用现有 DASHSCOPE_API_KEY / DASHSCOPE_API_HOST 和 qwen-max 做结构化分析。
  模型同时检查整个构建中的 SQL、Flyway/Liquibase 迁移，已明确覆盖的修改不提醒。
  仅对高置信度的数据库结构变化提醒；DTO、Transient 字段、方法、注释等不应命中。
  模型判断仍可能误判，需要提交人最终核对。
- 用 Git 作者邮箱匹配 feishu_mapping.json，沿用现有部门昵称查询作为后备。
  建议配置精确邮箱映射，避免重名。不会使用模型生成的姓名或邮箱决定收件人。
- 按 open_id 合并私聊，内容以“检查是否提交sql”开头，包含构建链接、commit、文件和依据。
  不向 NOTIFY_CHAT_ID 发群通知，不依赖告警卡片模板。
  本功能不生成或执行 DDL，也不能确定仓库外单独提交的 SQL 是否存在。

## 运行边界

缺少 changeSet 数据、Git 读取失败、diff 超过 100,000 字符、模型返回非法结果，
都会记录失败日志并停止提醒，不会用截断数据推断无需 SQL。空 changeSet 表示无新提交。
身份映射或发送失败同样记录日志，后续收到同一回调可以重试。

去重保留当前单进程内最近 1,000 个构建，已成功接收的用户不会因同一构建重试再次收到提醒。
进程重启、多 worker 或网络超时造成的“发送成功但响应丢失”不能保证去重。
后台任务不是持久队列，也不会自动重试；部署重启可能丢失已接受的任务。
分析结果和通知状态目前通过应用日志查看；需要跨实例可靠交付时应接持久队列与去重存储。

此接口沿用现有 webhook 的网络访问方式，应由内部 Jenkins 调用。

## 本地验证

```sh
CODEBASE_CONFIGS_PATH=codebase_configs.example.json DASHSCOPE_API_KEY=test \
  .venv/bin/python -m unittest tests.test_staging_ddl -v
```

测试使用临时 Git 仓库及模拟 Jenkins、模型、飞书接口，不发送真实消息。
