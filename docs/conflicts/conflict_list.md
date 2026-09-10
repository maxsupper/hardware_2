# raw 规则解析 冲突/决策清单

> 阶段1a 交付物 | 日期: 2026-09-10 | raw 只读，本清单基于解析结果
> 状态: A 部分=对话中已确认；B 部分=本次扫描新发现，**待用户逐条确认**

## A. 已确认决策（记录留痕，来源标注 raw 位置）

| ID | 来源(raw) | 现象/冲突 | 决策(已确认) |
|---|---|---|---|
| A-01 | hardware-reviewer.md L21/L24 | §1.2 重复（"Purpose" 与 "多 Agent 委派架构"） | 规范化为 1.2/1.3，后续章节号顺延 |
| A-02 | hardware-reviewer.md 各 agent 表 | 模型名 deepseek-v4-pro/flash | 全流程统一 spark-dsv4/deepseek-v4-flash-0731，可配置升级 pro |
| A-03 | hardware-reviewer.md §5.3 | "纯标准库、禁止 pydantic/jsonschema/typer" | **约束取消**（可用 pydantic/第三方） |
| A-04 | hardware-reviewer.md §2.3 Block#4 / RG0-02 | "≥3 种检索来源 websearch→Context7→librarian" | Context7 废弃(软件文档API不适用硬件)；librarian→refbook 本地检索；改为"本地+ Tavily≥2 策略，合计≥3 次有效尝试" |
| A-05 | hardware-reviewer.md §1.2/P1-P6 | 裁判=LLM agent | 裁判改为 **Flow 确定性状态机**；运动员=LLM agent |
| A-06 | hardware-reviewer.md §4.3 | 报告输出 .md | 报告 = **report.json + 自动渲染 .md** |
| A-07 | hardware-reviewer.md G0-G7 审计门禁 vs G0 手册搜索阶段 | G0 双重含义混用 | 重编号：阶段 PH-0..7；门禁 G1..G7；审计标准 **SA-1..8**(原 G0-G7) |
| A-08 | 电源检查/接口电路 各"G0 前置依赖" | 手册缺失判定 | 统一：缺手册→UNVERIFIED；判不出→UNVERIFIED+补测建议 |

## B. 本次解析新发现的冲突候选（**待确认**）

| ID | 来源(raw) | 现象 | 建议处理 | 待确认 |
|---|---|---|---|---|
| B-01 | hardware-reviewer.md §4.0/§4.0a | 运行时目录约定 `.sisyphus/runs/`、`.sisyphus/temp/`、`{REFBOOK_DIR}` | 统一映射到本项目路径：run→`storge/project/<产品>/`、temp→`<run>/.run/`、REFBOOK→`storge/refbook`、datasheet→`storge/datasheet`；rules.json 里做**路径域映射表** | 同意？ |
| B-02 | 接口电路检查规则.md | 该文件**无 Markdown 标题**，用"第X部分 / 2.1 / 2.2"编号 | 解析时按内容自定义段落切分；编号规范时按其子句重新编号（IC-* 等） | 同意？ |
| B-03 | hardware-reviewer.md §4.7 vs 全文 | §4.7 定义了 PREP-/G2X-/CONN-/IF-/PO-/CN-/DR-/PE-/LS-/PB-/IC-/MISS- 前缀，但全文实际使用 Q/R/K-T/RW/RG/RF 混用、且 Q9/R11 等与示例位号撞名 | **建"编号字典"**：统一为规则ID(§4.7 前缀) + 条件ID(原 R/Q/K/RW/RG/RF 归入) + 门禁ID(G/SA)，消除撞名，反向验证兜底 | 同意？ |
| B-04 | hardware-reviewer.md §4.3 漏读兜底 | 提到"项目根 上电时序图.json"，但全文无其 schema 定义 | 归为**待补定义项**：一期先用 evidence 内 power_domain_map/sequence_verification 承载；上电时序图.json 的具体 schema 到期中确认 | 同意？ |
| B-05 | hardware-reviewer.md §4.0a | `gates/gate{N}.json`、`evidence/wave{N}_{线}.json` 命名 | 对齐我们 PH/G 命名：gates/G1..G7_{name}.json、evidence/PH4_{ic}_{线}*.json；命名由 rules.json 的 output_scheme 统一映射 | 同意？ |
| B-06 | hardware-reviewer.md §6.3 | 修复循环"同类型≤3次，第3次强制通过" | 与 G5"LLM 内容审核有界2轮"并存；确定：**实施修复循环≤3(不变)，报告内容审核2轮(新)**，两者分级不混 | 同意？ |
| B-07 | 多个规则文件头部 | 各文件"启动前必须先读取 .sisyphus/temp/*.msg" | 保留语义，路径按 B-01 映射；`*.msg` 临时文件在 G6 后清理 | 同意？ |

---

## 确认记录（2026-09-10 用户确认）

| ID | 结论 |
|---|---|
| B-01 | ✅ 按建议：路径域映射表 |
| B-02 | ✅ 按建议：接口电路规则按内容切分重编号 |
| B-03 | ✅ 按建议：统一编号字典 |
| B-04 | ✅ 按建议 方案(a) + 电源树设计：产物化 power_tree.json；大电源网络多 agent 拆分→确定性合并→反向验证→LLM 合理性检测 |
| B-05 | ✅ 按建议：对齐 PH/G 命名 |
| B-06 | ✅ 按建议 方案(a)：分级不混（G5 内容审核 2 轮 与 审计修复 ≤3 轮 独立计数、闸依次开） |
| B-07 | ✅ 按建议：temp/.msg 路径映射，G6 后清理 |

B 部分全部确认 → 进入 1b 编号规范化 + 反向验证。
