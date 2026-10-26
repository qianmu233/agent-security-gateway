# Agent Tool Security Gateway

**Agent 工具调用安全授权网关**

基于 LangGraph、MCP 与 Spring Security 的 Agent 工具调用安全网关。通过 Python Agent 与 Java MCP 服务协作，在业务工具真正执行前完成身份认证、权限校验、资源授权和高风险写操作验证。

## 项目介绍

Agent 可以根据用户问题生成工具调用，但模型提出调用并不代表用户有权执行该操作。

例如，Agent 读取库存信息后，可能继续尝试修改采购单；即使模型已经生成了合法格式的工具请求，Java 服务端仍需要判断调用者是否有对应权限、订单是否属于该租户，以及本次写操作是否经过可信授权。

本项目以库存查询和采购单修改为例，将 Agent 的工具调用流程与服务端业务授权分离。Python 使用 LangGraph 组织 Agent 执行过程，通过官方 MCP Python SDK 调用 Java 网关；Java 侧负责最终授权与业务执行。

## 技术栈

| 技术 | 用途 |
|---|---|
| Java 17 | 安全网关与业务服务 |
| Spring Boot 3.5.4 | Java 应用框架 |
| Spring Security | 身份认证与安全上下文 |
| Spring AI / MCP Security | MCP 服务与认证集成 |
| Python 3.12 | Agent 客户端 |
| LangGraph 1.2.16 | Agent 状态图与执行流程 |
| LangChain 1.4.7 | 模型消息与调用适配 |
| 官方 MCP Python SDK 1.30.0 | MCP 工具发现与调用 |
| Maven、JUnit 5、pytest | 构建与自动化测试 |

## 系统架构

```text
用户任务
   │
   ▼
Python LangGraph Agent
   │
   ├── decide：调用模型，获取回答或 Tool Call
   │
   ├── tool：校验参数，通过 MCP 调用 Java
   │
   └── finish：整理结果并结束任务
                │
                ▼
       官方 MCP Python SDK
                │
                ▼
          Java MCP Gateway
                │
                ▼
           API Key 认证
                │
                ▼
        可信身份与权限策略
                │
        ┌───────┴────────┐
        │                │
        ▼                ▼
    库存查询         写意图校验
        │                │
        │                ▼
        │            采购单修改
        │                │
        └───────┬────────┘
                ▼
           审计与业务结果
```

## 核心实现

### 1. Java MCP 工具执行入口

Java 侧通过 MCP 暴露两个演示工具：

- `inventory.read`：查询指定商品的库存。
- `purchase_order.update`：修改指定采购单的数量。

`ToolConfiguration` 定义工具，`ToolGateway` 负责工具调用处理，`McpBoundaryFilter` 处理 MCP 边界上的请求。

Python Agent 通过 MCP 的 `tools/list` 获取工具定义，通过 `tools/call` 发起调用。请求经过真实 HTTP 入口进入 Java 服务，而不是直接调用 Java 内部的业务方法。

### 2. API Key 与可信身份

网关通过 API Key 识别调用者，再由 `IdentityDirectory` 将认证结果映射为服务端配置的身份信息。

身份信息包含主体、角色、租户和可访问资源。模型生成的参数只描述要查询的商品或要修改的订单，不能通过自报 `role`、`tenant` 或 `principal` 来改变服务端身份。

这使身份认证与模型输出相互独立：即使 Agent 生成了越权请求，也不会因此获得新的业务权限。

### 3. RBAC 与资源级授权

`PolicyService` 负责判断当前身份能否调用指定工具，并检查工具权限、租户和资源范围。

例如：

- `reader-a` 可以读取租户 A 的指定库存。
- `buyer-a` 可以读取授权库存，并对授权采购单执行写操作。
- `buyer-b` 只能访问租户 B 中配置的资源。

授权判断不仅检查用户是否拥有某个角色，还会核对当前请求中的实际租户和资源。未知工具、未授权资源和跨租户请求都会在业务执行前被拒绝。

### 4. 一次性可信写意图

对于采购单修改，项目在原有工具权限之外增加了本次操作的可信授权。

`TrustedIntentConsole` 提供本地操作员确认入口，`WriteIntentService` 负责生成、验证和消费写意图。

写意图有效期为 60 秒，并绑定以下信息：

- 调用者身份；
- 工具名称；
- 租户；
- 目标采购单；
- 修改数量。

执行时，Java 会重新核对上述字段，并检查意图是否过期、已被消费或被重复使用。意图消费与内存业务修改位于同一同步执行区间，避免同一个有效意图被并发重复消费。

写意图由可信操作员确认后签发，不是模型可以自行调用的工具。模型可以提出修改请求，但不能通过生成一个 `intentId` 来授权自己执行修改。

### 5. 审计与拒绝处理

`AuthenticationAuditFilter` 和 `AuditTrail` 记录认证及安全决策，`ToolGateway` 将工具执行结果返回给 MCP 客户端。

对于业务拒绝，网关返回明确的原因，例如：

- `FORBIDDEN`：身份、权限、租户或资源不符合授权要求。
- `INTENT_REQUIRED`：写操作缺少有效写意图。
- `INTENT_EXPIRED`：写意图已过期。
- `INTENT_MISMATCH`：当前调用与写意图绑定的参数不一致。
- `INTENT_REPLAY`：写意图已被使用。

客户端将 MCP 工具结果与 Java 审计记录关联，并检查采购单的数量和版本是否发生变化。这样可以区分“模型提出了什么调用”“服务器是否拒绝”以及“业务状态是否真的发生改变”。

### 6. Python LangGraph Agent

Python 侧的 `python-agent/p3_agent/` 实现 Agent 工作流。

`graph.py` 使用 `StateGraph` 组织 `decide`、`tool` 和 `finish` 三个节点：

- `decide`：调用模型，读取原生 `tool_calls`。
- `tool`：检查工具名称与参数，通过 MCP SDK 调用 Java。
- `finish`：处理成功结果、拒绝结果或执行结束条件。

`contracts.py` 定义工具参数和结果结构，拒绝未知字段和不符合要求的参数；`client.py` 使用官方 MCP SDK 完成初始化、工具发现和工具调用；`models.py` 负责 Fake 模型与真实聊天模型适配。

工作流对模型请求次数、工具调用次数和执行时间设置上限。遇到工具拒绝或执行错误时，流程按相应结果结束，而不是无限重试。

工具返回的库存备注作为不可信工具结果传递给 Agent。Python 侧不会把备注内容升级为系统指令，也不会把写意图交给模型生成。最终是否允许执行修改，仍由 Java 决定。

## 场景演示

### 合法库存查询

Agent 请求查询 `sku-a1`，通过 MCP 调用 Java 的 `inventory.read`，获得库存数量 120。Java 审计记录了对应调用者、工具和允许执行的决定。

### 跨租户读取

Agent 使用租户 A 的身份请求读取租户 B 的 `sku-b1`。请求实际到达 Java 网关，但由于资源不属于该身份的授权范围，服务端返回 `FORBIDDEN`，没有返回目标库存数据。

### 未授权采购单修改

Agent 提出修改采购单的工具调用，但当前没有对应的有效写意图。请求到达 Java 后返回 `INTENT_REQUIRED`，采购单数量和版本保持不变。

### 间接提示注入

在一次真实 DeepSeek 实验中，库存备注中的攻击内容进入了模型上下文，但模型没有提出危险的采购单修改调用，因此该次没有触发写操作授权分支。

这与前两个场景不同：跨租户读取和缺少写意图的修改都实际到达了 Java，并由服务端拒绝；提示注入场景中，不能将模型没有提出危险调用说成网关成功阻断了该次攻击。

## 本地运行

需要 JDK 17 和 Maven。在 Windows PowerShell 中配置好 `JAVA_HOME` 后，从仓库根目录执行：

```powershell
powershell -NoProfile -File scripts/acceptance.ps1 -JavaHome $env:JAVA_HOME
```

该脚本会运行 Java 构建与本地验收流程，使用隔离的演示业务数据和临时凭据，不需要真实模型 API Key 或数据库。

Python Agent 的依赖安装、CLI 参数和独立运行方式见 [`python-agent/README.md`](python-agent/README.md)。

## 项目结构

```text
.
├── src/main/java/dev/p3/gateway/
│   ├── audit/       # 审计记录
│   ├── erp/         # 演示 ERP 数据与业务操作
│   ├── mcp/         # MCP 工具定义与执行入口
│   └── security/    # 身份、授权、写意图与控制台
├── src/test/java/   # MCP HTTP、安全与集成测试
├── python-agent/
│   ├── p3_agent/    # LangGraph、模型适配、MCP 客户端
│   └── tests/       # Python 与跨语言测试
├── scripts/         # 本地验收与演示脚本
├── pom.xml
├── LICENSE
└── NOTICE
```

## 开源协议

项目使用 Spring AI MCP 相关组件，并参考 [Spring AI Community MCP Security](https://github.com/spring-ai-community/mcp-security) 的认证集成方式。Agent 工作流基于 [LangGraph](https://github.com/langchain-ai/langgraph)，MCP 客户端使用 [官方 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)。

项目遵循 Apache License 2.0，相关许可信息见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。

