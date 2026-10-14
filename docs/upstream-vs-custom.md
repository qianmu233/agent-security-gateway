# 上游已有能力与个人新增工作

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
| 11 项真实 HTTP 集成测试及打包 JAR 演示 | P3 JUnit/Failsafe 与 PowerShell 脚本 | 是 |
| OAuth2 授权服务器、客户端安全、天气工具等 | 上游仓库其他功能 | 未作为个人成果；未引入 P3 |

P3 不复制上游安全库源码，仅通过 Maven 依赖复用。`SecurityConfiguration.java` 参考上游 API Key 示例的配置模式，保留上游版权与 Apache-2.0 头。个人修改包括环境凭据、失败即阻止启动、固定身份、无状态认证、只保护 MCP API、严格凭据头和脱敏预检，详见根目录 NOTICE 和 LICENSE。

上游演示凭据仅存在于参考仓库隔离运行中，没有进入 P3 的配置、测试或文档。P3 测试凭据由脚本随机生成后仅通过环境继承。

个人工程价值在于把现有认证组件接入真实 MCP 请求链，在虚拟 ERP 业务执行前实现最小可信授权，并提供可以复现的安全证据。不存在“自研 MCP 协议/API Key 算法/完整安全框架”的成果声明。
