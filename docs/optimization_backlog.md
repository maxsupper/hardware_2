# 优化待办（optimization backlog）

> 记录"有界 2 次复审 / 自检"中暂缓的大改项与已知待校准项，供后续专项处理。二期优先。

## A. 已知待校准（真实语义正确性）
- **跨板位号冲突**：多板产品中 `U1` 等在 A/B 板指不同器件；全局合并需按"板+位号"身份，D2/追踪/证据溯源要区分文件来源。（已在 merge/refdes_map 初版记录，待按文件隔离完善）
- **GND→VCC 桥接 trace 校准**：tracer 发现 GND 经 R98 跨到 VCCIO_PHY0；需金标核对是"真实网络"还是解析归属错误，再定 continue 规则细度。
- **契约枚举词表**：已对齐 raw（FOUND_PARTIAL/TRULY_MISSING 等）；新模型/新任务需持续监控 5 级判定/置信度枚举漂移。

## B. 规模与性能
- **芯片级拆分（P5）**：全量审查需按"每芯片一任务"拆分再并行(≤5)；当前直连短 prompt 逐 IC 可行，但整板 ~700 器件全量跑耗时长，建议正式全量运行前先按主控 IC 级联拆分。
- **网关长结构化 prompt 慢**（单 IC ≈44s）：已用直连短 prompt + mock 快速验证缓解；正式批量跑建议在网关空闲时段进行。
- **BOM 与 EDN 数量差**（EDN-only 411）：需确认 BOM 口径（关键器件/国产化清单），或按需补 BOM。

## C. 二期（自学习等，本期不做）
- learn/ 自学习回写（knowledge/ic_index/corrections/suggestions）
- 在线手册自动下载 → datasheet 分类归档的完整性校验
- OpenTelemetry/Langfuse 观测接入（可选）
- 上位机"上电时序图.json"独立 schema 落地
