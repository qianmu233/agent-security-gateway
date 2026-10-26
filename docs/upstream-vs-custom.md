# 上游已有能力与个人新增工作

> **2026-10-26结项索引：** 原来源、许可证和贡献归属保持不变，以下“真实D未执行”等描述是对应阶段历史。后续新增批量驱动及离线审计故障回归，并完成用户执行的真实D/B/C：D危险写入授权分支NOT_EXERCISED，B/C服务端拒绝PASS，不能算通用抗注入率。最终原件、统计、证据局限和项目增量见[最终D/B/C审计](FINAL_REAL_LLM_DBC_AUDIT.md)。本轮只归档文档，既有Java策略和开源组件不冒充新增实现。

## 2026-10-23 Python跨语言增量

下表原Java来源归属保留。本轮新增python-agent/，并非重写认证或MCP协议：官方modelcontextprotocol/python-sdk提供Streamable HTTP、初始化与会话；LangGraph提供StateGraph执行；LangChain提供消息及原生Tool Calling适配。依赖许可证各自适用，项目保留Apache-2.0和原NOTICE，不分发依赖源码或模型权重。

本轮P3增量为decide/tool/finish有界图、模型工具别名与严格契约、受控身份/私有精确授权绑定、isError与超时错误转换、收据约束输出、仅测试Java可信stdin夹具、13项真实跨进程集成和一键验收。Java生产安全代码及原测试没有修改，原Java业务策略/写意图不算本轮新增。采用AI辅助开发，不声称上游框架或全部代码均个人手写。

原跨语言阶段Python34项与原Java20项/24场景通过；后续最小修复将Python基线补齐为51项，另完成一次真实DeepSeek合法库存A。真实攻击D未执行，不能把Fake驱动的危险调用阻断统计包装为真实模型抗注入率。版本、命令、历史失败及个人增量详见[专项报告](python-agent-verification.md)，单次真实结果与证据限制见[A终审](FINAL_REAL_LLM_A_AUDIT.md)。以下“唯一GitHub参考”指原Java主参考项目，Python框架/SDK是明确列出的依赖来源，不是本项目原创。

## 原Java来源与阶段记录

唯一 GitHub 参考：[spring-ai-community/mcp-security](https://github.com/spring-ai-community/mcp-security/tree/25b9ef1ba9d22bedb1100c85056baee6e9ce0a18)。固定 `v0.0.6` / `25b9ef1ba9d22bedb1100c85056baee6e9ce0a18`，Apache-2.0。

重点阅读 `samples/sample-mcp-server-api-key`，并参考同仓库 `sample-mcp-server-secured-tools` 的方法授权示例。没有引入其他 GitHub 主项目。

| 能力 | 来源及 P3 使用方式 | 是否个人新增 |
| --- | --- | --- |
| MCP 协议、initialize、tools/list、tools/call 与 HTTP transport | Spring AI / MCP Java SDK | 否 |
| McpApiKeyConfigurer、ApiKeyAuthenticationFilter/Converter/Provider | MCP Security 0.0.6 发布依赖 | 否 |
| API Key 格式解析、BCrypt 哈希与验证 | 上游组件和 Spring Security PasswordEncoder | 否 |
| InMemoryApiKeyEntityRepository、ApiKeyEntityImpl builder | MCP Security 0.0.6 | 否 |
| SecurityFilterChain 配置方式 | 借鉴 API Key sample，P3 配置有修改 | 配置扩展 |
| @PreAuthorize 与 EnableMethodSecurity 机制 | Spring Security；同仓库 secured-tools 已演示 | 否，P3 新增具体策略表达式 |
| 三个身份及服务端 role/tenant/permission/resource 目录 | P3 IdentityDirectory | 是 |
| inventory.read、purchase_order.update | P3 的虚拟 ERP 数据和工具注册 | 是 |
| 默认拒绝、租户与资源联合 PolicyService | P3 自定义最小业务策略 | 是 |
| 严格 fields/types、Bean Validation、禁止身份参数伪造 | P3 工具执行边界 | 是，验证框架是已有依赖 |
| 上游点分段容错的格式加固 | P3 验证单个点、ID/secret 长度字符、重复凭据头；委托上游 converter | 是，非重新实现 API Key 密码学 |
| 未注册工具预检、避免恶意名称回显 | P3 McpBoundaryFilter；协议与正常 dispatch 仍由 SDK 完成 | 是，薄边界过滤器 |
| 受控模拟写、version 原子递增、拒绝无副作用 | P3 ErpStore/ErpService | 是 |
| 原因码、请求 UUID、有界脱敏审计 | P3 AuditTrail/ToolGateway | 是 |
| 20 项真实 HTTP JUnit 及独立 JAR 演示 | 保留 Phase 1/2 的 19 项，新增一个 24 场景评测入口 | 是 |
| 不可信库存备注与标签 | P3 ERP 模拟字段；标签不作为授权属性 | 是，Phase 2 |
| 确定性 Mock Agent 间接注入驱动 | 仅测试代码，读取和后续调用均走真实 MCP HTTP | 是，Phase 2；不是模型攻击成功率 |
| 可信写意图 | 本地控制台确认、60 秒随机授权、身份/工具/租户/资源/数量绑定、单次消费 | 是，Phase 2 |
| 意图校验与原子模拟写 | P3 WriteIntentService / ErpService | 是，Phase 2；非分布式事务 |
| 认证、权限、意图失败区分 | P3 AuthenticationAuditFilter 与 INTENT_* 原因码 | 是，Phase 2 |
| 24 场景和实测安全指标 | P3 表驱动数据、实际 MCP 响应及业务执行/状态观测 | 是，Phase 3 |
| JSON/CSV/Markdown 脱敏报告 | P3 EvaluationReport；指标根据真实行数据计算 | 是，Phase 3 |
| 并发写窗口验收 | 测试侧暂停更新，以两个真实 HTTP 请求验证单次消费临界区 | 是，Phase 3；不是分布式压力测试 |
| 一键完整验收与简历文档 | P3 acceptance.ps1、验收与来源说明 | 是，Phase 3 |
| OAuth2 授权服务器、客户端安全、天气工具等 | 上游仓库其他功能 | 未作为个人成果；未引入 P3 |

P3 不复制上游安全库源码，仅通过 Maven 依赖复用。`SecurityConfiguration.java` 参考上游 API Key 示例的配置模式，保留上游版权与 Apache-2.0 头。个人修改包括环境凭据、失败即阻止启动、固定身份、无状态认证、只保护 MCP API、严格凭据头和脱敏预检，详见根目录 NOTICE 和 LICENSE。

上游演示凭据仅存在于参考仓库隔离运行中，没有进入 P3 的配置、测试或文档。P3 测试凭据由脚本随机生成后仅通过环境继承。

个人工程价值在于把现有认证组件接入真实 MCP 请求链，在虚拟 ERP 业务执行前实现最小可信授权，并提供可以复现的安全证据。不存在“自研 MCP 协议/API Key 算法/完整安全框架”的成果声明。

Phase 2 扩展原项目，没有新增主参考或独立项目。意图签发不是 MCP 工具，也没有 REST 审批接口。正常业务通过相同 ToolGateway / PolicyService / ErpService 执行；正式 JAR 不包含 Mock Agent 或测试授权助手，也没有无安全控制的执行器或绕过开关。

Phase 3 仅增加测试组织、观测、报告与交付文档，未新增正式业务模块或重写安全组件。Mockito spy、延迟计时和场景载荷只在测试中，保留真实业务方法与策略；报告不输出 API Key、有效意图或敏感原始参数。指标是本地确定性样本结果，不能包装为真实第三方 LLM 安全表现。本地控制台仅代表可信操作员确认。
