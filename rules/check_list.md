# 硬件审查检查清单（流程 → 负责人 → 规则编号）

> 由 rules/rules.json 自动渲染，**人工只维护 rules.json**，勿手改本文件。


## 流程总表

| 阶段 | 名称 | 负责人 | 门禁 | 规则束 | 批次暂停 |
|---|---|---|---|---|---|
| PH-0 | 输入准备 | human+flow | - | - |  |
| PH-1 | 手册检索(由BOM清单) | hw_search | G1 | G0-*、RG0-*、MI-* | ✔ |
| PH-2 | 数据预检(Wave0) | flow | G2 | W0-*、RW1-* |  |
| PH-3 | 网表解析(netlist_graph+子agent分发) | hw_prep | G3 | PREP-*、NG-* |  |
| PH-4 | 深度分析(芯片级并行<=5,只读netlist_graph+复核+回环) | hw_analyze | G4 | IC-*、PO-*、CN-*、DR-*、PE-*、LS-*、PB-*、IF-*、CL-* | ✔ |
| PH-5 | 报告合成(report.json+渲染.md) | hw_write | G5 | RF-*、CT-* |  |
| PH-6 | 审计复核 | hw_auditor | G6 | SA-*、Q-* | ✔ |
| PH-7 | 闭环交付 | flow | G7 | - |  |

## 门禁

- **G1**（manual_validate）@ PH-1：manual_index 覆盖全部U*；无手册者显式MISSING/UNVERIFIED；ic_type合法
- **G2**（bom_validate）@ PH-2：BOM解析无错误/条目非空/板号可识别（Wave0确定性预检）
- **G3**（netlist_validate）@ PH-3：netlist_graph完备性：dangling=0/uncovered=0/devices全覆盖/跨板连续
- **G4**（g2x_validate）@ PH-4：evidence契约/填充率>=80%/接口覆盖(确定性)+复核回环<=3轮(计数独立)
- **G5**（报告审核门）@ PH-5：确定性结构校验 + LLM内容审核(规则+要求+内容,有界2轮)
- **G6**（审计门）@ PH-6：SA-1..8自审 + 证据链三方对照(确定性+审计输出)
- **G7**（闭环交付门）@ PH-7：未决项清空/定版/final+渲染.md

## 规则编目（按规范 ID，由 raw 清册迭代生成，共 228 条）

| ID | 标题 | 源位置 | 行 |
|---|---|---|---|
| BLOCK-001 | ? 阻断条件 | raw_roles/hardware-reviewer.md::L300 | 300 |
| BLOCK-002 | ? 阻断条件 | raw_roles/hardware-reviewer.md::L325 | 325 |
| BLOCK-003 | ? 阻断条件 | raw_roles/hardware-reviewer.md::L378 | 378 |
| BLOCK-004 | ? 阻断条件 | raw_roles/hardware-reviewer.md::L406 | 406 |
| BLOCK-005 | ? 阻断条件 | raw_roles/hardware-reviewer.md::L432 | 432 |
| BLOCK-006 | ? 阻断条件 | raw_roles/hardware-reviewer.md::L466 | 466 |
| CL-001 | PH-4↔PH-3 回环 request/resolution 为 JSON、有 | v2_design::PH-4::G4 | 0 |
| CL-002 | PH-4 不得读原始 EDN/xlsx，仅读 netlist_graph.jso | v2_design::PH-4::G4 | 0 |
| CT-001 | §4 数据契约 | raw_roles/hardware-reviewer.md::L584 | 584 |
| CT-002 | §4.0 上下级数据交接总览 | raw_roles/hardware-reviewer.md::L588 | 588 |
| CT-003 | §4.0a 统一命名规范（合并自 pipeline_rules 规则7） | raw_roles/hardware-reviewer.md::L607 | 607 |
| CT-004 | 路径约定 | raw_roles/hardware-reviewer.md::L627 | 627 |
| CT-005 | §4.1 临时文件 Schema | raw_roles/hardware-reviewer.md::L642 | 642 |
| CT-006 | `g0_ic.msg` — IC 清单（G0 产出） | raw_roles/hardware-reviewer.md::L657 | 657 |
| CT-007 | `vccio.msg` — VCCIO 域→电压映射（引脚核对产出） | raw_roles/hardware-reviewer.md::L674 | 674 |
| CT-008 | `power.msg` — 供电拓扑（电源检查产出） | raw_roles/hardware-reviewer.md::L694 | 694 |
| CT-009 | §4.2 Evidence 统一格式 | raw_roles/hardware-reviewer.md::L724 | 724 |
| CT-010 | §4.3 Evidence 摘要格式 | raw_roles/hardware-reviewer.md::L747 | 747 |
| CT-011 | §4.4 Gate 结果统一格式 | raw_roles/hardware-reviewer.md::L804 | 804 |
| CT-012 | §4.5 JSON 通用顶层字段 | raw_roles/hardware-reviewer.md::L822 | 822 |
| CT-013 | §4.6 项目无关 Schema 原则 | raw_roles/hardware-reviewer.md::L842 | 842 |
| CT-014 | §4.7 稳定编号索引 | raw_roles/hardware-reviewer.md::L849 | 849 |
| DOC-001 | 硬件原理图设计验证专家 — Agent 规则 (v4.0) | raw_roles/hardware-reviewer.md::L1 | 1 |
| DP-001 | §5.1 委派 Prompt 模板 | raw_roles/hardware-reviewer.md::L882 | 882 |
| DP-002 | §5.2 并行任务分解约束（P1-P7） | raw_roles/hardware-reviewer.md::L920 | 920 |
| DP-003 | §5.3 CLI 基础设施约束 | raw_roles/hardware-reviewer.md::L972 | 972 |
| GATE-001 | §2.1 全流程概览 | raw_roles/hardware-reviewer.md::L222 | 222 |
| GATE-002 | §2.2 Step 0a — 人工配置门禁 | raw_roles/hardware-reviewer.md::L292 | 292 |
| GATE-003 | ?? 适用规则 | raw_roles/hardware-reviewer.md::L308 | 308 |
| GATE-004 | §2.3 G0 — 手册搜索 | raw_roles/hardware-reviewer.md::L317 | 317 |
| GATE-005 | ?? 适用规则 | raw_roles/hardware-reviewer.md::L334 | 334 |
| GATE-006 | §2.4 G0.5 — 手册缺失确认 | raw_roles/hardware-reviewer.md::L344 | 344 |
| GATE-007 | ? 无缺失自动 PASS | raw_roles/hardware-reviewer.md::L352 | 352 |
| GATE-008 | ??? Question 弹窗配置 | raw_roles/hardware-reviewer.md::L367 | 367 |
| GATE-009 | ?? 适用规则 | raw_roles/hardware-reviewer.md::L387 | 387 |
| GATE-010 | §2.5 Wave 1 — hw_prep 网表解析 | raw_roles/hardware-reviewer.md::L398 | 398 |
| GATE-011 | ?? 适用规则 | raw_roles/hardware-reviewer.md::L414 | 414 |
| GATE-012 | §2.6 Wave 2 — hw_analyze 深度分析 | raw_roles/hardware-reviewer.md::L424 | 424 |
| GATE-013 | ?? 适用规则 | raw_roles/hardware-reviewer.md::L443 | 443 |
| GATE-014 | §2.7 Wave FINAL — 报告 + 审计 + G6 闭环 | raw_roles/hardware-reviewer.md::L458 | 458 |
| GATE-015 | ?? 适用规则 | raw_roles/hardware-reviewer.md::L477 | 477 |
| IC-001 | 引脚核对规则 | raw_rules/引脚核对规则.md::L1 | 1 |
| IC-002 | 定位：引脚检查的综述文件 | raw_rules/引脚核对规则.md::L7 | 7 |
| IC-003 | 核心原则 | raw_rules/引脚核对规则.md::L22 | 22 |
| IC-004 | 正确流程 | raw_rules/引脚核对规则.md::L30 | 30 |
| IC-005 | 第一步：追踪物理连接 | raw_rules/引脚核对规则.md::L32 | 32 |
| IC-006 | 连接器引脚输出格式 | raw_rules/引脚核对规则.md::L68 | 68 |
| IC-007 | 第二步：确认芯片引脚功能 | raw_rules/引脚核对规则.md::L87 | 87 |
| IC-008 | 第三步：确认 VCCIO 域电压 | raw_rules/引脚核对规则.md::L101 | 101 |
| IC-009 | 第四步：反向验证标签 | raw_rules/引脚核对规则.md::L112 | 112 |
| IC-010 | 禁止事项 | raw_rules/引脚核对规则.md::L125 | 125 |
| IC-011 | 实战案例 | raw_rules/引脚核对规则.md::L142 | 142 |
| IC-012 | 案例：接口 "GPIO1-3V3" 的核实 | raw_rules/引脚核对规则.md::L146 | 146 |
| IC-013 | 案例：J3.9 "GPIO0-1V8" 的核实 | raw_rules/引脚核对规则.md::L168 | 168 |
| IC-014 | 案例：DVP VI0_DATA0/1 CIF 编号互换 | raw_rules/引脚核对规则.md::L181 | 181 |
| IC-015 | 精确值校验规则（No-Shortcut Rule） | raw_rules/引脚核对规则.md::L201 | 201 |
| IC-016 | 问题根源 | raw_rules/引脚核对规则.md::L203 | 203 |
| IC-017 | ❌ 浅层检查 — 仅验证类别存在 | raw_rules/引脚核对规则.md::L208 | 208 |
| IC-018 | 遗漏了: CIF_D1 vs 标号 DATA0 不一致 | raw_rules/引脚核对规则.md::L210 | 210 |
| IC-019 | ✅ 深层检查 — 验证编号精确匹配 | raw_rules/引脚核对规则.md::L212 | 212 |
| IC-020 | 适用场景 | raw_rules/引脚核对规则.md::L218 | 218 |
| IC-021 | 禁止事项（补充） | raw_rules/引脚核对规则.md::L232 | 232 |
| IC-022 | 网表解析技巧 | raw_rules/引脚核对规则.md::L242 | 242 |
| IC-023 | EDIF 格式 portRef 提取 | raw_rules/引脚核对规则.md::L244 | 244 |
| IC-024 | 提取网络中所有连接 | raw_rules/引脚核对规则.md::L247 | 247 |
| IC-025 | GPIO 域后缀与 VCCIO 映射 | raw_rules/引脚核对规则.md::L258 | 258 |
| IC-026 | 自动化脚本自我审查规则（Script Self-Audit） | raw_rules/引脚核对规则.md::L274 | 274 |
| IC-027 | 问题根源 | raw_rules/引脚核对规则.md::L276 | 276 |
| IC-028 | 案例 1：`net_body` 行数截断 → I2C2 上拉漏检 | raw_rules/引脚核对规则.md::L280 | 280 |
| IC-029 | ❌ 有截断风险的写法 | raw_rules/引脚核对规则.md::L283 | 283 |
| IC-030 | 网络较长 → U1000 portRef 在第 55 行 → 被截断 → has | raw_rules/引脚核对规则.md::L287 | 287 |
| IC-031 | → 误判为 "no U1000, assumed external" → 跳过上 | raw_rules/引脚核对规则.md::L288 | 288 |
| IC-032 | ✅ 正确的写法 — 扫描到网络结束符 | raw_rules/引脚核对规则.md::L292 | 292 |
| IC-033 | 案例 2：仅验证功能类别 → DVP D0/D1 编号漏检 | raw_rules/引脚核对规则.md::L304 | 304 |
| IC-034 | ❌ 浅层检查 | raw_rules/引脚核对规则.md::L307 | 307 |
| IC-035 | ✅ 深层检查 | raw_rules/引脚核对规则.md::L313 | 313 |
| IC-036 | 案例 3：只搜 portRef 已连接引脚 → U3200 ZQ 悬空漏检 | raw_rules/引脚核对规则.md::L319 | 319 |
| IC-037 | ❌ 只搜 portRef（网络连接的引脚） | raw_rules/引脚核对规则.md::L322 | 322 |
| IC-038 | → 结果: VSS/ZQ_U(DDP) 等已连接引脚 | raw_rules/引脚核对规则.md::L324 | 324 |
| IC-039 | → ZQ 引脚悬空 → 没有 portRef → 永远搜不到！ | raw_rules/引脚核对规则.md::L325 | 325 |
| IC-040 | → 搜到 VSS/ZQ_U 含 "ZQ" 子串 → 误判为 ZQ → 停止 | raw_rules/引脚核对规则.md::L326 | 326 |
| IC-041 | ✅ 对比 portInstance（符号定义） vs portRef（网络连接） | raw_rules/引脚核对规则.md::L330 | 330 |
| IC-042 | 1. 从 instance 定义提取全部引脚 | raw_rules/引脚核对规则.md::L331 | 331 |
| IC-043 | → ['DML_n', 'DQSL_P', ..., 'ZQ', ..., 'V | raw_rules/引脚核对规则.md::L333 | 333 |
| IC-044 | 2. 从网络提取已连接的引脚 | raw_rules/引脚核对规则.md::L334 | 334 |
| IC-045 | → ['DML_n/DBIL_n', ..., 'VSS/ZQ_U(DDP)'] | raw_rules/引脚核对规则.md::L336 | 336 |
| IC-046 | 3. 对比 → ZQ 在 inst_pins 但不在 wired_pins →  | raw_rules/引脚核对规则.md::L337 | 337 |
| IC-047 | 悬空引脚检测规则 | raw_rules/引脚核对规则.md::L341 | 341 |
| IC-048 | 芯片范围规则（新增，不可跳过） | raw_rules/引脚核对规则.md::L345 | 345 |
| IC-049 | 实战教训 | raw_rules/引脚核对规则.md::L373 | 373 |
| IC-050 | 原规则（保留，按引脚功能分类） | raw_rules/引脚核对规则.md::L379 | 379 |
| IC-051 | 脚本自审清单 | raw_rules/引脚核对规则.md::L392 | 392 |
| IC-052 | 错误处理规则 | raw_rules/引脚核对规则.md::L406 | 406 |
| IC-053 | ❌ 沉默跳过 | raw_rules/引脚核对规则.md::L409 | 409 |
| IC-054 | ✅ 显式上报 | raw_rules/引脚核对规则.md::L413 | 413 |
| IC-055 | 验证策略层级 | raw_rules/引脚核对规则.md::L419 | 419 |
| IC-056 | 检查员自审清单（Inspector Self-Audit） | raw_rules/引脚核对规则.md::L432 | 432 |
| IC-057 | 一、枚举先行原则（Enumerate Before Evaluate） | raw_rules/引脚核对规则.md::L436 | 436 |
| IC-058 | 二、逐 net body 硬读（Hard-Read Net Body） | raw_rules/引脚核对规则.md::L459 | 459 |
| IC-059 | 三、自审门禁（Go/No-Go Gates） | raw_rules/引脚核对规则.md::L469 | 469 |
| IC-060 | 四、经典漏检模式速查 | raw_rules/引脚核对规则.md::L475 | 475 |
| IC-061 | 四、经典漏检模式速查 | raw_rules/引脚核对规则.md::L477 | 477 |
| IC-062 | 五、纠正措施 | raw_rules/引脚核对规则.md::L492 | 492 |
| IC-063 | 输出要求：VCCIO 域→电压映射表（数据交接） | raw_rules/引脚核对规则.md::L503 | 503 |
| IC-064 | JSON Schema | raw_rules/引脚核对规则.md::L511 | 511 |
| IC-065 | 输出步骤 | raw_rules/引脚核对规则.md::L551 | 551 |
| IC-066 | 验证 | raw_rules/引脚核对规则.md::L559 | 559 |
| IC-067 | 引脚复用关系检查规则 | raw_rules/引脚复用关系检查规则.md::L1 | 1 |
| IC-068 | 核心原则 | raw_rules/引脚复用关系检查规则.md::L18 | 18 |
| IC-069 | 数据来源 | raw_rules/引脚复用关系检查规则.md::L26 | 26 |
| IC-070 | GPIO 标识解读 | raw_rules/引脚复用关系检查规则.md::L44 | 44 |
| IC-071 | IO 域后缀与电压 | raw_rules/引脚复用关系检查规则.md::L56 | 56 |
| IC-072 | 检查流程 | raw_rules/引脚复用关系检查规则.md::L62 | 62 |
| IC-073 | 第一步：提取端口复用表 | raw_rules/引脚复用关系检查规则.md::L64 | 64 |
| IC-074 | 第二步：逐接口信号核对 | raw_rules/引脚复用关系检查规则.md::L82 | 82 |
| IC-075 | 第三步：检查三种冲突 | raw_rules/引脚复用关系检查规则.md::L93 | 93 |
| IC-076 | 冲突类型一：专用功能与 GPIO 互斥 | raw_rules/引脚复用关系检查规则.md::L95 | 95 |
| IC-077 | 冲突类型二：同引脚多功能 | raw_rules/引脚复用关系检查规则.md::L106 | 106 |
| IC-078 | 冲突类型三：同功能跨域 Mux | raw_rules/引脚复用关系检查规则.md::L117 | 117 |
| IC-079 | 接口引脚复用关系速查（模板） | raw_rules/引脚复用关系检查规则.md::L132 | 132 |
| IC-080 | J3（示例：DF56C-26S 调试接口） | raw_rules/引脚复用关系检查规则.md::L136 | 136 |
| IC-081 | J5（DF56C-26S DVP 摄像头接口） | raw_rules/引脚复用关系检查规则.md::L149 | 149 |
| IC-082 | J8（USL00-30L RGMII 以太网） | raw_rules/引脚复用关系检查规则.md::L160 | 160 |
| IC-083 | 最终交付检查清单 | raw_rules/引脚复用关系检查规则.md::L170 | 170 |
| LEARN-001 | G6 后：自学习回写 | raw_roles/hardware-reviewer.md::L494 | 494 |
| LEARN-002 | 会话结束：升级建议询问 | raw_roles/hardware-reviewer.md::L523 | 523 |
| LEARN-003 | ? SUG-XXX: {条目标题} | raw_roles/hardware-reviewer.md::L535 | 535 |
| LEARN-004 | G6 通过标准 | raw_roles/hardware-reviewer.md::L558 | 558 |
| LEARN-005 | G6 自审清单 | raw_roles/hardware-reviewer.md::L571 | 571 |
| LS-001 | 引脚电平检查方案 | raw_rules/引脚电平检查方案.md::L1 | 1 |
| LS-002 | 一、核心流程 | raw_rules/引脚电平检查方案.md::L16 | 16 |
| LS-003 | 二、Step 1 — 确定信号路径 | raw_rules/引脚电平检查方案.md::L32 | 32 |
| LS-004 | 三、Step 2 — 查芯片 VCCIO 域 | raw_rules/引脚电平检查方案.md::L45 | 45 |
| LS-005 | 从芯片引脚名提取域后缀 | raw_rules/引脚电平检查方案.md::L47 | 47 |
| LS-006 | 四、Step 3 — 追踪供电网络 | raw_rules/引脚电平检查方案.md::L61 | 61 |
| LS-007 | EDN 查询方法 | raw_rules/引脚电平检查方案.md::L72 | 72 |
| LS-008 | 伪代码 | raw_rules/引脚电平检查方案.md::L75 | 75 |
| LS-009 | 五、Step 4 — 检查中间芯片 | raw_rules/引脚电平检查方案.md::L89 | 89 |
| LS-010 | 5.1 确认路径上的所有中间芯片 | raw_rules/引脚电平检查方案.md::L93 | 93 |
| LS-011 | 追踪时发现信号经过了芯片 Ux 而非直连 | raw_rules/引脚电平检查方案.md::L106 | 106 |
| LS-012 | 5.2 对每颗中间芯片，要求提供数据手册 | raw_rules/引脚电平检查方案.md::L112 | 112 |
| LS-013 | 5.3 核对手册与实际电路 | raw_rules/引脚电平检查方案.md::L126 | 126 |
| LS-014 | 5.4 核对信号方向与芯片能力 | raw_rules/引脚电平检查方案.md::L149 | 149 |
| LS-015 | 5.5 核对 Footprint 一致性 | raw_rules/引脚电平检查方案.md::L158 | 158 |
| LS-016 | 5.6 信号直连（无中间芯片） | raw_rules/引脚电平检查方案.md::L167 | 167 |
| LS-017 | 六、Step 5 — 对比标注 vs 实际 | raw_rules/引脚电平检查方案.md::L178 | 178 |
| LS-018 | 七、完整检查清单 | raw_rules/引脚电平检查方案.md::L190 | 190 |
| LS-019 | 对每个信号执行 | raw_rules/引脚电平检查方案.md::L192 | 192 |
| LS-020 | 高风险信号优先检查 | raw_rules/引脚电平检查方案.md::L203 | 203 |
| LS-021 | 八、批量检查方案（可用脚本实现） | raw_rules/引脚电平检查方案.md::L214 | 214 |
| MI-001 | manual_index 覆盖 BOM 全部 U* 位号，无手册者须显式 MIS | v2_design::PH-1::G1 | 0 |
| MI-002 | ic_type ∈ {SINK,PASS_THRU,POWER_SRC,UNVE | v2_design::PH-1::G1 | 0 |
| MI-003 | 手册检索链：refbook 本地优先 → 未中 Tavily≥2 策略 → 合计 | v2_design::PH-1::G1 | 0 |
| NG-001 | netlist_graph：devices 覆盖全部 (板,位号)，pins 为 | v2_design::PH-3::G3 | 0 |
| NG-002 | links 覆盖每个非串联器件引脚（uncovered=0）；纯芯片间网 sid | v2_design::PH-3::G3 | 0 |
| NG-003 | 跨板仅经 cross_board_links（连接器按脚号一一配对，禁 GND  | v2_design::PH-3::G3 | 0 |
| NG-004 | 0Ω 两端归 alias_group；差分对 _P/_N 归 diff_pair | v2_design::PH-3::G3 | 0 |
| NG-005 | dangling_joins=0（每个 join 的位号存在于 devices） | v2_design::PH-3::G3 | 0 |
| PART-001 | §0 快速导航 (人类阅读) | raw_roles/hardware-reviewer.md::L3 | 3 |
| PART-002 | §1 角色定义与架构 | raw_roles/hardware-reviewer.md::L14 | 14 |
| PART-003 | §2 审核流程 | raw_roles/hardware-reviewer.md::L218 | 218 |
| PART-004 | §5 委派规范 | raw_roles/hardware-reviewer.md::L876 | 876 |
| PART-005 | §6 交付与质量 | raw_roles/hardware-reviewer.md::L986 | 986 |
| PB-001 | 第二部分：动态电路与隐性风险检查 (Dynamic & Integrity Ch | raw_rules/接口电路检查规则.md::L26 | 26 |
| PB-002 | 2.1 电平转换芯片（Level Shifter）判定树 | raw_rules/接口电路检查规则.md::L28 | 28 |
| PB-003 | 2.2 默认电平与单点多驱检查 | raw_rules/接口电路检查规则.md::L40 | 40 |
| PB-004 | 2.3 电源域耦合与上电时序 | raw_rules/接口电路检查规则.md::L46 | 46 |
| PB-005 | 第三部分：常见外设标准电路检查规则 (Peripheral Standard R | raw_rules/接口电路检查规则.md::L50 | 50 |
| PB-006 | 3.1 低速串行总线 (I2C / UART) | raw_rules/接口电路检查规则.md::L54 | 54 |
| PB-007 | 3.2 工业接口转换 (RS232 / RS485 / RS422) | raw_rules/接口电路检查规则.md::L76 | 76 |
| PB-008 | 3.3 高速内存总线 (DDR3 / DDR4 / LPDDR4 / LPDDR | raw_rules/接口电路检查规则.md::L98 | 98 |
| PB-009 | 3.4 视频与高速接口 (MIPI / DVP) | raw_rules/接口电路检查规则.md::L146 | 146 |
| PB-010 | 第四部分：最终交付与异常判定逻辑输出 | raw_rules/接口电路检查规则.md::L164 | 164 |
| PO-001 | 电源检查规则 | raw_rules/电源检查.md::L1 | 1 |
| PO-002 | 一、上电时序检查 | raw_rules/电源检查.md::L9 | 9 |
| PO-003 | 1.1 时序约束来源 | raw_rules/电源检查.md::L13 | 13 |
| PO-004 | 1.2 多轨启动顺序验证 | raw_rules/电源检查.md::L25 | 25 |
| PO-005 | 1.3 tON / tOFF / tRAMP 参数核对 | raw_rules/电源检查.md::L40 | 40 |
| PO-006 | 二、电源启动流程 | raw_rules/电源检查.md::L49 | 49 |
| PO-007 | 2.1 EN 链追踪 | raw_rules/电源检查.md::L51 | 51 |
| PO-008 | 2.2 PG 级联验证 | raw_rules/电源检查.md::L64 | 64 |
| PO-009 | 2.3 保护机制确认 | raw_rules/电源检查.md::L77 | 77 |
| PO-010 | 三、PMIC 配置验证 | raw_rules/电源检查.md::L87 | 87 |
| PO-011 | 3.1 分压电阻计算 | raw_rules/电源检查.md::L89 | 89 |
| PO-012 | 3.2 FB 网络一致性 | raw_rules/电源检查.md::L107 | 107 |
| PO-013 | 3.3 可编程寄存器默认值 | raw_rules/电源检查.md::L113 | 113 |
| PO-014 | 四、上下拉模型 | raw_rules/电源检查.md::L121 | 121 |
| PO-015 | 4.1 EN 引脚默认态与外部配合 | raw_rules/电源检查.md::L123 | 123 |
| PO-016 | 4.2 开漏输出的上拉要求 | raw_rules/电源检查.md::L135 | 135 |
| PO-017 | 4.3 MODE/SYNC 配置引脚 | raw_rules/电源检查.md::L142 | 142 |
| PO-018 | 五、电容配置 | raw_rules/电源检查.md::L150 | 150 |
| PO-019 | 5.1 输入/输出电容手册要求 | raw_rules/电源检查.md::L152 | 152 |
| PO-020 | 5.2 去耦密度检查 | raw_rules/电源检查.md::L163 | 163 |
| PO-021 | 5.3 耐压与介质类型 | raw_rules/电源检查.md::L172 | 172 |
| PO-022 | 六、电阻配置 | raw_rules/电源检查.md::L179 | 179 |
| PO-023 | 6.1 限流/频率设定电阻 | raw_rules/电源检查.md::L181 | 181 |
| PO-024 | 6.2 电流采样电阻（Shunt） | raw_rules/电源检查.md::L189 | 189 |
| PO-025 | 七、交付检查清单 | raw_rules/电源检查.md::L200 | 200 |
| Q-001 | §6.1 交付质量标准（Q1-Q9） | raw_roles/hardware-reviewer.md::L990 | 990 |
| Q-002 | §6.3 复查不合格闭环 | raw_roles/hardware-reviewer.md::L1023 | 1023 |
| Q-003 | §6.4 缺项闭环 | raw_roles/hardware-reviewer.md::L1060 | 1060 |
| ROLE-001 | 1.1 角色定义 | raw_roles/hardware-reviewer.md::L16 | 16 |
| ROLE-002 | 1.2 Purpose | raw_roles/hardware-reviewer.md::L21 | 21 |
| ROLE-003 | 1.2 多 Agent 委派架构 | raw_roles/hardware-reviewer.md::L24 | 24 |
| ROLE-004 | 1.3 hardware_review — 流程编排器（裁判） | raw_roles/hardware-reviewer.md::L34 | 34 |
| ROLE-005 | 1.4 hw_search — 手册检索（运动员） | raw_roles/hardware-reviewer.md::L77 | 77 |
| ROLE-006 | 1.5 hw_prep — 网表解析（运动员） | raw_roles/hardware-reviewer.md::L100 | 100 |
| ROLE-007 | 1.6 hw_analyze — 深度分析（运动员） | raw_roles/hardware-reviewer.md::L122 | 122 |
| ROLE-008 | 1.7 hw_auditor — 复核审计（运动员） | raw_roles/hardware-reviewer.md::L158 | 158 |
| ROLE-009 | 1.8 hw_write — 报告编写（运动员） | raw_roles/hardware-reviewer.md::L180 | 180 |
| ROLE-010 | 1.9 全流程 Gate 顺序 | raw_roles/hardware-reviewer.md::L203 | 203 |
| SA-001 | §6.2 Self-Audit Gates（G0-G7） | raw_roles/hardware-reviewer.md::L1005 | 1005 |
| SYN-001 | 证据文件 JSON Schema 规范 | raw_rules/证据文件Schema规范.md::L1 | 1 |
| SYN-002 | 一、通用要求 | raw_rules/证据文件Schema规范.md::L8 | 8 |
| SYN-003 | 1.1 根节点元信息 | raw_rules/证据文件Schema规范.md::L10 | 10 |
| SYN-004 | 二、任务输出 Schema | raw_rules/证据文件Schema规范.md::L36 | 36 |
| SYN-005 | T1: IC 清单 — `v10_ic_inventory.csv` | raw_rules/证据文件Schema规范.md::L38 | 38 |
| SYN-006 | T1 附加: RK3576 参数 — `v10_rk3576_params.js | raw_rules/证据文件Schema规范.md::L55 | 55 |
| SYN-007 | T4: VCCIO 域映射 — `v10_vccio_map.json` | raw_rules/证据文件Schema规范.md::L100 | 100 |
| SYN-008 | T5: 供电网络 — `v10_power_rails.json` | raw_rules/证据文件Schema规范.md::L149 | 149 |
| SYN-009 | T6: 连接器 — `v10_connector_pinout.json` | raw_rules/证据文件Schema规范.md::L179 | 179 |
| SYN-010 | T7: DDR — `v10_ddr_check.json` | raw_rules/证据文件Schema规范.md::L222 | 222 |
| SYN-011 | T8: 外设 — `v10_peripheral_check.json` | raw_rules/证据文件Schema规范.md::L299 | 299 |
| SYN-012 | T9: 悬空引脚 — `v10_floating_pins.json` | raw_rules/证据文件Schema规范.md::L359 | 359 |
| SYN-013 | T10: 芯片专属 — `v10_rk3576_specific.json` | raw_rules/证据文件Schema规范.md::L398 | 398 |
| SYN-014 | 三、枚举值定义 | raw_rules/证据文件Schema规范.md::L432 | 432 |
| SYN-015 | 四、F2 报告代理的使用规范 | raw_rules/证据文件Schema规范.md::L444 | 444 |
| SYN-016 | 五、版本历史 | raw_rules/证据文件Schema规范.md::L456 | 456 |