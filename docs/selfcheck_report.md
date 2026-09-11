# 自检报告（FL-25-E-MR203）

> 生成时间 1789116834s | 通过 10/10

| 检查 | 状态 | 说明 | 证据 |
|---|---|---|---|
| L1-edn_parse(真实) | PASS | 全局元件=952 网络=802 | global_components.json/global_nets.json |
| L1-gate(G1) | PASS | G1 状态 | gates/G1.json -> PASS |
| L1-gate(G2) | PASS | G2 状态 | gates/G2.json -> PASS |
| L1-NG-006 邻接等值 | PASS | 派生邻接 vs 基准：EQUIVALENT（比对 4131 引脚） | docs/evidence/adjacency_baseline_FL-25-E-MR203.json 不等=0 缺失=0 |
| L2-负向-fault注入(G4缺报告) | PASS | report.json 缺失 → G4 应 FAIL | PH-4_报告合成/report.json |
| L2-负向-恢复 | PASS | 删除后恢复 report.json | report.json 存在 |
| L3-budget | PASS | 规则束40K估算=26666 | budget_validator |
| L3-溯源-反向验证 | PASS | 遗留/重复/错位 全 0 | reverse_check.json |
| L3-可复现-mock | PASS | report.json md5=56e1385f | 确定性 MOCK 产物 |
| L3-产出齐全 | PASS | 84 个产物文件 | PH-0_输入准备; PH-1_手册检索; PH-2_网表解析; PH-3_深度分析; PH-4_报告合成; PH-5_审计复核; PH-6_闭环交付; gates; run_manifest.json |