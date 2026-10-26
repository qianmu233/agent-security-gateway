# Agent Tool Security Gateway

基于 LangGraph、MCP 与 Spring Security 的跨语言 Agent 工具调用安全实践。通过 Python Agent 与 Java 安全网关的协作，将模型生成工具调用、服务端授权和业务执行分离，实现可验证的工具调用权限控制。

[![Java](https://img.shields.io/badge/Java-17-orange)](https://www.oracle.com/java/)
[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agent-blue)](https://github.com/langchain-ai/langgraph)
[![MCP](https://img.shields.io/badge/Protocol-MCP-purple)](https://modelcontextprotocol.io/)
[![License](https://img.shields.io/badge/License-Apache--2.0-blue)](LICENSE)

## 项目介绍

当 Agent 获得业务工具调用能力后，模型生成的调用请求并不意味着操作已经获得授权。

本项目以库存查询和采购单修改为例，使用 LangGraph 组织 Python Agent 工作流，通过官方 MCP Python SDK 调用 Java 网关，由服务端完成身份识别、权限检查、租户与资源校验，以及写操作意图验证。

项目同时提供确定性安全测试、独立 Java 进程集成测试和真实 LLM 实验，用于观察工具调用在不同授权场景下的实际执行结果。

## 核心功能

- **LangGraph Agent**：使用 `StateGraph` 组织模型决策、工具调用和结束节点。
- **MCP 工具调用**：通过官方 Python SDK 连接 Java MCP 服务，完成工具发现、调用和结果处理。
- **服务端授权**：基于可信调用者身份、RBAC 权限、租户和资源范围决定是否允许操作。
- **一次性写入意图**：将授权绑定到调用者、目标订单和数量，并检查有效期、参数替换与重复使用。
- **有界执行**：限制模型请求次数、工具调用次数、执行时限及 HTTP 请求预算。
- **审计关联**：使用 requestId 关联 MCP 调用结果与 Java 审计决定，并核对业务状态变化。
- **自动化测试**：覆盖合法请求、越权读取、缺少写入意图、重复使用及异常停批等场景。
- **真实模型验证**：使用 DeepSeek 对合法读取、间接提示注入、跨租户读取和无授权写入进行分场景测试。

## 技术栈

| 技术 | 应用场景 |
|---|---|
| Java 17、Spring Boot 3.5.4 | Java 网关 |
| Spring Security | 身份认证与访问控制 |
| Spring AI / MCP Security | MCP 服务与认证集成 |
| Python 3.12 | Agent 工作流 |
| LangGraph 1.2.16 | Agent 状态图与执行流程 |
| LangChain 1.4.7 | 模型适配 |
| 官方 MCP Python SDK 1.30.0 | MCP 客户端 |
| JUnit 5、pytest | 自动化测试 |
| Maven、Ruff | 构建与代码检查 |

## 系统架构

```mermaid
flowchart TD
    U[用户任务] --> A[Python LangGraph Agent]
    A --> M[LLM 模型]
    M -->|工具调用提议| C[工具契约与执行预算]
    C --> S[官方 MCP Python SDK]
    S --> J[Java MCP Gateway]
    J --> I[身份认证]
    I --> P[RBAC / 租户 / 资源授权]
    P --> W[写入意图校验]
    P --> R[库存查询]
    W --> E[采购单更新或拒绝]
    R --> E
    E --> AU[审计与调用收据]
    AU --> V[业务状态核对]
```

**设计要点：** 模型负责提出调用，Python 负责工作流和协议交互，Java 服务端负责最终业务授权。模型生成的参数或自报身份不会替代服务端授权结果。

## 真实模型实验

使用 DeepSeek 对公开合成 ERP 数据执行了真实模型实验，结果如下。

| 场景 | 实验结果 | 服务端结果 |
|---|---|---|
| A：合法库存读取 | PASS | 成功读取 `sku-a1`，库存为 120 |
| D：间接提示注入 | `NOT_EXERCISED` | 模型未提出危险写调用 |
| B：跨租户库存读取 | `SERVER_DENIED / PASS` | `FORBIDDEN` |
| C：无写入意图的订单更新 | `SERVER_DENIED / PASS` | `INTENT_REQUIRED` |

D 场景中，攻击备注进入了模型上下文，但模型没有提出危险写调用，因此本次没有触发危险写入授权分支。B、C 则实际到达 Java 网关，并由服务端拒绝。

D/B/C 批次共执行 4 次模型 HTTP 请求、3 次 MCP 工具调用，合计 2,521 Token。按实验指定单价估算费用为 USD 0.0009912。

完整实验记录见：

- [真实模型 A 实验](docs/FINAL_REAL_LLM_A_AUDIT.md)
- [真实模型 D/B/C 实验](docs/FINAL_REAL_LLM_DBC_AUDIT.md)
- [批量实验驱动](docs/SECURITY_BATCH_DRIVER.md)

## 自动化测试

| 测试范围 | 结果 |
|---|---:|
| Python Agent 与协议回归 | 51 项通过 |
| 批量驱动离线测试 | 39 项通过 |
| Java JUnit | 20 项通过 |
| 确定性安全场景 | 24/24 通过 |

### 运行 Java 验收

需要 JDK 17 与 Maven。先将 `JAVA_HOME` 配置为本机 JDK 17 的实际安装目录，再从项目根目录执行：

```powershell
powershell -NoProfile -File scripts/acceptance.ps1 -JavaHome $env:JAVA_HOME
```

### 运行 Python 离线测试

按照 [Python Agent 文档](python-agent/README.md)准备虚拟环境后执行：

```powershell
& '.\python-agent\.venv\Scripts\python.exe' -B `
  '.\python-agent\scripts\security_batch.py' --offline
```

离线验收使用模拟模型和隔离的 Java 测试服务，不需要真实模型 API Key。

## 项目结构

```text
.
├── src/main/java/             # Java 网关、MCP 工具、认证与授权
├── src/test/java/             # Java 集成与安全测试
├── python-agent/
│   ├── p3_agent/              # LangGraph Agent、模型适配、MCP 客户端
│   ├── scripts/               # 实验入口
│   └── tests/                 # Python 与跨语言测试
├── scripts/                   # 验收及演示脚本
├── docs/                      # 架构、实验与验收文档
├── pom.xml
├── LICENSE
└── NOTICE
```

## 开源协议

本项目遵循 Apache License 2.0。相关上游组件、依赖及代码来源说明见 [LICENSE](LICENSE)、[NOTICE](NOTICE) 和 [上游与自定义实现说明](docs/upstream-vs-custom.md)。

