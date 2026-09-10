# 硬件原理图自动审查 + 故障分析系统 — 设计文档（已确认版）

> 日期: 2026-09-10 | 状态: 已与用户逐条确认，可实施 | 依据: 多次设计讨论纪要

## 0. 目标与边界
- 基于 CrewAI 的硬件原理图（EDN 网表）自动化审查 + 故障分析工具。
- `raw/` = 唯一事实源（角色规则/检查规则/平台数据），**全程只读、绝不修改**。
- 一期实现审查闭环（PH-0..7）+ 故障咨询（hw_master）+ 调试 web；二期做自学习 learn/ 回写。

## 1. 模型与配置（config.json 单一配置）
- LLM 默认 `spark-dsv4 / deepseek-v4-flash-0731`（内网网关 `222.128.103.10:18080/api/v1`，OpenAI-completions），可配置升级 `pro: deepseek-v4-pro`。
- `config.json` 段：`llm{provider,baseUrl,apiKey,models{flash,pro},default_model}`、`budget{...}`、`web{download_dir,tavily_key...}`、路径。
- apiKey 支持 `TAVILY_API_KEY` 等环境变量覆盖；config.json 不入 git，提供 config.example.json。
- **预算（可调项）**：context_total=512K **固定不可改（硬顶，validator 按 min(配置,512K) 钳制）**；input_hard_cap=400K、target=256K、rule_bundle_tokens=40K、auto_retry=3 均可调。

## 2. 目录（已定，2026-09-10 实测）
```
raw/           只读事实源（raw_roles/raw_rules/raw_platmform）
roles/         派生的 agent 定义（CrewAI 格式）
rules/         派生的检查规则：rules.json(单源) + 渲染.md + platform/<芯片>/
src/           运行时核心（非 web）：tools/models/flows/cli/workspace/prompt-assembler + tools.md 注册表
web/           web 前端本体（原 forward 更名）：server.py + html/ css/ src/
project/       输入：EDN/BOM（已含真实测试项目 FL-26-E-MR203: A/B 两块 EDN + 两份 xlsx BOM）
storge/        refbook(既有手册库,只读) / datasheet(Tavily 下载存档,可写) / project(产品B..F产出) / problem(故障)
scripts/       prepare_rules（raw 解析构建器，幂等可重跑、留痕）
docs/          plans/ conflicts/ 等
config.json    （不入 git；有 config.example.json）
```

## 3. 资产契约与规则整理（阶段1）
- rules.json = 规则**单一事实源**（人机同一套）；`.md` 视图由它渲染，永不手工同步。
- raw 整理流程：逐条解析 → 冲突检测 → **逐条人工确认** → 编号规范化（§1.2→1.2/1.3、审计标准 G0-G7→SA-1..8）→ **反向验证（遗留=0 错位=0）** → 生成 assets。
- 已确认的规则决策：§5.3 纯标准库约束**取消**（可用 pydantic/第三方）；Context7 **废弃**（软件文档 API，不适用硬件）；librarian 由 refbook 本地检索等价覆盖；模型名统一 spark-dsv4。
- 开发法：脚本资产化（scripts/prepare_rules 幂等可重跑）；`src/tools.md` 注册门禁（新增脚本未注册=不可合入）。

## 4. 流程与门禁（重编号）
- 阶段 **PH-0..7**：PH-0 输入准备(Step0a) / PH-1 hw_prep(多EDN全局合并+完整信号链) / PH-2 hw_search(手册检索) / PH-3 数据预检(确定性) / PH-4 hw_analyze(深度分析,芯片级并行≤5,LLM补盲) / PH-5 hw_write(报告 JSON+.md) / PH-6 hw_auditor(审计) / PH-7 闭环交付。
- 门禁 **G1..G7**：G1 prep_validate / G2 手册缺失确认(人机A/B/C) / G3 数据完整性(确定性) / G4 g2x_validate / **G5 报告门 = 确定性结构校验 + LLM 内容审核（提交 规则+要求+内容 → 需改清单 → 修订 → 有界2轮）** / G6 审计门(SA-1..8+证据链) / G7 闭环。
- **Flow（=hardware_review）确定性裁判**：Gate 单一门控 PASS 放行 / FAIL 硬阻断+退回；批次边界自动停等人工。
- 信号追踪：图遍历+终止规则+双向验证+mux落地（端到端可脚本校验）；LLM 补盲共用 D2 子图打包器 + 分类缓存；判不出→UNVERIFIED。
- 人工解决问题点（6 类）：规则冲突仲裁 / G2 缺失A-B-C / G6 未决项归档 / 故障实测闭环 / 终稿签字 / (二期)自学习建议。

## 5. 数据与格式
- 全 JSON：中间产物 + LLM 反馈一律 JSON（Pydantic 契约强制）；报告 = report.json + 自动渲染 .md。
- 位号↔BOM↔功能映射 JSON（identity/function/manual/provenance 分层、渐进填充、分类反查）。
- 落盘即真相；经验存 learn/ 文件（二期写回，本期留加载钩子）。

## 6. 角色与提示词
- hardware_review(Flow裁判) + hw_search / hw_prep / hw_analyze / hw_write / hw_auditor(流水线) + hw_master(故障咨询)。
- 提示词三段式：角色指令(roles/) + 任务指令(Flow 按阶段组装: 规则束+输入引用+约束, 懒加载) + 输出契约(Pydantic)。

## 7. 上下文与预算
- 512K 硬顶(不可改) / 输入硬限 400K / 目标 256K / 规则束≤40K（均可下调/上调，除 512K）。
- 切片不压缩；manual_lookup 按需读手册；budget_validator 超限自动切片，绝不静默截断。

## 8. 网络检索
- Tavily（search/extract/download）已配置并实测可用。
- G0 检索链：refbook 本地递归+模糊 → 未中 → Tavily ≥2 策略 → 合计 ≥3 次有效尝试 → 匹配则下载存档 `storge/datasheet/{分类}/` → 仍无 → 缺失清单 + UNVERIFIED。

## 9. Web 前端（web/ = server.py + html/ css/ src/）
- 功能：上传 EDN/BOM、Start、日志、全环节进程轨、当前环节高亮、当前环节 agent 运行数、每 agent 输出、日志终端。
- 数据：Crew task_callback/step_callback + Flow 状态 → run.log(JSONL) + run.state.json → SSE 实时。
- 门禁可见：进程轨 Gate 状态灯 + check 明细 + 退回原因 + 事件日志。
- 人工交互统一"待你处理"：Step0a 表单 / G2 A-B-C / 批次继续 / G6 确认 / 诊断输入 → POST /api/human/{topic} 写 run JSON，Flow checkpoint 恢复。

## 10. 开发流程
- 每个模块 DoD：实现 → 单测 → tools.md 注册 → **有界 2 次自动 LLM 复审**（无人工中插）→ 冻结；剩余建议进 docs/optimization_backlog.md。
- 自检修复边界：**修实施不修规则**（可改 src/scripts/web/models实现/config非规则键/tools.md/产物；禁止改 raw/rules.json/已确认编号与冲突结论/refbook/已签字交付物）；实现类自动修 ≤auto_retry 次，规则类冻结走人工流程。

## 11. 自检验收（阶段8）
- 三层：L1 单元 / L2 流程冒烟(fixture) / L3 实弹(FL-26-E-MR203 A/B EDN+BOM)。
- 清单项：多EDN跨板、BOM解析、手册检索(含Tavily路径)、证据契约、报告+G5二轮、人机点、web、故障注入(负面)、可复现、预算、溯源。
- 充分性证据：覆盖率(阶段8/8 门禁7/7 角色6+1 工具100%注册)、负向命中、金标人工抽验≥20条、两跑diff、反向校验、预算记录；产出 selfcheck_report.md 提交复核。
