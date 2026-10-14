# P3 简历描述与真实技术亮点

项目：企业级 Agent 工具调用安全网关（Agent Tool Security Gateway）。Java 17、Spring Boot、Spring Security、Spring AI MCP、MCP Security、Bean Validation、JUnit/Failsafe。

## Java 后端安全版本

基于 Spring Security 和 MCP Security 构建工具调用安全网关，复用 API Key 认证，新增服务端权限映射、租户与资源级授权、参数校验及脱敏审计；使用绑定主体和精确操作的短期单次授权保护虚拟采购写入，通过真实 MCP HTTP 验证越权拒绝与并发重放安全。

## Agent 安全版本

构造虚拟 ERP 备注的间接提示词注入场景，使用确定性 Mock Agent 模拟被诱导的工具提议；在执行端通过可信身份、资源策略及操作意图阻断未授权调用，建立 24 场景真实 MCP 评测与 JSON/CSV/Markdown 报告，区分危险提议、网关决策、实际业务执行和状态改变。

## 可验证技术亮点

- 将上游 API Key 认证接入真实 MCP HTTP 入口，结合 @PreAuthorize 与独立 PolicyService 实现权限、租户、资源联合判定；默认拒绝未知工具和 Agent 伪造身份字段。
- 设计绑定用户、工具、租户、订单与数量的 60 秒单次写意图，签发来自本地可信操作员确认；校验、消费和更新共享临界区，受控并发实验只产生一次修改。
- 保留原有 19 项安全回归，新增一个执行 24 场景的评测入口，完整 Maven verify 共 20 项通过；本地样本 8/8 合法请求执行、16/16 非法执行阻断，非法执行与合法误拒绝均为 0。
- 通过真实 HTTP、测试侧业务执行观测和全量订单快照核对无拒绝副作用；自动输出脱敏结构化报告与原因分布，一键完成 verify、评测和独立 JAR 演示。

证据：[Phase 3 验收](phase3-verification.md)、[本次报告](evaluation/report.md)、[逐条 JSON](evaluation/results.json)、[上游与个人边界](upstream-vs-custom.md)。

20 是 JUnit 数量，24 是其中表驱动入口的场景数量，不能相加宣称 44 个独立测试。100% 阻断仅针对这 16 个本地固定样本；Mock 不是真实模型，控制台不是终端用户同意验证。不要声称自研 MCP 协议、认证库、通用注入检测器或生产落地平台。延迟是带测试观测的小样本往返时间，不作为性能优化成果。
