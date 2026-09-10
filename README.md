# 硬件原理图自动审查 + 故障分析系统

基于 **CrewAI** 的 EDN 网表自动审查工具（PH-0..7 门禁流水线 + 故障分析顾问 + web 调试面板）。

## 快速开始

```bash
source .venv/bin/activate            # 依赖已装(crewai/fastapi/openpyxl...)
export PYTHONPATH=src
# 一键审查（真实模型；无人值守用 --auto-pass）
python -m hardware_analysis.cli run --product FL-25-E-MR203 [--auto-pass]
# 快速验证（HARDWARE_MOCK=1 不调 LLM，跑确定性流程+门禁）
HARDWARE_MOCK=1 python -m hardware_analysis.cli run --product FL-25-E-MR203 --auto-pass
# 分步
python -m hardware_analysis.cli prep|validate|search|analyze|write|audit|finalize --product ...
# web 调试面板
uvicorn web.server:app --reload     （http://127.0.0.1:8000）
# 规则重建（raw 只读 → 资产）
python -m scripts.prepare_rules.inventory_raw && python -m scripts.prepare_rules.renumber \
  && python -m scripts.prepare_rules.reverse_check && python -m scripts.prepare_rules.generate_rules
```

## 结构

- `raw/` 唯一事实源（只读）；`roles/ rules/` 派生（rules.json 单源 + check_list.md 渲染 + platform 平台包）
- `src/hardware_analysis/{models,tools,flows,agents,prompt,workspace,cli}`；`src/tools.md` 工具注册表
- `web/` 前端（html/css/src）；`project/` 输入 EDN/BOM；`storge/{refbook,datasheet,project,problem}`
- `scripts/{prepare_rules,selfcheck}`；`docs/`（设计/冲突/自检/backlog）

## 配置

`config.json`（不入库，用 `config.example.json` 模板 + 真实密钥）：llm(spark-dsv4) / budget(512K 硬顶) / web(tavily)。

## 状态

一期 14 阶段完成 13/14（最后为收尾交付确认）；自检 9/9 PASS（含负向）。详见 `docs/plans/2026-09-10-hardware-analysis-design.md` 与 `docs/selfcheck_report.md`。
