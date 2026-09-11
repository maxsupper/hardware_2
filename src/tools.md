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
- 功能   : 端到端信号追踪（NG-010~014 重写）：深度上限 trace_max_hops=6 / 差分对防打转 / 访问集防绕圈 / **先本网有源落点（已抵达不再跨件）** / 反向对称停止 / MISMATCH 原因分类 reason
- 输入   : PH-2_网表解析 目录(global_nets.json)；--limit 起始网上限
- 输出   : trace_inventory.json（traces+inventory 终点分布+inventory.mismatch_reasons）；每条带 endpoint_pins/reason
- 已验证 : 真实数据 400 条 → TERMINAL/OPEN_END/ACROSS；MISMATCH 0、无回绕（OSCILLATION=0 DEPTH_EXCEEDED=0）
- 备注   : 落点分类 CHIP/TO_CONNECTOR/POWER/OPEN_END/STUB（NG-014）；reason∈OSCILLATION/DEPTH_EXCEEDED/NO_ACTIVE_END/REVERSE_NOT_HOME/PATH_DIFF/POWER_BRIDGE；endpoint_pins 契约不变

## [T-GATE] gate_validators
- 模块   : src/hardware_analysis/tools/gate_validators.py
- 功能   : 确定性门禁 G1(prep/信号链闭合) G2(数据完整性/网表解析：**+NG-006/007/010/011/012**) G3(**+PF-001/003/004/005** 平台匹配/官方核对/覆盖率/缺口告警) G4 G5
- 输入   : gate(G1|G2|G3|G4|G5) + 产品工作区路径；--out gates/G<n>.json
- 输出   : gates/G<n>.json（GateResult 契约）；stdout 逐条 check
- 已验证 : G1/G2(真实数据 PASS) / G4、G5(空目录负向 FAIL 成立)；G3 平台核对含反例与降级（无官方表→WARNING）
- 副作用 : 写 gates/*.json；幂等
- 备注   : PF-004 覆盖率阈值可经 conventions.platform_coverage_min 覆盖；PF-005 官方表缺口>0 记 WARNING

## [T-BUDGET] budget_validator
- 模块   : src/hardware_analysis/tools/budget_validator.py
- 功能   : 上下文预算强制（规则束≤rule_bundle_tokens=64K / 输入≤400K / 总上下文≤512K硬顶，不可破）
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
- 输出   : Config 对象（.llm .budget .web .paths；budget.context_total 恒钳制 512K；rule_bundle_tokens 默认 64000）
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
- 功能   : PH-2 产物——网表 json 化（v3.0）：devices/nets/paths/cross_board_links；**NG-006 单一真源**（不内嵌邻接，邻接由 pins+joins 经 GraphIndex 派生）；连接器配对；**PF-001 平台识别**
- 输入   : PH-2_网表解析 (global_* / trace_inventory / refdes_function_map) + PH-1_手册检索/manual_index.json；--groups N；--product；--pretty
- 输出   : netlist_graph.json（v3.0，默认紧凑 1.04MB）；meta.validation 含 dangling/uncovered/embedded_adjacency；meta.platform / meta.platform_detect（平台识别）
- 已验证 : FL-25-E-MR203 → 952 器件/802 网/472 路径/跨板144/配对 J19↔J8=144脚；dangling=0 uncovered=0 embedded=0；165MB→1.04MB(↓158×)
- 备注   : links 按脚拆条，仅留不可派生：net/pin/side/fanout/trace/status/cross_board；删 upstream/downstream/via；邻接用 GraphIndex.neighbors()

## [T-VERIFY-ADJ] verify_adjacency
- 模块   : src/hardware_analysis/tools/verify_adjacency.py
- 功能   : NG-006 **等值证据**——证明「派生邻接」与旧 links[].upstream/downstream 逐条等价（含 model/kind 全字段）
- 输入   : --make-baseline <旧graph.json> -o <基线.json> ；校验：--graph <新> --baseline <基线>
- 输出   : 基线 JSON（引脚→side/fanout/邻居集合哈希）；stdout 判定 EQUIVALENT/DIFFERENT；退出码 0/1
- 已验证 : FL-25-E-MR203 → 4131 引脚 / 1,232,943 邻接条目，**EQUIVALENT（不等=0 缺失=0）**
- 备注   : 作为 PH-2 自检项；基准存 docs/evidence/adjacency_baseline_<产品>.json

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
- v4新增 : trace_max_hops=6；series_passive_prefixes(R/L/BEAD/FB/FERR/JMP/JUMP/0R)+is_series_passive()；差分对识别扩展 `+/-`；power_net_regex 权威化（NG-010，工具禁自造正则）
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

## [T-PDF-TO-MD] pdf_to_md
- 模块   : src/hardware_analysis/tools/pdf_to_md.py
- 功能   : PDF → Markdown 文本抽取（pdftotext 优先，退化 pdfplumber；无文字层提示需 OCR）；供手册检索/阅读统一为 .md
- 输入   : convert(<pdf>[--out-dir D][--force]) / convert_many([pdf|dir]) / CLI: python -m ... <pdf|dir>...
- 输出   : 同名 .md（含来源/方法头）；返回 {src,out,chars,ok,error,method}
- 接入   : web /api/manual/upload 上传 PDF 后**自动触发**转换（converted_md 字段）
- 已验证 : storge/datasheet/ETA3417S2F.pdf → 正文抽取成功

## [T-PREPARE-RULES-V3] apply_v3_rules（规则固化）
- 模块   : scripts/prepare_rules/apply_v3_rules.py
- 功能   : v3 规则固化（幂等）——把「单一真源/禁内嵌邻接/规模守门/等值可证」写成**通用规则**
- 写入   : rules[] += NG-006(单一真源) / NG-007(规模守门) / NG-008(等值可证)；dev_rules += DEV-007(真源唯一化,通用) / DEV-008(大图按需访问)
- 强制   : 规则文本(人/LLM) + dev_rules(启动即读) + **G2 门禁代码强制**(gate_validators NG-006/NG-007)
- 输出   : rules/rules.json（含 _audit.v3_applied）+ rules/check_list.md 重渲染
- 备注   : PH-2 规则束模式为 NG-*，新规自动纳入；须在 generate_rules.py 之后重跑（防被 raw 重生成覆盖）

## [T-PREPARE-RULES-V4] apply_v4_rules（v4 规则固化）
- 模块   : scripts/prepare_rules/apply_v4_rules.py
- 功能   : v4 规则固化（幂等）——把「方向语义/追踪/差分对/双向验证/落点」「平台识别/加载/官方核对/覆盖率/预算」写成通用规则
- 写入   : rules[] += NG-010~014（上下游解析）/ PF-001~005（平台链路）；stage 通配符 PH-2 += PF-001*、PH-3 += PF-*；dev_rules += DEV-009(规范先行)/DEV-010(权威来源不重复定义)/DEV-011(md→json 校验护栏)
- 强制   : rules 文本(人机同源) + dev_rules(启动即读) + gates 审计登记(G2 NG-010~014 / G3 PF-002/003/004)
- 输出   : rules/rules.json（含 _audit.v4_applied）+ docs/check_list.md 重渲染
- 备注   : 与 apply_v2/apply_v3 同序；须在 generate_rules.py 之后重跑（防被 raw 重生成覆盖）

## [T-MD-TO-JSON] md_to_json（md→json 转换引擎）
- 模块   : scripts/prepare_rules/md_to_json.py
- 功能   : raw/raw_rules/*.md → rules/common/*.json（6 通用 bundle）；markdown 标题切条 + 伪标题 chunker（无标题 md）；ID 复用（按 rules.json 同源行号）+ 前缀映射；stage/gate 适配
- 输入   : raw/raw_rules/*.md；--force / --only NAME / --out-dir（默认 rules/common）/ --rules（默认 rules/rules.json）
- 输出   : common/<主题>.json（kind=rule_bundle）含 must/must_not/tokens_est；单文件 >20000 tokens 自动拆分
- 已验证 : 6 文件 165 条，与 rules.json 既有 ID 100% 对齐
- 备注   : 产物一律过 models.rules_contracts 的 Pydantic 校验；sha1 增量（源未变→skipped）；只读 raw/、只写 rules/common/

## [T-PLATFORM-TO-JSON] platform_to_json（平台派生）
- 模块   : scripts/prepare_rules/platform_to_json.py
- 功能   : raw/raw_platmform/<芯片>/* → rules/platform/<芯片>/{rules*.json,pinout.json,pinout.index.json} + rules/index.json（统一入口 + 逐芯片适配器）
- 输入   : CHIPS（code/md/pinout/md_adapter）；--force / --chips RK3588,E2000
- 输出   : 平台规则(kind=platform_rules，>20000 tokens 自动拆 rules_NN.json)、引脚表(kind=pinout_table，**不进 LLM**)、O(1) 引脚索引、总索引(kind=rules_index：common+platform+load_policy+detect)
- 已验证 : RK3588(7430tok/1088pin)/RK3576/RV1126B/E2000(拆 4 片)；detect.min_pins=总引脚×0.5
- 备注   : md 格式不作统一要求，逐芯片适配（markdown / e2000_datasheet 编号标题探测器）；sha1 增量；存在 rules_contracts 即做契约校验，否则轻量回退

## [T-MODELS-RULES] models.rules_contracts
- 模块   : src/hardware_analysis/models/rules_contracts.py
- 功能   : 规则 JSON 的 Pydantic 契约（RuleBundle/RuleEntry/Ref，`extra="forbid"` 冻结接收格式）
- 输入   : rules/common/*、platform 规则 JSON 载荷
- 输出   : 校验通过的结构化对象；字段缺失/多余抛 ValidationError
- 副作用 : 无

## [T-RULE-LOADER] rule_loader（索引 / 资产加载 / 渲染）
- 模块   : src/hardware_analysis/flows/rule_loader.py
- 功能   : ①load_index() 读 rules/index.json（缺失/异常→{} 优雅降级）；②load_rule_assets(stage,platform) 按 load_policy 组装 common/*.json + platform/<芯片>/rules.json（平台在前、通用在后；pinout 绝不进返回值仅回 pinout_path）；③render_rules_text() 渲染注入文本
- 输入   : stage；platform(可空)；index_path(默认 rules/index.json)；budget_tokens(默认 config.rule_bundle_tokens=64000)
- 输出   : {entries,rule_ids,tokens_est,cap,under_budget,sources,pinout_path,truncated,dropped[],dropped_tokens}
- 备注   : 超预算按 entry 顺序二分截断（保留最长可容前缀）并**显式告警 + 完整 dropped ID 列表 + dropped_tokens**，禁静默截断（PF-005）

## [T-DIRECT] agents.direct.llm_json
- 模块   : src/hardware_analysis/agents/direct.py
- 功能   : 直连 LLM 的 json 契约调用入口；新增 `rules_text` 参数把本阶段规则束注入 system（BRIEF_ROLE 之后、system_footer 之前）
- 输入   : agent/prompt/model_cls/…；rules_text(str,默认""=行为与旧版完全一致；mock 不受影响)
- 输出   : (解析对象, meta)
- 备注   : 仅非空时追加「【本阶段规则束（必须遵守）】」段

## [T-ORCH] flows.orchestrator（PH-3 规则注入 + platform_check）
- 模块   : src/hardware_analysis/flows/orchestrator.py
- 功能   : PH-3 深度分析循环外渲染一次规则束注入各 LLM 调用；调用 platform_check 写 PH-3_深度分析/platform_check.json；记录 rules_truncated 日志（含 dropped ID/dropped_tokens）
- 输入   : netlist_graph.meta.platform；规则资产 rules/index.json
- 输出   : PH-3_深度分析/platform_check.json；.run 日志事件 platform_check_done / platform_check_failed / rules_truncated
- 备注   : 平台识别失败优雅降级（仅通用规则 + 显式 warning）

## [T-PLATFORM-CHECK] platform_check（平台官方引脚核对）
- 模块   : src/hardware_analysis/tools/platform_check.py
- 功能   : 用平台官方引脚表核对主控 SoC 每脚（对应 IC-007/IC-008、PF-001/003/004）：①pin_existence ②function/复用 ③domain 电平域；报告覆盖率=已核对/应核对；识别平台（无 --platform 时按 rules/index.json detect）
- 输入   : <PH-2_网表解析_dir>；--platform 芯片(可空)；--out(默认 platform_check.json)
- 输出   : platform_check.json（platform/coverage/checks[pin_existence|function|domain]/inconsistencies）
- 已验证 : RK3588 覆盖率 0.817；核对三类判据保守（缺引脚 WARNING、明确冲突才 FAIL、无电压证据 SKIPPED_NO_NET_VOLTAGE）
- 备注   : **pinout 不进 LLM**——官方表优先 rules/platform/<芯片>/pinout.json，回退 raw/raw_platmform/<芯片>/pinout.json；脚名归一基于 CONV（DEV-010）

## [T-TEST-PLATFORMS] test_platforms（全平台链路回归）
- 模块   : scripts/selfcheck/test_platforms.py
- 功能   : 对 RK3588/RK3576/RV1126B/E2000 逐一验证「识别→规则加载(不截断/不注入引脚数据)→platform_check→G3 门禁」
- 输入   : 无（用真实 netlist_graph 造副本）
- 输出   : stdout PASS/FAIL 汇总；失败退出码非 0
- 已验证 : 4 平台 ALL PASS
- 备注   : 通用性回归；防"只对 RK3588 有效"

## [T-DATASHEET-TO-RULES] datasheet_to_rules（数据手册分章提炼硬件约束）
- 模块   : scripts/prepare_rules/datasheet_to_rules.py
- 功能   : 整本数据手册→按目录分章→分批 LLM 判定是否硬件约束→只保留硬件约束生成平台规则束（PF-006）
- 输入   : raw/<平台>/数据手册.md；--force / --batch-chars；缓存 rules/platform/<芯片>/filter_verdicts.json
- 输出   : rules/platform/<芯片>/rules.partN.json + filter_manifest.json（逐章 keep/drop+理由）+ 同步 rules/index.json
- 已验证 : E2000 → 176章 keep 149/drop 27；字符 100,988→28,325；丢弃仅噪声白名单；同标题一致=0；二跑 0 次 LLM 且字节一致
- 备注   : 标题硬护栏(title_guard)+丢弃理由白名单 双保险；PROMPT_VERSION 变更即缓存失效；不动其它平台资产
