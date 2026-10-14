# 企业级 Agent 工具调用安全网关

Agent Tool Security Gateway · P3 Phase 1

一个可运行的 Java 后端安全项目：在真实 MCP HTTP 入口验证 API Key，在工具执行前按可信身份、权限、租户和资源范围授权。即使 Agent 生成越权调用，服务端仍拒绝执行。ERP 数据全部在内存中模拟，重启即恢复初始状态。

本阶段仅提供两个工具、三个固定测试身份和最小审计。没有真实 LLM、企业数据库、采购系统或前端。

## 技术与来源

Java 17 / Spring Boot 3.5.4 / Spring AI 1.1.2 / MCP Java SDK 0.15.0 / Spring Security 6.5.2 / MCP Security 0.0.6 / Bean Validation / JUnit 5。

唯一 GitHub 参考项目是 [spring-ai-community/mcp-security](https://github.com/spring-ai-community/mcp-security/tree/25b9ef1ba9d22bedb1100c85056baee6e9ce0a18)，固定标签 `v0.0.6`。API Key 过滤器、认证 Provider、BCrypt 校验和凭据仓库复用发布依赖；MCP 协议由 Spring AI / SDK 实现。个人新增内容见 [上游与个人工作边界](docs/upstream-vs-custom.md)。许可证与配置借鉴声明见 LICENSE、NOTICE。

## 构建与一键验收

在本项目目录执行 PowerShell：

```powershell
./scripts/verify.ps1 -JavaHome 'C:\Users\R9000P\.jdks\ms-17.0.16'
./scripts/demo.ps1 -JavaHome 'C:\Users\R9000P\.jdks\ms-17.0.16'
```

请按本机实际 JDK 17 路径修改 `-JavaHome`。verify 自动产生三个临时随机 secret，通过进程环境传给 Maven 测试，并执行完整 `mvn verify`。demo 启动打包 JAR，执行真实 MCP initialize/list/call 和拒绝案例，再停止自己启动的进程。两者结束时恢复原环境变量，不输出或保存密钥。验收无需模型账户。

默认 Maven 缓存在被忽略的 `.local/repository`。本次开发使用工作区独立缓存，可复用：

```powershell
./scripts/verify.ps1 -MavenRepository 'E:\codeplace\llm-agent\.p3-cache\repository'
```

## 持续启动与认证配置

需要三个不同的随机 secret，每个是 32–64 位 ASCII 字符，只允许字母、数字、下划线、连字符。没有默认密钥；缺少或无效配置会阻止应用启动。可由外部环境配置，或在当前 PowerShell 安全交互输入：

```powershell
$env:JAVA_HOME = 'C:\Users\R9000P\.jdks\ms-17.0.16'
foreach ($name in @('P3_READER_A_SECRET','P3_BUYER_A_SECRET','P3_BUYER_B_SECRET')) {
    $value = Read-Host "Enter $name" -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($value)
    try {
        [Environment]::SetEnvironmentVariable($name, [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr), 'Process')
    } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr); $value.Dispose() }
}
& "$env:JAVA_HOME\bin\java.exe" -jar target/agent-security-gateway-0.1.0.jar --debug=false
```

入口 `http://127.0.0.1:8093/mcp`，使用 `STATELESS`、`SYNC`。用 `P3_PORT` 改端口。每次请求都需要 `X-API-Key`，值为 `<服务端身份ID>.<对应secret>`。客户端只能提交工具业务参数，不能设置授权角色或租户。密钥在启动时由上游 builder 哈希，仓库中保存 BCrypt 哈希。

| 身份 ID | 服务端角色 | 租户 | 权限 | 授权资源 |
| --- | --- | --- | --- | --- |
| reader-a | READER | tenant-a | inventory.read | sku-a1 |
| buyer-a | BUYER | tenant-a | inventory.read、purchase_order.update | sku-a1、po-a1 |
| buyer-b | BUYER | tenant-b | inventory.read、purchase_order.update | sku-b1、po-b1 |

role 用于解释身份，实际授权以明确 permission、tenant、resource 三项共同决定。`sku-a2` 和 `po-a2` 虽属 tenant-a，也不在上述身份的资源授权范围内。

## MCP 工具与演示请求

每个 POST 设置 `Content-Type: application/json`、`Accept: application/json, text/event-stream`、`MCP-Protocol-Version: 2025-06-18` 和 API Key 头。认证前置覆盖 initialize、tools/list、tools/call。

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"p3-demo","version":"1"}}}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"inventory.read","arguments":{"productId":"sku-a1"}}}
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"purchase_order.update","arguments":{"orderId":"po-a1","quantity":25}}}
```

| 工具 | 输入 | 返回与约束 |
| --- | --- | --- |
| inventory.read | productId | 已授权商品的库存；初始 sku-a1=120、sku-a2=30、sku-b1=80 |
| purchase_order.update | orderId、quantity | 修改采购单数量并原子增加 version；quantity 必须是 1–1000 的整数 |

初始订单 po-a1=10、po-a2=20、po-b1=30，version=0。非法类型、缺失字段、额外字段（包括 role/tenantId）、未知资源与越权调用均被拒绝。

认证失败 HTTP 401；工具拒绝使用 HTTP 200 + MCP `isError=true`，文本内容是 `{code,requestId}`。未知工具返回 JSON-RPC error `-32602 / UNKNOWN_TOOL`。允许调用返回 `{data,requestId}`。跨租户、未授权资源和资源不存在统一返回 FORBIDDEN，不泄漏资源存在性。审计只记录服务端 caller、注册工具名/固定 unregistered、decision、reason、UUID。

## 学习与阶段边界

- [实际验收证据](docs/phase1-verification.md)
- [源码与面试复盘](docs/project-review.md)
- [上游与个人新增功能](docs/upstream-vs-custom.md)

Phase 1 是本地安全工程原型。固定身份、内存数据、最近 200 条审计和同步 BCrypt 验证用于解释与验证最小授权链路；后续上线前需要评估版本升级、密钥生命周期、限流、审计持久化与写操作幂等性。Phase 2 尚未实现。
