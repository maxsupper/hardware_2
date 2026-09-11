# 新增 / 维护规则文件指南（rules/add_new.md）

> 面向**人**的说明文档。规则/数据的唯一事实源是 `raw/`（只读），`rules/` 全部是**派生资产**，
> 一律由脚本生成、幂等可重跑；**不要手改派生 JSON**。本文件不并入任何 `rules.json`。

---

## 1. 目录结构

```
raw/raw_platmform/<芯片>/          # 只读事实源（平台资料）
    hardware_check.md              #   检查规则（RK3588 / RK3576 / RV1126B）
    数据手册.md                    #   E2000 用此文件当规则源（PDF 文本转储）
    pinout.md  pinout.json         #   官方引脚表（pinout.json 为结构化权威源）

rules/
    rules.json                     # 通用规则单一事实源（人机同源；本指南不涉及）
    index.json                     # 总索引：common + platform + load_policy（由脚本生成）
    common/<中文主题>.json          # 通用规则文件（前缀 IC- 等）
    platform/<芯片>/
        rules.json                 # kind=platform_rules（进 LLM）
        rules_NN.json              #   仅当单芯片 tokens_est>20000 时拆分为多文件
        pinout.json                # kind=pinout_table（数据，**不进 LLM**）
        pinout.index.json          # 引脚/功能/球号 → 条目下标 的 O(1) 索引
```

生成/刷新脚本：`scripts/prepare_rules/platform_to_json.py`（**统一入口 + 逐芯片适配器**）

```bash
cd <repo>
PYTHONPATH=src .venv/bin/python scripts/prepare_rules/platform_to_json.py          # 增量（源未变则 skipped）
PYTHONPATH=src .venv/bin/python scripts/prepare_rules/platform_to_json.py --force  # 强制重写
PYTHONPATH=src .venv/bin/python scripts/prepare_rules/platform_to_json.py --chips RK3588,E2000
```

---

## 2. JSON「接收格式」（冻结，不得改动）

### 2.1 统一信封（所有产物）

```jsonc
{
  "schema_version": "1.0",
  "kind": "platform_rules | pinout_table",   // pinout.index.json 用 "pinout_index"
  "scope": "platform/RK3588",                // 归属：platform/<芯片>
  "source": "raw/raw_platmform/RK3588/hardware_check.md",
  "source_sha1": "<源文件 sha1>",             // 增量依据
  "generated_at": "2026-07-01T10:00:00+08:00",
  "tokens_est": 7430,                         // 预算护栏依据
  "entries": [ /* 规则条目 或 引脚条目 */ ]
}
```

约定：
- `tokens_est = int(len(源文本字符数) / 1.6)`。单文件芯片取**整份源文件**；拆分文件取**其覆盖的行区间**。
- `source_sha1` = 所消费源文件的 sha1（十六进制）。源未变 → 脚本 `skipped`（幂等）。
- `pinout.json` 额外带 `meta`（原 `meta` + 补 `source_sha1` / `generated_at`）。
- `pinout.index.json` 用 `by_pin` / `by_function` / `by_ball` 字段（无 `entries`）。

### 2.2 规则条目（`kind=platform_rules`）

```jsonc
{
  "id": "PF-RK3588-001",
  "title": "一、VCCIO 域定义",
  "stage": ["PH-2", "PH-3"],
  "gate": "G3",
  "params": {},
  "must": ["……必须……的完整句子"],
  "must_not": ["……禁止/不得/⛔……的完整句子"],
  "text": "该标题起、到下一处被切分标题前的完整原文（含标题行）",
  "refs": [{"src": "raw/raw_platmform/RK3588/hardware_check.md", "line": 13, "end_line": 32}]
}
```

- `title` = 标题原文；`text` = 该标题下的完整原文。
- `must` / `must_not`：从 `text` 中抽取含 **必须** / **禁止·不得·⛔** 的句子的原样列表（按出现顺序去重）。
- `refs[].line` / `end_line` 为**源文件 1-based 行号**（闭区间），便于回溯校对。
- 默认 `stage=["PH-2","PH-3"]`、`gate="G3"`；`params` 默认 `{}`。

### 2.3 引脚条目（`kind=pinout_table`）

```jsonc
{
  "pin": "U1",              // 键去 "__" 前缀（权威标识）
  "ball": "U1",             // 源 ball
  "functions": ["DDR_CH0_DQ0_A"],   // functions 字典的取值列表（f0..fn）
  "type": "I/O",            // 源 io_type
  "power_domain": "",       // 源 domain（缺失留空）
  "voltage": "",            // 源无此字段则留空，**不编造**
  "mux": "f0",              // 源 default_function（默认复用档）
  "notes": "pull=-; gpio=GPIO3_A0; schmitt=true"  // 其余源字段原样保留
}
```

- 缺失字段一律留**空串 / 空数组**，严禁编造。
- `by_function` 建立时，复合功能名（含 `/`）会按分名同时建索引，保证按单一功能名可 O(1) 命中。

### 2.4 索引（`kind=pinout_index`）

```jsonc
{
  "schema_version": "1.0", "kind": "pinout_index", "scope": "platform/RK3588",
  "source": "raw/raw_platmform/RK3588/pinout.json", "source_sha1": "…", "generated_at": "…",
  "by_pin":     {"U1": 0},
  "by_function": {"DDR_CH0_DQ0_A": [0]},
  "by_ball":    {"U1": 0}
}
```
只存**下标**，不重复存内容。

### 2.5 总索引（`rules/index.json`，`kind=rules_index`）

```jsonc
{
  "schema_version": "1.0", "kind": "rules_index", "generated_at": "…",
  "common":   {"<主题>": {"file": "common/<主题>.json", "prefix": "IC-", "stages": ["PH-2","PH-3"], "tokens_est": 0}},
  "platform": {"RK3588": {"rules": "platform/RK3588/rules.json",
                           "pinout": "platform/RK3588/pinout.json",
                           "pinout_index": "platform/RK3588/pinout.index.json",
                           "tokens_est": 7430, "pins": 1088,
                           "detect": {"model_regex": "RK3588", "min_pins": 544}}},
  "load_policy": {"PH-2": {"common": ["引脚核对"], "platform_rules": true, "pinout": false},
                   "PH-3": {"common": ["引脚核对","引脚电平检查","电源检查","接口电路检查","引脚复用关系"],
                            "platform_rules": true, "pinout": "on_demand"}}
}
```

- `platform.<芯片>.rules`：**单文件为字符串**；因超预算拆分时，为**文件路径数组**（按序）。
- `common.<主题>.file`：优先 `common/<主题>.json`；若不存在，则按主题词元（中文子串 + 英文词）**模糊匹配** `rules/common/` 下的实际文件并写入其真实文件名（例如 `证据schema` → `common/证据文件Schema规范.json`），匹配不到时回退预期名（不报错）。
- `platform.<芯片>.detect.min_pins` = `int(meta.total_entries × 0.5)`（无 `meta` 用 100）。
  真实项目主控 **RK3588M（889 引脚）**，故 RK3588 的 `min_pins` 必须 ≤ 889（当前 544）。

---

## 3. 如何新增一个规则文件

### 3.1 新增「平台」规则（派生自 `raw/raw_platmform/`）
1. 在 `scripts/prepare_rules/platform_to_json.py` 的 `CHIPS` 中登记芯片：`code` / `md` / `pinout` / `md_adapter`。
2. **先探查该芯片 md 与 pinout.json 的真实结构**（各芯片格式可能不同），必要时新增一个适配器函数并注册进 `MD_ADAPTERS`。
   - 规则切条：标题 → 条目；`text` 取该标题下的完整原文；抽 `must` / `must_not`。
   - 引脚：把源记录映射到 §2.3 的 8 个字段，缺失留空。
3. 运行脚本；脚本自动写 `rules/platform/<芯片>/` 三个文件并刷新 `rules/index.json`。
4. 校验：`tokens_est` 是否 ≤20000（超限须拆分，脚本自动做）；`entries` 数量是否与切条数一致；抽样比对 `refs` 行号。

### 3.2 新增「通用」规则（`rules/common/*.json`）
1. 约定主题名（中文）与 ID 前缀（默认 `IC-`）。
2. 在 `COMMON_TOPICS`（`platform_to_json.py`）中登记主题与适用阶段；若属于某个阶段加载策略，同步加入 `LOAD_POLICY`。
3. 生成 `rules/common/<主题>.json`（`kind=platform_rules`，信封同上）。索引中的 `common.<主题>.file` 会优先用同名文件，缺失时按词元模糊匹配实际文件（不报错）。
4. 重跑 `platform_to_json.py` 刷新 `rules/index.json` 的 `common.<主题>.tokens_est`（文件不存在时按 0 登记）。

---

## 4. ID 命名与前缀

| 类别 | 前缀 | 示例 | 说明 |
|---|---|---|---|
| 平台规则 | `PF-<芯片代号>-` | `PF-RK3588-001` | 3 位序号**全局递增**（跨拆分文件连续） |
| 通用规则 | `IC-`（默认） | `IC-007` | `common/*.json` |
| 通用规则（NG/DEV 等） | 见 `rules/rules.json` | `NG-006` / `DEV-009` | 由 `rules.json` 维护 |

- 平台规则 ID 由脚本按最终条目顺序生成，**不要手工改号**；新增芯片从 `-001` 起。
- 新增条目请追加到源 md（或对应的适配器数据源），重跑脚本即可。

---

## 5. source_sha1 / tokens_est / 预算护栏

- **source_sha1 增量**：脚本读取源文件字节算 sha1；与产物中记录一致且内容不变则不重写（打印 `SKIP`）。`--force` 强制重写。
- **tokens_est**：`int(字符数 / 1.6)`。示例：RK3588 `hardware_check.md` 整文件 = **7430**。
- **预算护栏 BUDGET_TOKENS = 20000**：
  - 单芯片规则 `tokens_est ≤ 20000` → 单文件 `rules.json`；
  - `> 20000` → 按标题层级**自动拆分** `rules_NN.json`（示例：E2000 `数据手册.md` 拆为 4 个分片），
    并在 `rules/index.json` 中以数组登记。
- **引脚数据不进 LLM**：`pinout.json` 体量大（RK3588 ≈ 15 万 tokens），由工具按 `pinout.index.json` **按需单条查询**，
  不要整体注入上下文（`load_policy` 中 `pinout=false | "on_demand"`）。
- 新增产物须在 `src/tools.md` 登记（由维护者统一登记）。
- **契约校验**：平台规则文件会调用 `src/hardware_analysis/models/rules_contracts.py` 的 `RuleBundle`
  （`extra="forbid"`，字段缺失/多余一律拒收）校验；若无该模型（或其 API 变化）则回退本脚本轻量校验。

---

## 6. 原则：md 格式不作要求，按实际 md 写适配器

- `raw/` 各芯片手册来源不同（markdown / PDF 文本转储 / Word 转出），**格式不被要求统一**。
- 转换器提供**逐芯片适配器**：
  - `markdown`：标准 `##` / `###` 标题；`####` 及以下视为正文（不切）。
  - `e2000_datasheet`：PDF 文本转储无 markdown 标题，用编号标题探测器
    （`^\d+(\.\d+)*\s+标题`，过滤量词表格行 / TOC 点线行 / 页眉重复），正文从最后一个 TOC 点线行之后起算。
- 切条采用**连续不重叠**语义：每块从标题行到下一处被切标题前，避免父标题重复包含子标题正文、token 翻倍。
- 新增源格式时，**先探查再写适配器**，不要假设格式一致。

---

## 7. 可复制模板

### 7.1 规则文件模板（`rules/platform/<芯片>/rules.json` / `rules/common/<主题>.json`）

```json
{
  "schema_version": "1.0",
  "kind": "platform_rules",
  "scope": "platform/<芯片>",
  "source": "raw/raw_platmform/<芯片>/hardware_check.md",
  "source_sha1": "<sha1>",
  "generated_at": "2026-07-01T10:00:00+08:00",
  "tokens_est": 1234,
  "entries": [
    {
      "id": "PF-<芯片代号>-001",
      "title": "<标题原文>",
      "stage": ["PH-2", "PH-3"],
      "gate": "G3",
      "params": {},
      "must": ["<含『必须』的完整句子>"],
      "must_not": ["<含『禁止/不得/⛔』的完整句子>"],
      "text": "<该标题下的完整原文>",
      "refs": [{"src": "raw/raw_platmform/<芯片>/hardware_check.md", "line": 13, "end_line": 32}]
    }
  ]
}
```

### 7.2 引脚数据模板（`pinout.json`）

```json
{
  "schema_version": "1.0",
  "kind": "pinout_table",
  "scope": "platform/<芯片>",
  "source": "raw/raw_platmform/<芯片>/pinout.json",
  "source_sha1": "<sha1>",
  "generated_at": "2026-07-01T10:00:00+08:00",
  "tokens_est": 150000,
  "meta": {"platform": "<芯片>", "total_entries": 1088, "source_sha1": "<sha1>", "generated_at": "…"},
  "entries": [
    {"pin": "U1", "ball": "U1", "functions": ["DDR_CH0_DQ0_A"],
     "type": "I/O", "power_domain": "", "voltage": "", "mux": "f0", "notes": "pull=-"}
  ]
}
```

### 7.3 引脚索引模板（`pinout.index.json`）

```json
{
  "schema_version": "1.0",
  "kind": "pinout_index",
  "scope": "platform/<芯片>",
  "source": "raw/raw_platmform/<芯片>/pinout.json",
  "source_sha1": "<sha1>",
  "generated_at": "2026-07-01T10:00:00+08:00",
  "by_pin": {"U1": 0},
  "by_function": {"DDR_CH0_DQ0_A": [0]},
  "by_ball": {"U1": 0}
}
```
