# P3 Phase 1–3 学习与面试复盘

## 源码阅读顺序

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

正常用户任务是“只查库存”。攻击者控制 ERP 备注，让 Agent 忽略任务并改单、访问其他租户或调用伪造的授权工具。Mock Agent 主动模拟服从备注；测试要求 induced=true，确保危险调用实际被提出。

noteTrust 只是信任标签，不能授予权限。防线是认证主体、业务策略与独立可信写意图。提示模型“忽略备注指令”不能替代执行前授权。

长期 BUYER 权限不足以表示本次批准。TrustedIntentConsole 展示 caller/order/quantity 后要求本地可信操作员 CONFIRM；它信任 OS stdin 通道，不代表已验证真实终端用户同意。Agent 网络客户端没有该通道或 issueForConfirmedUser 的入口，MCP 工具列表仍只有两个。

授权用标准 SecureRandom 生成 32 字节不透明 ID，绑定可信主体、固定工具、真实租户、订单与数量。API Key 认证继续由上游完成。WriteIntentService.execute 再检查策略、有效期和匹配关系，随后一次性消费；匹配失败不消费授权。内部执行失败时已消费授权不恢复，避免不受控重试。

当前写操作共享进程内锁，并发 HTTP 重放测试证明同一授权最多改变一次订单。它不能代替数据库事务、唯一约束和分布式幂等。过期条目清理后旧 ID 返回 INVALID 而不是 EXPIRED，均不能执行。

本地操作员确认是受信前提，尚无独立用户账户或确认 UI。若 Agent 获得服务器 OS 控制权，本项目不能保护该信任域。若备注提出的操作与已经获批的全部绑定字段完全相同，它仍属于允许范围；本阶段不判断模型为何提出调用或真实模型攻击概率。

## 面试问题与回答要点

| 问题 | 回答要点 |
| --- | --- |
| Agent 输出越权工具调用怎么办？ | 不把 Agent 当授权主体；MCP 入口认证，真实工具路径再做服务端策略判定，生成正确 JSON 也不能绕过权限 |
| 认证成功为何仍可能拒绝？ | 认证确定谁在调用，授权检查能否对该租户的该资源执行该工具 |
| 为什么不能信任 tenantId/role？ | 客户端可任意伪造；身份来自认证实体，资源归属来自服务端数据，额外身份字段拒绝 |
| 为什么还要资源范围？ | 同租户用户也可能只能访问分配的商品/订单；测试验证 sku-a2/po-a2 被拒 |
| @PreAuthorize 为什么可能失效？ | 未启用方法安全、自调用、绕开代理、异步丢失 SecurityContext；本项目启用代理并以实际 HTTP 验证 |
| MCP tools/list 能否看到不可调用工具？ | 本阶段认证用户可见两工具；工具发现不是执行授权，调用仍逐次检查 |
| JSON Schema 是否足够防止非法参数？ | Schema 是接口描述；执行端严格字段/类型检查与 Bean Validation 才是可信边界 |
| 如何证明拒绝没有副作用？ | 每个拒绝请求通过真实 HTTP 发出，前后比较全部订单 snapshot；成功写另外验证数量与版本变化 |
| 如何避免审计泄漏？ | 固定字段、可信 caller/工具名、固定原因码、UUID；不存原始参数/密钥/异常消息，并注入运行时密钥做反射测试 |
| 有写权限为什么还需 intent？ | 权限是长期资格，intent 在本项目中表示本地可信操作员批准本次精确修改；不等于真实终端用户同意验证 |
| Agent 能否生成授权？ | 没有签发工具；猜测 ID、复制他人 ID、改数量或重放都被检查 |
| UNTRUSTED_DATA 是否阻止注入？ | 只是标记；攻击模拟仍服从备注，服务端负责阻断执行 |
| 是否测出模型攻击成功率？ | 没有；确定性 planner 被设定为提出危险调用，测试证明执行阻断条件 |
| 如何计算阻断率？ | 16 个非法主请求中，实际 MCP 拒绝、业务调用次数为零且全量订单不变的数量除以 16；不把预期结果当观测 |
| 如何区分进入工具和业务执行？ | 测试侧分别观察 gateway handler、权限后的写服务和真正 ErpStore.update；进入意图检查并不表示已执行写入 |
| 是否存在授权检查到写入的窗口？ | 校验、消费和更新持有同一锁；测试暂停实际写入，第二 HTTP 请求进入受保护服务后仍等待，最终一次修改、一次重放拒绝 |
| p50/p95 如何计算？ | 24 个主请求的完整 HTTP 往返时间，排序后最近秩分位数；排除准备读、批准、预热和并发辅助；不是吞吐基准 |
| RBAC 是怎样实现的？ | 服务端固定角色配置 permission，实际谓词检查 permission、tenant 与 resource；role 标签本身不来自模型，也没有动态通用角色引擎 |
| 你个人实现了哪些？ | ERP 模拟工具、可信身份目录、租户与资源授权、严格参数、脱敏审计和 HTTP 安全验收；认证库/MCP 协议是上游 |
| 进入生产还缺什么？ | 密钥生命周期、限流、持久化审计、监控、写操作幂等/并发控制、依赖升级验证 |

## 简历表述参考

基于 Spring AI MCP 和 MCP Security 构建 Agent 工具安全网关，新增权限/租户/资源授权与短期单次可信写意图；使用 20 项真实 HTTP JUnit 测试及其中的 24 场景评测，验证本地样本中 8/8 合法请求通过、16/16 非法执行被阻断，并以实际执行观测和全量订单状态核对拒绝无业务副作用。详见 [简历亮点](resume-highlights.md)。

## 两个不变量的源码核查结论

正式代码唯一 `store.update` 调用点是 ErpService 的 intent 执行回调，先经方法安全策略，再由 WriteIntentService 校验授权。签发只由本地确认代码调用 package-private 方法，无 MCP/REST 签发入口。固定主体目录与不可变租户归属限制了当前作用域。

WriteIntentService.execute 在同步方法中完成匹配、过期、已消费检查、消费及 mutation.get()，没有释放锁后的写入。B02 用测试侧 spy 暂停真正更新，第二请求已经进入权限后的服务但不能越过这段临界区；恢复后只有一个实际 update。测试没有替换权限/意图判断或提供成功假响应，业务仍由真实方法执行。本轮未发现导致越权副作用的缺陷，未更改正式安全框架。

当前身份资源范围互不重叠，因此主体/租户/目标绑定部分以组合拒绝路径和源码检查验证，没有声称隔离证明共享订单多主体场景。并发样本仅两个请求，不能替代分布式压力测试。API Key、nonce、参数和备注不进入报告；状态用运行内加盐指纹比较，盐不输出。

不要表述为自研 MCP 协议、安全认证库、通用 Prompt Injection 检测器或已经生产上线的企业平台。
