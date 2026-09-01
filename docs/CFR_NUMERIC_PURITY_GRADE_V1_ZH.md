# CFR 实体作用域数字纯度牌号 V1

> 对应实现：A1 Factor Resolution Engine `0.8.0`  
> 语义注册表：`material-semantic-registry/2.2.0`
> 文档日期：2026-08-21

## 1. 目标与边界

本能力解决耐火材料和工业原料名称中常见的 `70/80/90` 数字牌号。系统在材料实体已唯一解析时自动应用已审核的材料作用域规则，减少无必要追问；同时不把裸数字伪装成精确化学组成、最低含量或排放因子调整依据。

核心不变量：

- 先解析材料实体，再解释数字；
- 显式组成证据优先于名称牌号；
- 裸数字只能由唯一适用的已发布 Grade Schema 绑定；
- 请求与正式因子记录使用同一 Parser；
- 来源未声明 Grade 时只形成 Grade Proxy/Reference，并保留局限；
- 不从牌号生成、缩放或插值排放因子；
- 多组分材料无法确定数字作用对象时才追问。

## 2. 数据契约

### 2.1 NumericTokenResolution

每个有语义的数字片段保留原文、字符区间、角色、规则证据、被拒绝角色和解释。角色包括：

- `PURITY_GRADE`
- `PARTICLE_SIZE`
- `GRIT_SIZE`
- `MODEL_CODE`
- `ALLOY_GRADE`
- `STANDARD_NUMBER`
- `YEAR`
- `PACKAGING`
- `UNRESOLVED`

系统禁止“没有识别为 Grade 就直接丢弃数字”。负例角色同样会限制检索和候选资格。

### 2.2 PurityGrade

结构化 Grade 至少包含：

- `grade_value`
- `basis_component_id`
- `interpretation_kind`
- `schema_id` / `schema_version`
- `evidence_scope` / `evidence_ids`
- `parser_rule_ids`
- 可选的 `specification_operator`、上下限或 nominal 值
- `ordered`，表示该 Grade Schema 是否支持有序比较

`IMPLICIT_GRADE_CLASS` 只表示在某个已审核业务 schema 中的 70/80/90 级别。它不等价于 `MgO = 90%` 或 `MgO ≥ 90%`。

### 2.3 PurityGradeSchema

Schema 是可版本化注册表数据，不是 Graph 中持续增加的 `if`。其作用域由 entity IDs、basis component、允许牌号、证据作用域、证据 IDs、标签前缀、优先级和发布状态共同限定。只有 `ACTIVE` Schema 影响运行时。

## 3. 确定性优先级

```text
1. 显式组成：MgO ≥ 95%、Al2O3 90、95%
2. 已审核供应商/产品前缀：例如 AR78、AR90
3. 已审核标准 Schema
4. 组织业务默认 Schema：实体作用域内的 70/80/90
5. 无唯一作用域：UNRESOLVED / numeric_grade_basis
```

若结构化 `composition` 与名称牌号冲突，`composition` 优先。例如名称为 `烧结镁砂90`、composition 为 `MgO ≥ 95%`，最终目标是带 `MINIMUM` 操作符的显式 95，而不是隐式 90。

## 4. 当前组织默认规则

| 材料实体 | 默认 basis | 裸牌号示例 | 解释类型 |
|---|---|---|---|
| magnesia | MgO | 70/80/90 | IMPLICIT_GRADE_CLASS |
| spinel | Al2O3 | 70/80/90 | IMPLICIT_GRADE_CLASS |
| corundum/alumina/bauxite/mullite | Al2O3 | 70/80/90 | IMPLICIT_GRADE_CLASS |
| silicon carbide | SiC | 70/80/90 | IMPLICIT_GRADE_CLASS |
| aluminium | Al | 70/80/90 | IMPLICIT_GRADE_CLASS |
| silicon metal | Si | 70/80/90 | IMPLICIT_GRADE_CLASS |

这些是显式带组织证据 ID 的业务规则。后续若行业标准或供应商规范覆盖某一实体，应新增更高优先级且经过审核的 Schema、回归测试并发布新的注册表版本，不修改 Graph 路由。

## 5. 反例保护

| 输入 | 数字角色 | 处理 |
|---|---|---|
| F80碳化硅、P80白刚玉 | GRIT_SIZE | 不解释为纯度；通用 alias 不得形成 Direct |
| T60板状刚玉、CT800氧化铝 | MODEL_CODE | 不解释为纯度 |
| AISI 446钢纤维、6061铝合金 | ALLOY_GRADE | 保留合金牌号语义 |
| 90烧结镁砂 0-3mm | PURITY_GRADE + PARTICLE_SIZE | 两类数字独立保存 |
| GB/T 1234-2020 | STANDARD_NUMBER | 不解释为纯度或年份牌号 |
| 25kg/袋 | PACKAGING | 不解释为纯度 |
| 莫来石-碳化硅砖90 | UNRESOLVED | 询问 `numeric_grade_basis` |

## 6. Graph 集成

```text
Normalize Text
  → Parse Material Mention
  → Resolve Base Entity
  → Classify Numeric Tokens
  → Bind Grade Schema when unique
  → Build RetrievalIntent
  → Entity Index Retrieval
  → Candidate Qualification
  → Structured Grade Gap
  → Grade Router（一次、有界、确定性）
  → Rank / Top-K / Human Approval
```

Material Class 仍只在本地同实体检索不足之后指导 Proxy Resolution，不因数字牌号提前进入 Proxy 路由。

## 7. 来源记录与候选准入

`SourceRecord` 在建 Semantic Index 前通过同一注册表富化。请求 Grade 与来源 Grade 的比较顺序为：

1. 来源是否有可解析 Grade；
2. schema ID 是否一致；
3. basis component 是否一致；
4. grade value 是否一致；
5. Grade Anchor 的 factor kind、indicator、边界、单位和 provenance 是否合格。

来源没有 Grade 时，候选可作为有局限的 `GRADE_PROXY` 或 `REFERENCE_ONLY`，但不能成为无差异 Direct。不同 schema/basis 比单纯数值差异严重，不能只比较 80 与 90 的大小。

## 8. Trace 与版本锚点

Trace 可回答：

- 哪个数字被识别成什么角色；
- 使用了哪个 Grade Schema、版本、basis 和证据；
- 哪些可能角色被拒绝以及原因；
- 正式因子库、注册表和 Semantic Index 分别是哪一版；
- 来源 Grade 是否缺失或与请求不同；
- 候选为何降为 Grade Proxy/Reference Only；
- 70、80、90 的相同材料请求为何具有不同规范化业务指纹；
- 数据库或注册表更新后候选和排名为何变化。

Trace 是可更新记录并锚定数据库/注册表版本，不创建不可变 Trace 快照。

## 9. 验收行为

自动化回归覆盖：

- magnesia、spinel、corundum 的 70/80/90 自动绑定；
- 显式 percentage 和无 `%` 化学式值的优先级与操作符；
- 粒度、型号、合金牌号等对抗性负例；
- Grade 与粒度同时出现；
- 请求 90、来源 80 形成 Grade Gap；
- 显式 composition 不产生重复 Grade Gap；
- 数字限定词不能被通用 alias 擦除；
- 多组分材料只在 basis 不唯一时追问；
- 70 与 90 形成不同规范化业务指纹。

正式目录测试必须只读取数据库端口，并在 Trace 中保存正式数据库 SHA。目录未提供来源 Grade 时，系统不得声称完成牌号校正，也不得生成新因子值。

## 10. 后续治理

遇到新材料或新牌号时，按以下流程增量发布：

```text
失败样例
  → 数字角色标注
  → 实体与 basis 审核
  → Grade Schema 草案
  → 正反例回归测试
  → ACTIVE 发布与注册表版本升级
  → Semantic Index 自动重建
```

供应商牌号必须绑定供应商/产品作用域和原始证据，不能升级为全行业默认。无法证明顺序关系的 Schema 必须 `ordered=false`，不得插值。真实来源 Grade 字段治理完成前，Top-K 应向用户展示候选来源、适用理由和 Grade 局限，而不是追求伪精确单值。
