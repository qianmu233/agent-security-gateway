# README 正式版修订依据

审查日期：2026-10-21。修改前基线 `2044de2`。本清单在 README 修改前建立。

| 原句或小节 | 问题类别 | 可核查依据 | 修改方案 |
|---|---|---|---|
| “企业级 Agent 工具调用安全网关” | 能力夸大 | `ErpStore`、`WriteIntentService` 都是单 JVM 内存状态 | 定位为工具执行授权的工程原型 |
| 两处本机 JDK/Maven 缓存绝对路径 | 不可移植 | `scripts/acceptance.ps1` 的可选参数 | 使用已配置 JAVA_HOME；缓存说明留给工程文档 |
| “20 项 JUnit、24 场景…全部通过” | 测试计数及真实 LLM 边界不突出 | 三份 Failsafe XML：11+8+1；`docs/evaluation/report.md`：8 合法、16 非法 | 分开说明 JUnit、场景和独立 JAR；16/16 仅确定性 Mock + MCP HTTP |
| 版本与部署范围 | 阶段状态 | `PolicyService`、`ToolGateway`、`WriteIntentService` | 说明单 JVM 的实际执行范围 |
| 项目增量与上游能力 | 来源归属 | `NOTICE`、`docs/upstream-vs-custom.md` | 明示 API Key 认证/BCrypt/凭据仓库及 MCP 协议来自上游；增量是执行策略与实验 |

示例身份 `reader-a` / `buyer-a` / `buyer-b`、租户和 ERP 资源均为固定演示数据。源码无默认可用 API Key；三份秘密需外部提供。审计不保存 Key、intentId 或原始工具参数；测试字符串不能用于真实部署。
