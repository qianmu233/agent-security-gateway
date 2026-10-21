# README 正式版修订依据

审查日期：2026-10-21。修改前基线 `2044de2`。本清单在 README 修改前建立。

| 原句或小节 | 问题类别 | 可核查依据 | 修改方案 |
|---|---|---|---|
| “企业级 Agent 工具调用安全网关” | 能力夸大 | `ErpStore`、`WriteIntentService` 都是单 JVM 内存状态 | 定位为工具执行授权的工程原型 |
| “P3 简历 MVP · Phase 1–3 完成” | 招聘材料和开发阶段混入产品标题 | `pom.xml`、MCP 注册配置 | 项目名、一句话定位与真实架构开篇 |
| 两处本机 JDK/Maven 缓存绝对路径 | 不可移植 | `scripts/acceptance.ps1` 的可选参数 | 使用已配置 JAVA_HOME；缓存说明留给工程文档 |
| “20 项 JUnit、24 场景…全部通过” | 测试计数及真实 LLM 边界不突出 | 三份 Failsafe XML：11+8+1；`docs/evaluation/report.md`：8 合法、16 非法 | 分开说明 JUnit、场景和独立 JAR；16/16 仅确定性 Mock + MCP HTTP |
| “本阶段验证”“完成后停止，等待最终审核” | 开发时间线 | `PolicyService`、`ToolGateway`、`WriteIntentService` | 改成长期有效的限制说明 |
| “个人新增内容”可能泛化为全部实现 | 来源归属 | `NOTICE`、`docs/upstream-vs-custom.md` | 明示 API Key 认证/BCrypt/凭据仓库及 MCP 协议来自上游；增量是执行策略与实验 |

示例身份 `reader-a` / `buyer-a` / `buyer-b`、租户和 ERP 资源均为固定演示数据。源码无默认可用 API Key；三份秘密需外部提供。审计不保存 Key、intentId 或原始工具参数；测试字符串不能用于真实部署。
