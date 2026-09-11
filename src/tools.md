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

## [T-TRACER] tracer
- 模块   : src/hardware_analysis/tools/tracer.py
- 功能   : 端到端信号追踪（透明器件跨过/终端终止/OPEN_END检测）+ 终止清单 trace_inventory.json
- 输入   : PH-2_网表解析 目录(global_nets.json)；--limit 起始网上限
- 输出   : trace_inventory.json（traces+inventory 终点分布）
- 已验证 : 真实数据 400 条 → 395 TERMINAL / 2 OPEN_END / 3 ACROSS
- 备注   : 桥接异常(GND→VCC)列为自检金标校准项

## [T-GATE] gate_validators
- 模块   : src/hardware_analysis/tools/gate_validators.py
- 功能   : 确定性门禁 G1(prep/信号链闭合) G3(数据完整性) G4(evidence/summary契约/≤5KB) G5(report三字段/无截断)
- 输入   : gate(G1|G3|G4|G5) + 产品工作区路径；--out gates/G<n>.json
- 输出   : gates/G<n>.json（GateResult 契约）；stdout 逐条 check
- 已验证 : G1(真实数据 PASS) / G4、G5(空目录负向 FAIL 成立)
- 副作用 : 写 gates/*.json；幂等

## [T-BUDGET] budget_validator
- 模块   : src/hardware_analysis/tools/budget_validator.py
- 功能   : 上下文预算强制（规则束≤40K / 输入≤400K / 总上下文≤512K硬顶，不可破）
- 输入   : --rules 规则束文本；--input 输入文本(可多个)
- 输出   : budget_check dict（status/estimates/caps/checks）
- 已验证 : 512K 硬顶钳制生效

## [T-REFBOOK] refbook_search
- 模块   : src/hardware_analysis/tools/refbook_search.py
- 功能   : refbook/datasheet 递归扫描 + 型号模糊匹配（相等/互含/token重叠评分）
- 输入   : model(必填)；--root 默认 storge/refbook；--top
- 输出   : [{score,path,name,stem_match}] 按分降序
- 已验证 : RK3588/SIT3232/EG4X20 均命中

## [T-WEB] web_tools（web_search / web_extract / web_download）
- 模块   : src/hardware_analysis/tools/web_tools.py
- 功能   : Tavily 搜索/正文抽取校验/文件下载（HTTP直连，config 密钥）
- 输入   : search(q[,max_results])；extract(url[,depth])；download(url,dest)
- 输出   : search→[title,url,content]；extract→{url,ok,raw_content,error}；download→{url,ok,dest,size}
- 已验证 : search 定位 EG4X20 官方手册 PDF；key 有效

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
- 输入   : PH-2_网表解析 + PH-1_手册检索/bom_entries.json
- 输出   : refdes_function_map.json（identity/provenance/index/stats/conflicts）
- 已验证 : 776 位号 / 双源一致 305 / 型号冲突 0

新增工具登记：在此追加 [T-xxx] 块（功能/输入/输出/副作用）。

## [T-MANUAL-INDEX] manual_index
- 模块   : src/hardware_analysis/tools/manual_index.py
- 功能   : PH-1 产物——BOM 唯一 IC 型号 → 手册存放路径表格（manual_index.json）；本地 refbook 检索
- 输入   : bom_entries.json；--out；--refbook(默认 storge/refbook)；--product
- 输出   : manual_index.json（entries 键="板::位号"；model/ic_type/manual_path/status/attempted_sources）
- 已验证 : FL-25-E-MR203 → IC=37 唯型号=22 FOUND=10 PARTIAL=1 MISSING=11（RK860-2→RK860 Datasheet 命中）
- 备注   : ic_type(SINK/PASS_THRU/POWER_SRC) 由 PH-1 LLM 回填，本工具先置 UNKNOWN

## [T-NETLIST-GRAPH] netlist_graph
- 模块   : src/hardware_analysis/tools/netlist_graph.py
- 功能   : PH-3 产物——网表 json 化（v2.2）：devices/nets/paths/cross_board_links；子 agent 按接插件分组追踪后合并；连接器配对(D1)
- 输入   : PH-2_网表解析 (global_* / trace_inventory / refdes_function_map) + PH-1_手册检索/manual_index.json；--groups N；--product
- 输出   : netlist_graph.json + netlist_graph.validate.json（dangling/uncovered 完整性）
- 已验证 : FL-25-E-MR203 → 952 器件/802 网/472 路径/跨板144(信号109)/配对 J19↔J8=144脚；校验 dangling=0 uncovered=0
- 备注   : links 按脚拆条（side/upstream/downstream/via/cross_board）；0Ω→alias_group；差分对→diff_pairs

## v2 变更说明（2026-09-11 阶段换位/板级隔离）
- edn_global_merge：**板级隔离**（身份="板::位号"，网="板::网"）；不再输出 cross_board_nets.json；新增 merge_report(board_stats)
- bom_parse：支持 **Word(.docx)+Excel**；键改为 **"板::位号"**；新增 model 字段；剔除重复表头/签名行
- refdes_map：**按板配对**（A_EDN↔A_BOM）；DNP=EDN有BOM无（不装）；edn_symbol 与 BOM 料号不判冲突
- tracer：**接口优先**（起点=接插件脚）；只跨"真串联无源件"（两端非电源/地）；双向验证；终点 CHIP/POWER/TO_CONNECTOR/STUB/OPEN_END；--only_connectors 支持子 agent 分发
- refbook_search：型号**变体匹配**（RK860-2→RK860）+ 词元命中 + 手册/TRM 加权；纯字节重叠不入阈

## [T-CLARIFY] clarify（PH-4↔PH-3 回环协议）
- 模块   : src/hardware_analysis/tools/clarify.py
- 功能   : PH-4 提 request（自含 scope+假设）→ PH-3 只重读源 EDN 该局部定向复查 → resolution(CONFIRMED/CORRECTED+delta)；有界≤3轮
- 输入   : emit <PH-2_网表解析> <out.jsonl>；resolve <product> <PH-2_网表解析> <req.jsonl> <out.jsonl>
- 输出   : clarify_requests.jsonl / clarify_resolutions.jsonl
- 已验证 : FL-25-E-MR203 → 94 request / 94 CONFIRMED（回查源 EDN joins）

## [T-COMMON] common（通用层：约定 + 可复用 LLM 检查器）
- 模块   : src/hardware_analysis/common/conventions.py, llm_check.py
- 功能   : ①Common conventions 单一来源（位号前缀/电源网/透明件/连接器/差分对/板号/脚名归一 + 阈值），可经 config conventions 覆盖；②LLMChecker 统一"角色+任务+契约+按key持久化缓存+宽松归一"
- 输入   : config.json 的 conventions 段(可选,自动生效)/Conventions(overrides)；LLMChecker(cache_path).run(agent,task,contract,payload)
- 输出   : 归一化契约对象 + meta(errors/sec/cached/key)
- 已验证 : 全工具改用 CONV（去重 _board_of×3/前缀常量×3）；ic_type 判定走 LLMChecker 缓存

## v2 命名统一
- 位号种类前缀、透明件、连接器、电源网正则、差分对正则、板号正则、追踪 guard、扇出阈值、连接器配对阈值 → 全部集中在 `common/conventions.py::DEFAULTS`

## [T-MANUAL-GAPS] manual_gaps / apply_decisions（手册缺失确认，人机）
- 模块   : src/hardware_analysis/tools/manual_index.py::collect_gaps / apply_decisions
- 功能   : 收集无手册清单(manual_gaps.json)；应用人工决策 IGNORE(→UNVERIFIED)/COMPATIBLE(按兼容型号)/PROVIDE_FILE(补充文件)
- 输入   : collect_gaps(<PH-1_手册检索>)；apply_decisions(<PH-1_手册检索>, {位号:{action,...}})
- 输出   : PH-1_手册检索/manual_gaps.json；回写 manual_index.json(状态/路径/备注) + 重算 stats
- 已验证 : 19 项待补；IGNORE→UNVERIFIED / COMPATIBLE→FOUND_COMPATIBLE / PROVIDE_FILE→FOUND
- 人机   : web GET /api/manual_gaps/{产品} 列表 + POST /api/human/confirm{kind:manual,decisions} 写 gates/human_manual.json；CLI 非无人值守时打印清单并暂停
- 报告   : PH-4 报告追加"待补手册清单"表

### 手册缺失决策（四选一，web/CLI）
- 缺省：IGNORE → UNVERIFIED
- 上传：PROVIDE_FILE → 存 storge/datasheet，FOUND
- 替换：COMPATIBLE → 兼容型号检索，FOUND_COMPATIBLE
- **说明(NOTE)：填补充描述 → 提交时发 LLM(ManualNoteVerdict) 判定 IGNORE/COMPATIBLE 并落库(含理由)**
- 契约：models.contracts.ManualNoteVerdict(action/compatible_model/reason/confidence)
