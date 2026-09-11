# 硬件原理图自动审查 + 故障分析系统

基于 **CrewAI** 的 EDN 网表自动审查工具：**PH-0..6 门禁流水线**（输出 `netlist_graph.json` 网表 json 化 + 审查报告）
+ 故障分析顾问 + Web 调试面板。真实验证项目：`FL-25-E-MR203`（A/B 双板，RK3588 + 安路 EG4X20）。

> 版本：v3（2026-09-11）：规则资产化（`common/`+`platform/` JSON）、上下游规范 NG-010~014、平台链路 PF-001~005、`netlist_graph` v3.0（单一真源 + 平台识别）。

---

## 一、快速启动

```bash
cd /home/antimax-ai/work/AI/crewai/hardware_analysis
export PYTHONPATH=src                 # 关键：让模块可导入
```

### ① 快速验证（MOCK，不调真 LLM，约 1–2 分钟）
```bash
HARDWARE_MOCK=1 .venv/bin/python -m hardware_analysis.cli run --product FL-25-E-MR203
```
- `HARDWARE_MOCK=1` ＝ 用假 LLM，只验 **流程/门禁/产物** 是否通；
- 默认**自动跑完**；仅在真需人工处暂停等待（网页处理），处理完**自动继续**；
- 期望输出：`current: DONE`、`gates` 全 `PASS`（G1–G6）。

### ② 真实模式（调真 LLM，慢——单次约 44s，全量很久）
```bash
.venv/bin/python -m hardware_analysis.cli run --product FL-25-E-MR203
```
> ⚠️ 建议先用 MOCK 验流程；真跑留到出会话/缩小范围（见下文"分步跑"）。

### ③ Web 调试面板（可视化进度/门禁/日志）
```bash
.venv/bin/python -m uvicorn web.server:app --reload     # 或 uvicorn web.server:app --reload
# 浏览器打开 http://127.0.0.1:8000
```

---

## 二、分步跑（可指定阶段，不必全量）

```bash
.venv/bin/python -m hardware_analysis.cli run   --product FL-25-E-MR203   # 全流程
.venv/bin/python -m hardware_analysis.cli prep|validate|search|analyze|write|audit|finalize --product FL-25-E-MR203
```
- `prep/validate` 目前等于"PH-1+门禁 G1"（按需扩展）；其余为 agent 阶段（阶段 5 已接线）。
- 单查某道门禁：
```bash
.venv/bin/python -m hardware_analysis.tools.gate_validators G3 storge/project/FL-25-E-MR203
```

---

## 三、产出（都在 `storge/project/<产品>/`）

| 阶段 | 产物（目录 = 阶段号，一一对应） |
|---|---|
| PH-0 输入准备 | `PH-0_输入准备/step_0a.json` |
| PH-1 手册检索 | `PH-1_手册检索/`：`bom_entries.json`、`manual_index.json`（位号→手册路径 + ic_type）、`precheck.json` |
| PH-2 网表解析 | `PH-2_网表解析/netlist_graph.json`（**核心**：devices/nets/paths/cross_board_links）＋ `global_*`、`trace_inventory.json` |
| PH-3 深度分析 | `PH-3_深度分析/*_summary.json`、`*_evidence.json`、`clarify_*(requests/resolutions).jsonl` |
| PH-4 报告 | `PH-4_报告合成/report.json` |
| PH-5 审计 | `PH-5_审计复核/audit.json` |
| PH-6 交付 | `PH-6_闭环交付/final_report.json`（定版）+ `delivery.json` |
| 门禁 | `gates/G1..G6.json`（PASS/FAIL + 逐条检查） |
| 日志 | `.run/run.log.jsonl`、`run.state.json`（web 用） |

中间文件（`.run/temp/*.timestamp.components|nets.json`）**即用即清**，最终零残留。

---

## 四、验收 / 自检

```bash
HARDWARE_MOCK=1 .venv/bin/python -m scripts.selfcheck.run_selfcheck --product FL-25-E-MR203
# 期望：自检 10/10 PASS（含负向故障注入、反向校验、可复现 md5）
```

---

## 五、配置

- **`config.json`**（根目录，**不入库**，含密钥）：`llm / budget / web / paths / conventions`。
  - 用 `config.example.json` 作模板：`cp config.example.json config.json` 后填 `apiKey`。
  - 密钥支持环境变量覆盖：`LLM_API_KEY`、`TAVILY_API_KEY`。
- **`conventions` 段**（可调 EDA 约定与阈值，缺省用代码默认）：连接器配对门限、追踪步数上限、电源网正则、位号前缀等。改 `config.json` 即生效，不用改代码。
- 预算：`context_total` **固定 512K 硬顶**（不可破）；`rule_bundle_tokens=64000`（PH-3 全量规则束注入预算，可调）。

---

## 六、规则与角色（要改规则时）

- `rules/rules.json` = **机器单一事实源**（审查规则 + 阶段/门禁 + `dev_rules` 代码生成硬性要求 + 平台）。
- `docs/check_list.md` = 由 rules.json **自动渲染**（勿手改；跑 `apply_v4_rules` 自动重印）。
- 改阶段/门禁/加规则 → 用脚本（不直接手改）：
```bash
python -m scripts.prepare_rules.apply_v4_rules     # 幂等；v4：NG-010~014 / PF-001~005 / DEV-009~011 + 重渲染 docs/check_list.md
python -m scripts.prepare_rules.apply_v3_rules     # 幂等；v3：NG-006/007/008 + DEV-007/008
python -m scripts.prepare_rules.apply_v2_rules     # 幂等；结构元数据
python -m scripts.prepare_rules.reverse_check      # 校验：遗留=0 / 错位=0
```
- `raw/` **只读**（唯一事实源，禁改）；`roles/*.yaml` 由 `scripts/prepare_rules/generate_roles.py` 生成。

### 规则资产结构（`rules/`，全部为派生资产，幂等可重跑）

```
rules/
  rules.json            机器单一事实源（人机同源）
  index.json            总索引：common + platform + load_policy + platform.<芯片>.detect
  common/<中文主题>.json 通用规则 bundle（6 个 / 共 165 条；kind=rule_bundle；ID 与 rules.json 对齐）
  platform/<芯片>/        platform：rules*.json（进 LLM）+ pinout.json（引脚表，不进 LLM）+ pinout.index.json（O(1) 查询）
  add_new.md            新增/维护规则指南（JSON 接收格式 + 如何新增 + 预算护栏；不并入 rules.json）
docs/check_list.md      人读检查清单（由 rules.json 自动渲染）
```

- **生成脚本**（只读 `raw/`，写 `rules/`）：
```bash
export PYTHONPATH=src
python scripts/prepare_rules/md_to_json.py           # raw/raw_rules/*.md → rules/common/*.json（sha1 增量；--force 重写）
python scripts/prepare_rules/platform_to_json.py     # raw/raw_platmform/<芯片>/* → rules/platform/<芯片>/ + rules/index.json（--force / --chips）
python scripts/prepare_rules/apply_v4_rules.py       # v4 规则固化（NG-010~014 / PF-001~005 / DEV-009~011）
```
- **加载策略**：`rules/index.json → load_policy` 决定各阶段注入哪些 common 主题与平台规则；**引脚数据 `pinout.json` 绝不注入 LLM**，由 `platform_check` 按 `pinout.index.json` 按需查单条（PF-002）。
- **预算护栏**：单文件 `tokens_est ≤ 20000`（超限自动拆分）；PH-3 全量规则束须在 `rule_bundle_tokens=64000` 内完整注入，发生截断必须显式列出被丢弃 ID（PF-005）。

### 校验 / 证据工具
```bash
# NG-006 派生邻接等价性证据（--make-baseline 生成基准；--graph --baseline 校验，等价→EQUIVALENT）
PYTHONPATH=src .venv/bin/python -m hardware_analysis.tools.verify_adjacency \
  --graph storge/project/FL-25-E-MR203/PH-2_网表解析/netlist_graph.json \
  --baseline docs/evidence/adjacency_baseline_FL-25-E-MR203.json

# 平台官方引脚核对（识别平台 → 覆盖率/不一致；pinout 不进 LLM）
PYTHONPATH=src .venv/bin/python -m hardware_analysis.tools.platform_check \
  storge/project/FL-25-E-MR203/PH-2_网表解析 --platform RK3588
```

### dev_rules（代码生成硬性要求，启动自动读取）
`rules.json → dev_rules`（DEV-001..011）：
1. 代码产出过 Pydantic 契约校验；2. 新脚本注册 `src/tools.md`；3. 禁改 `raw/`/既有规则/refbook；
4. 改前备份(.bak)+每步验证；5. 提交前自检 10/10+mock；6. **生成代码须与 LLM 对话检查 2 次**（有效/效率/通用性）；
7. 真源唯一化（DEV-007）；8. 大图按需访问（DEV-008）；
9. **DEV-009 规范先行**（代码服从规范，缺参数化先补规范）；10. **DEV-010 权威来源不重复定义**（conventions 单一真源）；
11. **DEV-011 md→json 校验护栏**（转换产物必过 Pydantic + 预算）。

---

## 七、目录结构

```
raw/          唯一事实源（只读）            project/      输入 EDN/BOM（真实项目不入库）
roles/        派生 agent 定义（CrewAI）     storge/       refbook(datasheet,project,problem)
rules/        rules.json 机器单源 + common/{通用规则JSON} + platform/{芯片规则+引脚表} + index.json + add_new.md
src/          运行时核心 + tools.md 工具注册表（新脚本必须登记）
web/          server.py + html/css/src（调试面板）
scripts/      prepare_rules / selfcheck     docs/         设计/冲突/自检/backlog
config.json    本地配置（不入库）            .venv/        依赖（python3.12）
```

---

## 八、常见问题

- **没设 PYTHONPATH** → 报 `ModuleNotFoundError: hardware_analysis`：先 `export PYTHONPATH=src`。
- **想换产品**：把 EDN/xlsx(docx) 放进 `project/<名称>/`，然后 `--product <名称>`。
- **BOM 只支持 xlsx/xlsm/docx**（Word 也能解析）。
- **真实模式太慢**：优先 MOCK + 分步跑；需要时缩小到重点 IC。

---

## 状态

v3（2026-09-11）：规则资产化（`rules/common` 6×JSON 165 条 + `rules/platform` 4 芯片规则/引脚表/索引 + `rules/index.json`）；netlist_graph v3.0 单一真源 + 平台识别；tracer 按 NG-010~014 重写（MISMATCH 0 / 无回绕）；**mock 全流程 DONE、G1–G6 全 PASS、自检 10/10 PASS**；真实验证项目 FL-25-E-MR203（4131 引脚等值 EQUIVALENT、RK3588 覆盖率 0.817）。详见 `docs/plans/2026-09-10-hardware-analysis-design.md`。
