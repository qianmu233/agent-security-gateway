# Phase 1 学习与面试复盘

## 源码阅读顺序

| 文件（src/main/java/dev/p3/gateway 下） | 作用 |
| --- | --- |
| GatewayApplication.java | 启动应用；排除默认密码用户配置 |
| security/SecurityConfiguration.java | 环境变量密钥、上游 API Key 仓库与过滤器、HTTP 安全链 |
| security/IdentityDirectory.java | 从认证主体的服务端 key ID 映射角色、租户、权限和资源范围 |
| security/PolicyService.java | 默认拒绝的 permission + tenant + resource 联合判断 |
| mcp/ToolConfiguration.java | 仅注册两个 SDK SyncToolSpecification 及输入 Schema |
| mcp/McpBoundaryFilter.java | 认证后的请求预检；拒绝未知工具并避免回显恶意名称 |
| mcp/ToolGateway.java | 严格字段/类型检查、Bean Validation、调用代理服务、错误脱敏与审计 |
| erp/ErpService.java | @PreAuthorize 在真实 MCP 执行链中阻止越权读写 |
| erp/ErpStore.java | 不可变资源归属、内存模拟库存与采购单、原子数量更新和版本递增 |
| audit/AuditTrail.java | 有界内存审计，固定字段与原因码 |

测试入口：`src/test/java/dev/p3/gateway/McpSecurityIT.java`。复现入口：`scripts/verify.ps1`、`scripts/demo.ps1`。参数、版本和启动配置：`pom.xml`、`src/main/resources/application.properties`。

## 一次工具调用如何被保护

1. Agent/客户端提交带 X-API-Key 的 `/mcp` HTTP POST。
2. SecurityFilterChain 调用上游 API Key filter/provider。凭据格式先做边界检查，上游从仓库取复制实体并使用 PasswordEncoder 验证 BCrypt 哈希，成功后建立 Authentication。
3. `/mcp` 要求认证，其余 HTTP 路径默认拒绝。采用 STATELESS，每次请求独立认证；没有通过 Cookie 登录。
4. 认证后的 McpBoundaryFilter 只做请求尺寸限制与未知工具预检。MCP initialize、工具发现、正常 dispatch、协议响应由现有 SDK 实现。
5. SDK SyncToolSpecification 的 handler 进入 ToolGateway。调用者从 SecurityContextHolder 的已认证 ApiKeyEntity ID 解析，不读客户端 role/tenantId。
6. 严格检查 fields 和 Java 值类型，Bean Validation 检查 ID/数量。JSON Schema 帮助客户端理解接口，服务端验证负责执行安全边界。
7. 从内存资源查到真实 tenant 和 ID，调用另一个 Bean 的 ErpService。Spring 方法安全代理执行 @PreAuthorize，PolicyService 检查注册工具、权限、租户与资源范围。
8. 只有授权成功才进入采购单更新方法。失败转为固定 FORBIDDEN，订单保持不变；成功更新数量、version，返回结果并记录审计 UUID。

当前 STATELESS + SYNC WebMVC 路径允许在工具 handler 中读取 Servlet 线程上的 SecurityContext。HTTP 集成测试证明了该版本组合下的身份传递。更换异步执行、线程池或协议时必须重新验证上下文传递；不能仅根据注解存在就假定安全。

## 技术选择与限制

- API Key 用于最小本地演示。认证机制依赖上游，不自行编写 token 协议或 BCrypt；属性不足时通过独立服务端目录扩展授权。
- 明确 permission 决定工具能力，tenant 决定租户边界，resources 决定租户内资源范围。单看 role 或 tenant 都不够。
- PolicyService 使用简单不可变映射和默认拒绝逻辑；不引入通用规则引擎。
- 数量使用整数并拒绝隐式转换，避免 `"25"`、`2.5`、布尔值被悄悄转换为合法写参数。额外字段一律拒绝，包括 Agent 的 role/tenantId。
- 方法安全放在独立 Bean 上，保证 MCP handler 经过 Spring 代理，避免同类 self-invocation 绕开 @PreAuthorize。
- MCP 认证失败是 HTTP 401，业务工具错误是 HTTP 200 + isError=true；验收同时检查传输状态和协议业务结果。
- `/mcp` 是每次凭据头认证的 API，CSRF 只对该路径豁免；未禁用认证或开放所有 URL。其他路径默认拒绝，应用绑定 loopback。
- 日志不记录异常消息、请求头或参数；SDK 异常日志关闭，改由结构化脱敏业务审计覆盖已注册工具执行结果与未知工具预检。当前不提供完整认证失败审计流水。
- unknown、missing resource、跨租户等不回显敏感内容。资源不存在和资源无权访问统一 FORBIDDEN。
- resource tenant 不可修改，更新通过 ConcurrentHashMap.computeIfPresent 原子递增 version；当前是 last-write-wins，没有乐观锁前置条件、幂等 key 或审批流。
- 审计只保留最近 200 条，业务与审计重启即丢失；BCrypt 每次验证有成本，尚未实现限流和密钥轮换。项目用于 Phase 1 本地工程演示。

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
| 你个人实现了哪些？ | ERP 模拟工具、可信身份目录、租户与资源授权、严格参数、脱敏审计和 HTTP 安全验收；认证库/MCP 协议是上游 |
| 进入生产还缺什么？ | 密钥生命周期、限流、持久化审计、监控、写操作幂等/并发控制、依赖升级验证 |

## 简历表述参考

基于 Spring AI MCP 和 MCP Security 构建 Agent 工具调用安全网关，复用 API Key 认证，新增服务端权限、租户及资源级授权，保护两个模拟 ERP 工具；通过 11 项真实 MCP HTTP 集成测试验证越权拒绝、参数校验、无拒绝副作用及日志脱敏。

不要表述为自研 MCP 协议、安全认证库、通用 Prompt Injection 检测器或已经生产上线的企业平台。
