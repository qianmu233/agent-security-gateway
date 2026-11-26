# MCP 授权流程与安全设计

## Java 网关源码

| 文件（src/main/java/dev/p3/gateway 下） | 作用 |
| --- | --- |
| GatewayApplication.java | 启动应用；排除默认密码用户配置 |
| security/SecurityConfiguration.java | 环境变量密钥、上游 API Key 仓库与过滤器、HTTP 安全链 |
| security/IdentityDirectory.java | 从认证主体的服务端 key ID 映射角色、租户、权限和资源范围 |
| security/PolicyService.java | 默认拒绝的 permission + tenant + resource 联合判断 |
| security/WriteIntentService.java | 60 秒精确绑定授权、单次消费与同步执行 |
| security/TrustedIntentConsole.java | 本地可信操作员与二次确认；无网络签发接口 |
| security/IntentConfiguration.java | 服务端 Clock；测试通过时钟推进验证过期 |
| mcp/ToolConfiguration.java | 仅注册两个 SDK SyncToolSpecification 及输入 Schema |
| mcp/McpBoundaryFilter.java | 认证后的请求预检；拒绝未知工具并避免回显恶意名称 |
| mcp/ToolGateway.java | 严格字段/类型检查、Bean Validation、调用代理服务、错误脱敏与审计 |
| erp/ErpService.java | @PreAuthorize 在真实 MCP 执行链中阻止越权读写 |
| erp/ErpStore.java | 不可变资源归属、内存模拟库存与采购单、原子数量更新和版本递增 |
| audit/AuditTrail.java | 有界内存审计，固定字段与原因码 |
| audit/AuthenticationAuditFilter.java | 观察真实认证 401，记录 AUTHENTICATION_FAILED |

测试入口：`McpSecurityIT.java` 保留 Phase 1 的 11 项；`AgentInjectionIT.java` 保留 Phase 2 的 8 项；`SecurityEvaluationIT.java` 一个表驱动入口执行 24 个评测场景；JUnit 共 20 项。`support/MockAgent.java` 只通过 HTTP 提出调用，`support/TrustedUser.java` 模拟独立操作员；`support/EvaluationReport.java` 根据真实观察生成 JSON/CSV/Markdown。一键入口 `scripts/acceptance.ps1`。依赖版本未改变，应用版本为 0.2.0。

## 一次工具调用如何被保护

1. Agent/客户端提交带 X-API-Key 的 `/mcp` HTTP POST。
2. SecurityFilterChain 调用上游 API Key filter/provider。凭据格式先做边界检查，上游从仓库取复制实体并使用 PasswordEncoder 验证 BCrypt 哈希，成功后建立 Authentication。
3. `/mcp` 要求认证，其余 HTTP 路径默认拒绝。采用 STATELESS，每次请求独立认证；没有通过 Cookie 登录。
4. 认证后的 McpBoundaryFilter 只做请求尺寸限制与未知工具预检。MCP initialize、工具发现、正常 dispatch、协议响应由现有 SDK 实现。
5. SDK SyncToolSpecification 的 handler 进入 ToolGateway。调用者从 SecurityContextHolder 的已认证 ApiKeyEntity ID 解析，不读客户端 role/tenantId。
6. 严格检查 fields 和 Java 值类型，Bean Validation 检查 ID/数量。JSON Schema 帮助客户端理解接口，服务端验证负责执行安全边界。
7. 从内存资源查到真实 tenant 和 ID，调用另一个 Bean 的 ErpService。Spring 方法安全代理执行 @PreAuthorize，PolicyService 检查注册工具、权限、租户与资源范围。
8. 读取返回带 UNTRUSTED_DATA 标签的备注。写操作由 WriteIntentService 检查 intentId 的用户、工具、租户、订单、数量、过期与消费状态；校验、消费和内存修改在同一锁内完成。拒绝不改变订单；成功更新数量和 version 并记录审计 UUID。

当前 STATELESS + SYNC WebMVC 路径允许在工具 handler 中读取 Servlet 线程上的 SecurityContext。HTTP 集成测试证明了该版本组合下的身份传递。更换异步执行、线程池或协议时必须重新验证上下文传递；不能仅根据注解存在就假定安全。

## 技术选择与限制

- API Key 用于最小本地演示。认证机制依赖上游，不自行编写 token 协议或 BCrypt；属性不足时通过独立服务端目录扩展授权。
- 明确 permission 决定工具能力，tenant 决定租户边界，resources 决定租户内资源范围。单看 role 或 tenant 都不够。
- PolicyService 使用简单不可变映射和默认拒绝逻辑；不引入通用规则引擎。
- 数量使用整数并拒绝隐式转换，避免 `"25"`、`2.5`、布尔值被悄悄转换为合法写参数。额外字段一律拒绝，包括 Agent 的 role/tenantId。
- 方法安全放在独立 Bean 上，保证 MCP handler 经过 Spring 代理，避免同类 self-invocation 绕开 @PreAuthorize。
- MCP 认证失败是 HTTP 401，业务工具错误是 HTTP 200 + isError=true；验收同时检查传输状态和协议业务结果。
- `/mcp` 是每次凭据头认证的 API，CSRF 只对该路径豁免；未禁用认证或开放所有 URL。其他路径默认拒绝，应用绑定 loopback。
- 日志不记录异常消息、请求头、参数或备注；SDK 异常日志关闭。审计覆盖工具结果、未知工具、真实 MCP 认证 401 和可信签发事件，分别使用 AUTHENTICATION_FAILED、FORBIDDEN、INTENT_* 等固定原因码。
- unknown、missing resource、跨租户等不回显敏感内容。资源不存在和资源无权访问统一 FORBIDDEN。
- resource tenant 不可修改，更新通过 ConcurrentHashMap.computeIfPresent 原子递增 version；当前是 last-write-wins，没有乐观锁前置条件、幂等 key 或审批流。
- 审计保留最近 200 条，业务、授权与审计重启即丢失；授权最多 200 条，签发时清理过期条目。BCrypt 每次验证有成本，尚未实现限流和密钥轮换。项目用于本地安全工程演示。

## 间接注入与可信写授权

间接提示注入测试将不可信备注作为工具数据交给确定性 Mock Agent。测试断言产生了不符合授权约束的实际工具请求，再核对 Java 的拒绝及订单快照。

noteTrust 只是信任标签，不能授予权限。防线是认证主体、业务策略与独立可信写意图。提示模型“忽略备注指令”不能替代执行前授权。

长期 BUYER 权限不足以表示本次批准。TrustedIntentConsole 展示 caller/order/quantity 后要求本地可信操作员 CONFIRM；它信任 OS stdin 通道，不代表已验证真实终端用户同意。Agent 网络客户端没有该通道或 issueForConfirmedUser 的入口，MCP 工具列表仍只有两个。

授权用标准 SecureRandom 生成 32 字节不透明 ID，绑定可信主体、固定工具、真实租户、订单与数量。API Key 认证继续由上游完成。WriteIntentService.execute 再检查策略、有效期和匹配关系，随后一次性消费；匹配失败不消费授权。内部执行失败时已消费授权不恢复，避免不受控重试。

当前写操作共享进程内锁，并发 HTTP 重放测试证明同一授权最多改变一次订单。它不能代替数据库事务、唯一约束和分布式幂等。过期条目清理后旧 ID 返回 INVALID 而不是 EXPIRED，均不能执行。

本地操作员确认是受信前提，尚无独立用户账户或确认 UI。若 Agent 获得服务器 OS 控制权，本项目不能保护该信任域。若备注提出的操作与已经获批的全部绑定字段完全相同，它仍属于允许范围；本阶段不判断模型为何提出调用或真实模型攻击概率。

## Python Agent 与执行边界

Python Agent 使用 LangGraph 的 `decide`、`tool` 和 `finish` 节点处理模型响应、SDK 调用和结果发布。聊天模型使用 `inventory_read` 等函数名，客户端映射到 MCP 工具名，进行严格的参数检查。Java 按已认证身份及实际资源独立授权。已认证用户可发现两个演示工具，执行时仍逐次校验。

MCP 工具拒绝可通过 HTTP 200 传递，由 `isError` 和业务原因码表示结果。响应的 `requestId` 可关联 Java 审计。库存备注作为不可信的工具结果传递，最终成功输出依据工具收据生成。写授权值由可信客户端绑定，保留在模型消息和工具 Schema 之外。

默认每轮最多 5 次模型、3 次工具尝试，图执行时间 30 秒，单步超时 10 秒。预算在请求前占用。超时后客户端停止等待，已派发的远端业务执行仍需通过审计和业务状态核对。

## 验收与统计范围

20 项 Java HTTP 集成测试包含一个 24 场景的本地评测入口。8 个合法场景全部通过，16 个非法主请求均被拒，且均未产生业务副作用。拒绝判定结合工具返回、业务执行观测及订单状态。并发辅助请求单独记录，24 个主请求的 p50 与 p95 按完整 HTTP 往返时间采用最近秩计算。真实模型及跨语言结果另见实测报告。[本地评测及口径](evaluation/report.md) · [跨语言验收](python-agent-verification.md) · [真实模型审计](FINAL_REAL_LLM_DBC_AUDIT.md)

## 两个不变量的源码核查结论

正式代码唯一 `store.update` 调用点是 ErpService 的 intent 执行回调，先经方法安全策略，再由 WriteIntentService 校验授权。签发只由本地确认代码调用 package-private 方法，无 MCP/REST 签发入口。固定主体目录与不可变租户归属限制了当前作用域。

WriteIntentService.execute 在同步方法中完成匹配、过期、已消费检查、消费及 mutation.get()，没有释放锁后的写入。B02 用测试侧 spy 暂停真正更新，第二请求已经进入权限后的服务但不能越过这段临界区；恢复后只有一个实际 update。测试没有替换权限/意图判断或提供成功假响应，业务仍由真实方法执行。本轮未发现导致越权副作用的缺陷，未更改正式安全框架。

当前身份资源范围互不重叠，因此主体/租户/目标绑定部分以组合拒绝路径和源码检查验证，没有声称隔离证明共享订单多主体场景。并发样本仅两个请求，不能替代分布式压力测试。API Key、nonce、参数和备注不进入报告；状态用运行内加盐指纹比较，盐不输出。

MCP 协议、API Key 认证基础及 SDK 来源见[上游组件与项目实现](upstream-vs-custom.md)。
