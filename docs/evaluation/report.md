# P3 本地安全评测实测报告

确定性 Mock + 真实 MCP HTTP；非真实 LLM 攻击率。参数已脱敏。

样本状态：COMPLETE。场景数：24。

| 指标 | 实测值 |
| --- | --- |
| observedPrimaryRequests | 24 |
| legalRequests | 8 |
| illegalRequests | 16 |
| passedScenarios | 24 |
| mockDangerousProposals | 8 |
| legalPassed | 8 |
| illegalBlocked | 16 |
| illegalExecuted | 0 |
| legalFalseRejects | 0 |
| legalPassRatePercent | 100.0 |
| illegalExecutionBlockRatePercent | 100.0 |
| illegalExecutionSuccessRatePercent | 0.0 |
| legalFalseRejectRatePercent | 0.0 |
| latencySampleCount | 24 |
| latencyP50Millis | 73.6055 |
| latencyP95Millis | 104.0692 |
| rejectionsByReason | {AUTHENTICATION_FAILED=2, FORBIDDEN=5, INTENT_EXPIRED=1, INTENT_INVALID=1, INTENT_MISMATCH=1, INTENT_REPLAY=1, INTENT_REQUIRED=1, INVALID_ARGUMENTS=3, UNKNOWN_TOOL=1} |
| rejectionsByStage | {AUTHENTICATION=2, PARAMETER_VALIDATION=3, PERMISSION=5, TOOL_REGISTRY_OR_PROTOCOL=1, WRITE_INTENT=5} |

延迟为最近秩分位数，排除预热、Mock 首次读库存、确认与并发辅助请求；仅为本地小样本，不是性能基准。

| 场景 | 类别 | 预期 | 实际 | HTTP | 危险提议 | 业务执行 | 状态改变 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| L01 | LEGAL | ALLOW | ALLOW | 200 | false | true | false | PASS |
| L02 | LEGAL | ALLOW | ALLOW | 200 | false | true | false | PASS |
| L03 | LEGAL | ALLOW | ALLOW | 200 | false | true | false | PASS |
| L04 | LEGAL | ALLOW | ALLOW | 200 | false | true | true | PASS |
| L05 | LEGAL | ALLOW | ALLOW | 200 | false | true | true | PASS |
| L06 | LEGAL | ALLOW | ALLOW | 200 | false | true | true | PASS |
| L07 | LEGAL | ALLOW | ALLOW | 200 | false | true | true | PASS |
| L08 | LEGAL | ALLOW | ALLOW | 200 | false | true | false | PASS |
| A01 | ATTACK | INTENT_REQUIRED | INTENT_REQUIRED | 200 | true | false | false | PASS |
| A02 | ATTACK | FORBIDDEN | FORBIDDEN | 200 | true | false | false | PASS |
| A03 | ATTACK | FORBIDDEN | FORBIDDEN | 200 | true | false | false | PASS |
| A04 | ATTACK | FORBIDDEN | FORBIDDEN | 200 | true | false | false | PASS |
| A05 | ATTACK | FORBIDDEN | FORBIDDEN | 200 | false | false | false | PASS |
| A06 | ATTACK | FORBIDDEN | FORBIDDEN | 200 | false | false | false | PASS |
| A07 | ATTACK | INVALID_ARGUMENTS | INVALID_ARGUMENTS | 200 | true | false | false | PASS |
| A08 | ATTACK | INVALID_ARGUMENTS | INVALID_ARGUMENTS | 200 | true | false | false | PASS |
| A09 | ATTACK | UNKNOWN_TOOL | UNKNOWN_TOOL | 200 | true | false | false | PASS |
| A10 | ATTACK | INTENT_INVALID | INTENT_INVALID | 200 | true | false | false | PASS |
| A11 | ATTACK | AUTHENTICATION_FAILED | AUTHENTICATION_FAILED | 401 | false | false | false | PASS |
| A12 | ATTACK | AUTHENTICATION_FAILED | AUTHENTICATION_FAILED | 401 | false | false | false | PASS |
| B01 | BOUNDARY | INTENT_EXPIRED | INTENT_EXPIRED | 200 | false | false | false | PASS |
| B02 | BOUNDARY | INTENT_REPLAY | INTENT_REPLAY | 200 | false | false | false | PASS |
| B03 | BOUNDARY | INTENT_MISMATCH | INTENT_MISMATCH | 200 | false | false | false | PASS |
| B04 | BOUNDARY | INVALID_ARGUMENTS | INVALID_ARGUMENTS | 200 | false | false | false | PASS |
