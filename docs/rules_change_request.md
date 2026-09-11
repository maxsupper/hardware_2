# rules.json 变更申请单（待用户批准）

> 依据：2026-09-11 已确认的 v2 修订（阶段换位 / netlist_graph / 回环 / 门禁重排）。
> 原则：**不改任何既有 218 条规则的规则内容**（检查条文的"事实源"不动）；仅调整
> `process`/`gates`/`agents` 三项**结构性元数据**，并**新增**新产物所需规则条目。

## A. 结构性元数据（建议必改，否则 rules.json 与实际流程脱节）

### A1. process 阶段换位（8 阶段 → 仍 8 阶段，顺序变化）
| 位置 | 现在 | 建议改为 | 角色 | 门禁 |
|---|---|---|---|---|
| PH-1 | 网表解析(多EDN全局合并+信号链) | **手册检索（由 BOM 清单）** | hw_search | **G1** |
| PH-2 | 手册检索 | **数据预检(Wave0)** | flow | **G2** |
| PH-3 | 数据预检(Wave0) | **网表解析(netlist_graph+子agent分发)** | hw_prep | **G3** |
| PH-4 | 深度分析 | 深度分析（不变，新增"复核 tracer+回环"） | hw_analyze | G4 |
- 建议 rules 归属随之搬移：PH-1→`["G0-*","RG0-*","MI-*"]`；PH-2→`["W0-*","RW1-*"]`；PH-3→`["PREP-*","NG-*"]`。

### A2. gates 语义重排（编号按阶段序，内容随阶段走）
| 门 | 现在 | 建议改为 |
|---|---|---|
| G1 | prep_validate (after PH-1) | **manual_validate**（每颗 IC 有手册或显式 UNVERIFIED）after PH-1 |
| G2 | 手册缺失确认 | **数据完整性 Wave0** after PH-2 |
| G3 | 数据完整性 | **netlist_validate**（netlist_graph 完备性）after PH-3 |
| G4..G7 | 不变 | 不变（analysis/report/audit/delivery） |

### A3. agents 职责/工具更新
- `hw_search`：note 改为「PH-1 由 BOM 清单取唯一 IC 型号检索，产 manual_index.json + ic_type 判定」；tools 增 `manual_index`。
- `hw_prep`：note 改为「PH-3 网表解析 + netlist_graph 组装 + 按接插件子 agent 分发合并」；tools 增 `netlist_graph`；bootstrap 增 `NG-*`。
- `hw_analyze`：note 增「只读 netlist_graph.json；兼做 tracer 判定复核；不清晰走回环(re-request PH-3)」；tools 增 `netlist_slice`（待建）。
- `hw_review`(flow)：note 增「回环轮次≤3，计数独立于 G5/G6」。

## B. 新增规则条目（新产物所必需；建议新增 ID 段，不动既有编号）

| 建议 ID | 阶段 | 门 | 规则要点 |
|---|---|---|---|
| `MI-001` | PH-1 | G1 | manual_index.json 必须覆盖 BOM 全部 U* 位号；每项含 manual_path 或 status∈{TRULY_MISSING,UNVERIFIED} |
| `MI-002` | PH-1 | G1 | ic_type 必须∈{SINK,PASS_THRU,POWER_SRC,UNVERIFIED}；PASS_THRU 必须有 channels |
| `NG-001` | PH-3 | G3 | netlist_graph：devices 覆盖全部 (板,位号)；pins 为**全量**引脚 |
| `NG-002` | PH-3 | G3 | links 必须覆盖每个非串联器件引脚（uncovered=0）；纯芯片间网 side=bi |
| `NG-003` | PH-3 | G3 | 跨板仅经 cross_board_links（连接器配对，脚号一一对应，禁 GND 塌缩） |
| `NG-004` | PH-3 | G3 | 0Ω 两端归 alias_group；差分对（_P/_N）归 diff_pairs；电源环路 side=pwr |
| `NG-005` | PH-3 | G3 | dangling_joins=0（每个 join 的位号存在于 devices） |
| `CL-001` | PH-4 | G4 | 回环 request/resolution 为 JSON、有界≤3 轮、计数独立；3 轮未决→link 标 UNVERIFIED 进待核清单 |
| `CL-002` | PH-4 | G4 | PH-4 不得读原始 EDN/xlsx；仅读 netlist_graph.json（除走回环） |

## C. 建议但非必须
- `PREP-*` 中"跨板网名合并"相关表述（若有）建议标注**deprecated**，以 NG-003 为准。
- 门禁文件命名保持 `gates/G<n>.json` 不变（编号语义改变已在 A2 说明）。

## D. 影响评估
- 不改规则内容 → 既有 218 条校验语义、编号、`_audit` 溯源**不变**，反向校验（遗留=0/错位=0）不受影响。
- 仅 `process`/`gates`/`agents` 与**新增 9 条**（MI/NG/CL）变动；新增条目需重新渲染 `rules/check_list.md`。
- 已在代码层实现对应行为（orchestrator 新阶段序、gate_validators 的 netlist 校验），**批准后**同步写回 rules.json 即一致。

## 请批复
- **(A)** 全部批准（A1+A2+A3+B）；
- **(B)** 批准 A，B 的 ID 段/条数要调整（给出）；
- **(C)** 暂不写回 rules.json，仅保留代码实现（我记为"待批"）。

---

## E. v4 变更记录（2026-09-11，**已实施并固化**）

> 由 `scripts/prepare_rules/apply_v4_rules.py` 幂等写入 `rules/rules.json`（`_audit.v4_applied`），并重渲染 `docs/check_list.md`。

### E1. 新增强制规则（rules[]）

| ID | 阶段 | 门 | 规则要点 |
|---|---|---|---|
| `NG-010` | PH-2 | G2 | 方向语义与权威来源：`links[].side∈{up,down,bi,pwr,nc}` 同网一致；电源/地判定用 conventions 权威正则，禁自造 |
| `NG-011` | PH-2 | G2 | 追踪：起=接插件脚，止=有源落点；可跨越件=2 脚 R/L/BEAD/FB/FERR/JMP/0R 且两端非电源地；`trace_max_hops=6`；访问集防绕圈 |
| `NG-012` | PH-2 | G2 | 差分对语义：`_P/_N`、`P/N`、`H/L`、`+/-` 视为同一逻辑信号，跨到搭档=原地打转 |
| `NG-013` | PH-2 | G2 | 双向验证：正反路径集合一致且互达→OK；否则 MISMATCH 必带原因分类 |
| `NG-014` | PH-2 | G2 | 落点判定：CHIP / TO_CONNECTOR / POWER / OPEN_END / STUB |
| `PF-001` | PH-2 | G2 | 平台识别：按 `rules/index.json` 的 `platform.detect` 写入 `netlist_graph.meta.platform` |
| `PF-002` | PH-3 | G3 | 平台规则加载：按 `load_policy` 注入 common+platform 规则；`pinout.json` 不进 LLM |
| `PF-003` | PH-3 | G3 | 官方引脚核对：SoC/DDR/PMIC/eMMC 以 `platform/<芯片>/pinout.json` 为权威（IC-007/IC-008） |
| `PF-004` | PH-3 | G3 | 核对覆盖率=已核对/应核对；低于阈值或存在未解释不一致 → 不得 PASS |
| `PF-005` | PH-3 | G3 | 规则束预算：全量须在 `rule_bundle_tokens`（≥58K）内完整注入；截断须显式列出被丢弃 ID |

- 规则束归属（通配符）：PH-2 += `PF-001*`；PH-3 += `PF-*`；PH-2 既有 `NG-*` 自动纳入 NG-010~014。
- 门禁审计登记：G2 强制 NG-010~014；G3 强制 PF-002/003/004（`gate_enforced`）。

### E2. 新增代码生成硬性要求（dev_rules）

| ID | 要点 |
|---|---|
| `DEV-009` | **规范先行**：规范是唯一权威，代码服从规范；实现与规范不一致时改代码；缺参数化条款先补规范 |
| `DEV-010` | **权威来源不重复定义**：conventions 为单一真源，工具不得自造正则/常量 |
| `DEV-011` | **md→json 校验护栏**：转换产物必过 `rules_contracts` Pydantic 校验 + 预算护栏 |

### E3. 单一真源 / 平台链路

- **单一真源**（NG-006）：`netlist_graph.json` 不内嵌邻接表（删 `upstream/downstream/via`），邻接由 `pins+joins` 经 `GraphIndex` 派生；等值证据见 `tools/verify_adjacency.py` + `docs/evidence/adjacency_baseline_FL-25-E-MR203.json`（4131 引脚 EQUIVALENT）。
- **平台链路**：`raw/raw_platmform/<芯片>` →（`platform_to_json`）→ `rules/platform/<芯片>/{rules*,pinout,pinout.index}.json` + `rules/index.json`；PH-3 经 `load_rule_assets` 注入规则束、`platform_check` 做官方核对（RK3588 覆盖率 0.817），`pinout` 绝不进 LLM。
- **规则资产化**：`raw/raw_rules/*.md` →（`md_to_json`）→ `rules/common/*.json`（6 个 / 165 条，ID 与 `rules.json` 100% 对齐）。

### E4. 预算调整

- `rule_bundle_tokens` **40000 → 64000**（PH-3 全量 202 条 / 56720 tok 无截断）；`context_total=512K` 天花板不变。
