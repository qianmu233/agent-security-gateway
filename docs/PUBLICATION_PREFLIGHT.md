# P3 公开发布前复核（2026-10-26）

本轮只做路径配置、文档同步、静态扫描和无费用回归，不增加 Agent 功能，不调用真实模型，不提交或推送。复核基线为 `86d2c58f8c98b0e74cbe3be750ed2f7f72fcf052`，分支为 `feature/python-langgraph-agent-security`。本文描述未提交的候选文件，不代表远端已经更新。

## 当前状态与结论

- GitHub 只读 API 当日返回仓库为 Public，远端 `main` 仍为 `e5fe54b6a3b579ccaed40d6f35f8367c028220c0`；`origin` 为 `https://github.com/qianmu233/agent-security-gateway.git`。
- 当前源码与文档中的硬编码 Windows 用户主目录路径已清除。历史执行记录使用明确标注的脱敏占位符，JDK 版本、运行 ID、结果和失败记录保留。
- 专用 Secret Scanner 在扫描范围内未发现凭据；这不是所有隐私内容均不存在的证明。
- 工程检查通过，但发布决定仍需用户接受旧历史的用户目录暴露。没有改写任何 Git 历史；新提交不会抹除旧提交中的路径。

## 路径修正与可执行性

`scripts/verify.ps1`、`acceptance.ps1`、`demo.ps1`、`verify-python-agent.ps1` 不再内置开发者 JDK 路径，使用 `JAVA_HOME`，允许 `-JavaHome` 显式覆盖。执行前必须配置真实 JDK 17；缺失或不符合要求则报错。

Python 测试夹具优先使用 `P3_JAVA_HOME`，否则使用 `JAVA_HOME`，检查 Java 可执行文件及 JDK 17 release 信息。批量驱动 `--offline` 的子进程环境白名单增加 `JAVA_HOME` 回退，仍不继承模型凭据。原 LangGraph、模型适配器、MCP 客户端、实验预算、收费门禁、运行锁及 Java 授权逻辑未修改。

`python-agent/README.md` 已补充最终 A/D/B/C 状态及最终审计链接，区分原有 51 项与新增 39 项；旧 A 准备阶段标记为历史记录，不再误读为当前 D 尚未执行。

## 专用扫描器与扫描范围

使用官方 [Gitleaks v8.30.1 Release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1) 的 Windows x64 版本，固定版本，不使用 Docker。ZIP 与校验清单均从官方 HTTPS Release 资源取得：

| 文件 | SHA-256 |
|---|---|
| `gitleaks_8.30.1_windows_x64.zip` | `d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e` |
| `gitleaks_8.30.1_checksums.txt` | `061476c21adaf5441516f96f185c1a4706a83cd6329b9b38762271b3d4a52fae` |
| 提取的 `gitleaks.exe` | `17157e2ee8b76fc8b1d8bee607a250e34b8a8023c8bc81822d4b5ee4d78fcb7c` |

下载内容与 GitHub Release API 的 asset digest 一致，ZIP 同时与官方校验清单条目一致；提取前检查压缩包路径。未做独立 Authenticode 或离线签名验证，不能把摘要一致性表述成完成了这类验证。工具及来源记录只放在忽略的 `.local/tools/gitleaks/8.30.1/`，不提交可执行文件。

扫描使用内置规则、`--redact=100`、`--ignore-gitleaks-allow`，未添加项目自定义豁免、baseline 或凭据环境变量。报告先在内存解析，仅保留规则、位置、提交等元数据，不保存或回显 `Secret`、`Match` 或扫描原始输出。

| 范围 | 实际结果 |
|---|---|
| `gitleaks git --log-opts=--all`：全部本地可达引用，共 9 个提交 | 退出码 0，0 条发现 |
| `gitleaks dir`：当前 71 个受跟踪文件加本文，共 72 个候选文件的独立快照 | 退出码 0，0 条发现 |

第二项覆盖工作区的路径修正及文档，而不仅是已提交 HEAD。未扫描或上传真实 `.env`、虚拟环境、运行数据库、原始运行目录及其他项目。没有发现需要分类处置的 scanner 命中；公开合成 fixture、环境变量名称和评测中的摘要指纹不作为真实凭据。静态扫描存在漏报可能，不能替代真实密钥轮换或人工隐私判断。

仓库没有 Git LFS 指针或需要另行上传的 LFS 资源；未跟踪模型权重或依赖二进制。`target/`、`.local/`、Python 虚拟环境、日志及 `.env` 类路径的忽略规则已逐项验证。`docs/evaluation/results.json` 是既有脱敏、合成场景的归档证据，和被忽略的运行 JSON 区分，不删除或重写。

## 仍存在的旧历史路径

用户目录路径模式检查与 Gitleaks 分开进行，因为目录隐私通常不是 secret 规则目标。当前 72 个候选文件为 0 条硬编码用户目录匹配，但历史仍存在：

- 远端旧 `main` 的可达历史：8 个不同 blob，共 13 处模式匹配，涉及 `README.md`、`docs/phase1-verification.md`、`scripts/acceptance.ps1`、`scripts/demo.ps1`、`scripts/verify.ps1`。其中部分 README 路径已在旧版本修改，仍可从提交历史查看。
- 本地发布候选 HEAD 的可达历史：18 个不同 blob，共 26 处模式匹配；额外涉及 `docs/python-agent-verification.md`、`python-agent/README.md`、`python-agent/tests/conftest.py`、`scripts/verify-python-agent.ps1`。

这里的计数按不同 blob 的匹配累计，不是泄露人数、独立凭据数或提交数。本报告不复制原用户名；内容主要暴露 Windows 账号目录、JDK 位置和本机开发布局，未观察到它们是认证秘密。

旧公开历史已存在的部分不能由普通前向提交消除；尚未推送的增强历史也会随增强分支发布。是否接受这部分公开可见性必须由用户确认。若不接受，应另行讨论独立净化发布方案；本轮没有重写、强推、删除分支或声称能够消除第三方缓存。

## 本次实际无费用验证

在项目 Python 3.12 虚拟环境及现有 JDK 17.0.16 下执行。Maven 使用已有 P3 缓存和项目公开 settings，离线 `-o`，不读取其他项目配置。

| 验证 | 本次结果 |
|---|---|
| 原有 Python Agent、模型/实验合约、协议、Java 跨进程测试 | 51 passed，0 failed，0 skipped（12.16 秒） |
| 批量驱动 `--offline`，含故障注入与独立 Java 进程 | 39 passed，0 failed，0 skipped（45.76 秒） |
| JDK 配置手工断言：缺失、JAVA_HOME 回退、无效显式覆盖、有效优先覆盖 | 4 项通过；不计入 pytest 数量 |
| `python -m ruff check python-agent` | 通过 |
| `python -m pip check` | 通过 |
| `scripts/acceptance.ps1`，未传 `-JavaHome`，验证 JAVA_HOME 默认值及 verify/demo 链路 | 退出码 0 |
| Maven verify / Failsafe | 20 项，失败 0、错误 0、跳过 0；BUILD SUCCESS |
| 原确定性安全评测 | COMPLETE，24/24 |
| 打包 JAR 本机 HTTP/MCP 演示 | 通过；测试 Harness 不在生产 JAR |
| 真实模型 HTTP | 0；未运行 A 或 D/B/C 真实实验 |

Python 51 项命令为 `python -B -m pytest -p no:cacheprovider tests/test_agent.py tests/test_model_adapter.py tests/test_experiment_a.py tests/test_protocol.py tests/test_java_integration.py -x -q`（在 `python-agent/` 下执行，另写忽略的 JUnit 报告）；39 项使用模块 README 的 `security_batch.py --offline`。Java 验收从根目录运行 `scripts/acceptance.ps1 -MavenRepository <P3_MAVEN_CACHE> -Port 18095`，当前进程设置 `JAVA_HOME` 与 Maven 离线公开 settings。尖括号是本报告的可移植占位符，不是原始路径或可直接复制的值。

本轮未弱化断言或删除测试，未观察到测试失败；首次工具下载的 curl 因本机 Schannel 错误失败，随后改用已有 Python HTTP 客户端、保持证书校验并核对官方摘要取得同一固定版本，不能把该下载失败写成测试失败或关闭 TLS 校验。

## 授权、来源与证据边界

- `src/main/`、Java 测试源码、原 Agent/模型/MCP 实现、依赖锁、Apache-2.0 `LICENSE` 与 `NOTICE` 均与复核基线一致。测试专用 Java Harness 不进入生产 JAR；没有新增授权工具或放松 RBAC、租户/资源及 Write Intent 校验。
- 上游认证、MCP 协议、LangGraph 和 LangChain 与本项目新增契约、工作流、可信绑定、收据检查、夹具的贡献边界保留；不声称从零实现这些依赖。
- A 真实合法读取 PASS；D 已暴露攻击备注但未提出危险写调用，目标授权分支 NOT_EXERCISED；B/C 真实到达 Java 并以 FORBIDDEN / INTENT_REQUIRED 拒绝，SERVER_DENIED / PASS。
- 原有 Fake 安全场景、MockTransport 合约与故障注入，不等同于真实模型防御率。真实实验单样本、未保存完整原始审计/网络报文、未评价自由草稿语义安全、无实际账单及生产 SLA 验收的限制不变。
- 本地真实 A、D/B/C 原件及一次性运行锁的 SHA-256 与修正前一致。它们不进入暂存区；归档摘要不能替代原始证据。

本轮 index 保持为空，main 与远端不变。建议在用户接受历史路径暴露并审阅本轮精确文件白名单后，再做本地修正提交；后续仅推送指定增强分支，不使用 `--all`、`--tags` 或强推，不自动合并 main。
