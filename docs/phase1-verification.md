# Phase 1 实际验收记录

验收日期：2026-10-14，Asia/Shanghai。范围仅 P3 Phase 1。

2026-10-26公开准备说明：下表JDK路径中的`%USERPROFILE%`仅用于脱敏展示当时的Windows用户目录，原始执行使用本机实际绝对路径；未改变JDK版本、执行结果或历史Git提交。

## 环境与版本

| 项目 | 实测值 |
| --- | --- |
| 系统 | Windows 11 amd64 / PowerShell |
| 工作目录 | E:\codeplace\llm-agent\agent-security-gateway |
| Java | Microsoft OpenJDK 17.0.16+8-LTS，真实 JDK 17 |
| JDK 路径 | %USERPROFILE%\.jdks\ms-17.0.16（用户目录已脱敏） |
| Maven | 3.9.1 |
| Git | 2.54.0.windows.1 |
| Spring Boot / Security | 3.5.4 / 6.5.2 |
| Spring AI / MCP SDK | 1.1.2 / 0.15.0 |
| MCP Security | 0.0.6，Maven 发布依赖 |

默认 Java 原为 25；所有最终构建和服务器验收均显式使用 JDK 17。两个目标目录开始时均不存在，未覆盖用户文件。P1、P2 未执行任何写入操作；检查时 P1 工作树干净，P2 已有 `?? test-data/`，保持原样。

## 上游复现

唯一上游：[mcp-security v0.0.6](https://github.com/spring-ai-community/mcp-security/tree/25b9ef1ba9d22bedb1100c85056baee6e9ce0a18)。

固定 Commit：`25b9ef1ba9d22bedb1100c85056baee6e9ce0a18`，detached HEAD。

本地位置：`E:\codeplace\llm-agent\reference-projects\mcp-security`。

已阅读 README、Apache-2.0 LICENSE、API Key 示例、secured-tools 示例及 API-key configurer/provider/filter/repository 源码。主分支与发布标签的 Spring AI/Boot 版本不同，使用 Java 17 兼容的发布标签组合；未混用不同分支源码。必要 reactor 仅包含 parent、mcp-server-security、API Key sample，未构建其他示例或接入模型。

构建命令（JAVA_HOME 和 PATH 指向 JDK 17）：

```powershell
mvn -B '-Dmaven.repo.local=E:\codeplace\llm-agent\.p3-cache\repository' -pl samples/sample-mcp-server-api-key -am package -DskipTests
mvn -B '-Dmaven.repo.local=E:\codeplace\llm-agent\.p3-cache\repository' -pl samples/sample-mcp-server-api-key -am package spring-boot:repackage -DskipTests
```

均为 BUILD SUCCESS。上游运行于 `127.0.0.1:18092`，使用发布示例自己的演示凭据，仅在隔离复现内使用，未复制到 P3。关闭运行时 Security TRACE，未关闭认证。实际请求证据在上游 `target/upstream-evidence.json`，探测脚本在 `target/upstream-probe.py`（从上游配置读取演示凭据，不落盘密钥）。

| 上游真实 HTTP 验证 | 结果 |
| --- | --- |
| 无密钥 initialize | 403，拒绝；原样例的 CSRF/entry-point 行为 |
| 错误 secret initialize | 401，拒绝 |
| 正确凭据 initialize | 200，协商协议 2025-06-18 |
| tools/list | 200，current-temperature |
| tools/call | 200、isError=false；Open-Meteo 返回 temperature_2m=20.4，time=2026-10-14T10:00:00 |

天气网络请求只用于上游原工具的复现，未接入收费模型；P3 自己的工具与测试完全本地。

定位并解决的环境问题：本机遗留 Git 代理指向不可用 localhost；该次克隆使用命令级空代理和 OpenSSL TLS backend，未修改全局 Git 配置、未关闭 TLS 校验。Windows 长路径通过参考仓库局部 `core.longpaths=true` 解决。全局 Maven 仓库位于不可写的 D 盘，改为工作区独立缓存，未修改全局配置。

定位的上游行为：0.0.6 `ApiKeyImpl.from()` 按点分隔后仅取前两段，合法 key 追加额外点分段仍可认证。P3 先严格验证一个点、合法 ID/secret 长度与字符、单个凭据头，再委托上游 converter/provider；没有重写密码学。自动测试覆盖额外点分段和缺失 secret。

## P3 自动验收

最终运行：

```powershell
./scripts/verify.ps1 -MavenRepository 'E:\codeplace\llm-agent\.p3-cache\repository'
```

2026-10-14 18:11:57 +08:00，最终 Maven verify BUILD SUCCESS。

Failsafe 汇总：**Tests run: 11, Failures: 0, Errors: 0, Skipped: 0**。

测试类 `src/test/java/dev/p3/gateway/McpSecurityIT.java` 使用 RANDOM_PORT 启动真实嵌入式 Tomcat，以 JDK HttpClient 发 HTTP POST 到 `/mcp`。没有使用 MockMvc，也没有通过直接调用工具方法来代替 MCP 验收。仅通过 ErpStore.snapshot() 检查业务副作用。

| JUnit 场景 | HTTP / MCP 断言 |
| --- | --- |
| initializeAndDiscoverExactlyTwoTools | 200，协商协议正确，精确发现两工具 |
| credentialsRequiredForEveryMcpMethod | initialize/list/call 的缺失、同长度同格式错误 secret、畸形、额外点分段、空 secret 均 401；错误 secret 经过上游认证校验 |
| readerReadsAuthorizedInventory | reader-a 正常读 sku-a1，库存 120 |
| buyerUpdatesOwnOrderWithObservableMutation | buyer-a 修改 po-a1=25，version 增加 1 |
| readerCannotWrite | 无写权限，FORBIDDEN |
| bothTenantsCannotCrossReadOrWrite | A/B 双向跨租户读写拒绝，B 本租户读正常 |
| sameTenantUnassignedResourcesDenied | 同租户 sku-a2/po-a2 仍拒绝 |
| unknownToolDeniedWithoutReflectingUntrustedName | 工具名包含运行时凭据仍返回固定 UNKNOWN_TOOL，无秘密反射 |
| invalidParametersDenied | 越界整数、字符串、浮点、布尔、大整数、缺字段、非法 ID 拒绝 |
| agentForgedRoleAndTenantCannotBypassPolicy | Agent 伪造 role/tenantId 被拒；移除伪造字段后真实跨租户仍拒绝 |
| errorsAndAuditDoNotLeakSecrets | 把运行时凭据注入业务参数，错误响应、审计、捕获日志均不包含任何测试 secret |

每个工具拒绝场景均断言请求前后**全部订单 snapshot 完全一致**。认证拒绝也检查全部订单不变。审计断言包括可信 caller、DENY、原因码与 UUID。三份随机凭据只在进程环境中生成、继承和恢复。

原始 Maven/Failsafe 报告在 `target/failsafe-reports`，开发输出在 `verify.log`；均被 Git 忽略，不把运行时日志提交到仓库。

## 打包 JAR 独立验收

`./scripts/demo.ps1` 于 2026-10-14 18:12 成功：启动独立 JVM 的打包 JAR，真实 HTTP 验证 initialize、list、读库存、合法改单、低权限写、跨租户写、Agent 伪造参数、缺失/畸形/同格式错误密钥和未知工具。该验收不计入 11 项 JUnit 数量。

最终脱敏证据：`target/demo/80841b028b9d4296b827f49fe9bc76af/evidence.json`。脚本自动停止自己的 JVM，并恢复环境变量。

另以清除 P3 secret 环境变量的独立 JVM 验证缺失凭据配置：应用退出码非零，出现固定配置提示，拒绝启动。上游示例运行进程也已根据 PID、启动时间和 Java 路径确认后停止。

打包 JAR `BOOT-INF/lib` 检查确认 MCP SDK 各核心模块统一为 **0.15.0**，MCP Security 为 **0.0.6**，Spring AI 为 **1.1.2**。Spring AI transitive 默认原会选 SDK 0.17.0；P3 显式导入上游同版本 MCP BOM 后复跑 verify 与打包验收通过。

## 交付检查与边界

没有真实模型、企业数据库、消息中间件或采购调用。只有上游复现曾访问免费天气接口。未修改 P1/P2，未操作 Docker，未配置 Git remote 或 push。P3 是独立 Git 仓库，仅建立本地 Phase 1 Commit。

安全错误只使用固定原因码；审计不记录凭据、原始参数、未注册工具名或异常堆栈。最终检查源码、文档、脚本、验收文本输出和 Git 暂存内容，未发现密钥或敏感文件；Git diff --check 通过。许可证为 Apache-2.0，保留借鉴配置的上游版权和 NOTICE。

Phase 1 已验证指定最小安全要求。生产部署、密钥轮换、限流、耐久审计和并发写语义属于后续工作，未宣称已实现。
