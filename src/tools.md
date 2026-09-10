# src/tools.md — 运行时工具接口注册表

> 注册门禁：凡在 `src/` 新增脚本必须在此登记一条接口；未登记=不可合入。
> 全部工具输入/输出均为 JSON；确定性工具幂等可重跑。

## [T-EDN-PARSE] edn_parse
- 模块   : src/hardware_analysis/tools/edn_parse.py
- 功能   : EDIF 2.0.0 s-表达式 真实语法解析（OrCAD/CAPTURE 导出）；产 per-file components/nets JSON
- 输入   : edn(str,必填) EDN 路径；--out(str,可选) 输出目录
- 输出   : {stem}.components.json（refdes→{refdes,model,cell}）；{stem}.nets.json（[{net, joins:[{refdes,pin}]}]）；stdout 统计
- 已验证 : FL-26-E-MR203-A(606元件/462net/2773连) B(346/340/1364)
- 副作用 : 只写 out；幂等

## [T-CFG] config.load
- 模块   : src/hardware_analysis/config.py::Config
- 功能   : 读取 config.json（LLM/预算/网络/路径），环境变量覆盖 LLM_API_KEY/TAVILY_API_KEY
- 输入   : path(str,可选) 默认 config.json
- 输出   : Config 对象（.llm .budget .web .paths；budget.context_total 恒钳制 512K）
- 副作用 : 只读；幂等

## [T-CONTRACT] models.contracts
- 模块   : src/hardware_analysis/models/contracts.py
- 功能   : §4.x 数据契约 Pydantic 模型（Severity 五级 / Confidence / GateStatus / BaseDoc / RunManifest / Step0aConfig / G0Sources / GateResult / EvidenceDoc / SummaryDoc≤5KB / ReportDoc）
- 输入   : 各 JSON 载荷
- 输出   : 校验通过的结构化对象；非法输入抛 ValidationError
- 副作用 : 无

## [T-WS] workspace.create_run
- 模块   : src/hardware_analysis/workspace/manager.py::create_run
- 功能   : 为产品创建 run 工作区（B/C/D/E/F/gates/.run）并写 run_manifest.json
- 输入   : product(str,必填)；root(str,可选,默认 storge/project)
- 输出   : run_manifest dict（写在工作区根）
- 副作用 : 创建目录 + 写 manifest + 建 .run/run.log.jsonl；可安全重入

## [T-WS-LOG] workspace.RunWorkspace.log / write_state
- 模块   : src/hardware_analysis/workspace/manager.py::RunWorkspace
- 功能   : 追加 JSONL 事件日志（供 web SSE）；写 run.state.json 快照
- 输入   : log(event:dict)；write_state(state:dict)
- 输出   : 无（写文件）
- 副作用 : 写 .run/run.log.jsonl 与 .run/run.state.json；幂等追问追加

---
## [T-EDN-MERGE] edn_global_merge
- 模块   : src/hardware_analysis/tools/edn_global_merge.py
- 功能   : 多 EDN per-file 全局合并（元件按refdes、网络按网名）+ 跨板检测 + 信号链（沿透明器件）
- 输入   : input_dir(per-file *.components/nets.json)；out_dir
- 输出   : global_components.json / global_nets.json / cross_board_nets.json / signal_chains.json / merge_report.json
- 已验证 : FL-25-E-MR203 A+B → 716 元件 / 692 net / 110 跨板 / 472 链

## [T-BOM-PARSE] bom_parse
- 模块   : src/hardware_analysis/tools/bom_parse.py
- 功能   : BOM(xlsx) 解析（自动选表跳过变更单、表头模糊映射、位号逗号展开）
- 输入   : bom.xlsx...(一或多个)；--out 输出路径
- 输出   : bom_entries.json（refdes→{name,mfg_model,mfg,package,qty,grade,note,bom_row}）
- 已验证 : 双 xlsx → 365 位号（A板U6=EG4X20BG256I8 等真实数据）

## [T-REFDES-MAP] refdes_map
- 模块   : src/hardware_analysis/tools/refdes_map.py
- 功能   : 位号↔BOM↔功能映射（EDN×BOM 按 refdes 合并；function/manual 留待 E 阶段渐进填充）
- 输入   : B_prep 目录（global_components.json + bom_entries.json）
- 输出   : refdes_function_map.json（identity/provenance/index/stats/conflicts）
- 已验证 : 776 位号 / 双源一致 305 / 型号冲突 0

新增工具登记：在此追加 [T-xxx] 块（功能/输入/输出/副作用）。
