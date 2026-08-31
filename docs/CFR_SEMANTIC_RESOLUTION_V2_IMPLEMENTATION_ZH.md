# CFR Entity-first Semantic Resolution V2 实施方案

> 对应包版本：`0.7.0`  
> 注册表：`material-semantic-registry/2.0.0`  
> 实施状态：V2 基线已落地并完成自动化回归；持久化 Semantic Index 与审核式 ProxyEdge Registry 属于后续扩展。

## 1. 决策结论

最终方案采纳“实体优先、修饰词结构化、身份准入先于评分”的方向，但不把它实现成删除停用词或无限扩张的名称词典。

系统现在先回答“请求指向哪个材料实体”，再回答“目录中有哪些可比较记录”。完整路径为：

```text
INPUT
  → VALIDATE
  → NORMALIZE TEXT
  → PARSE MATERIAL MENTION
  → RESOLVE ENTITY IDENTITY
  → BUILD RETRIEVAL INTENT
  → LOCAL SEMANTIC INDEX RETRIEVAL
  → CANDIDATE ADMISSION / QUALIFICATION
  → GAP ANALYSIS / BOUNDED RESOLUTION
  → CANDIDATE POOL → RANK → TOP-K
  → HUMAN APPROVAL → LOCK
```

本地仍无合适候选时，Graph 才进入 Material Resolution 与技术合理的 Proxy Resolution。Material Class 不提前替代实体识别，LLM 也不能生成排放因子数值。

## 2. 为什么必须修改 Normalize 契约

旧契约主要输出 `canonical_name`、aliases、product form、composition 和 process。它可以处理简单标准化，却不能稳定区分：

- `金属铝`、`氧化铝`、`铝合金`和`铝矾土`；
- `金属硅`、`二氧化硅`和`碳化硅`；
- 基础材料、生产工艺、产品形态、纯度、牌号和组成成分；
- 单一材料与多组分复合材料。

当请求与来源都未被识别时，旧 Related Recall 可能依靠共同中文片段召回错误材料。例如“金属铝”和“金属硅粉”共享“金属”，但其基础实体不同。下游低分或 `REFERENCE_ONLY` 只能降低展示级别，不能修复错误准入。

因此 V2 将 Normalize 变成身份解析管道，并把词面相似度降为“未识别时提出待审实体建议”的辅助信号，不允许它直接产生排放因子候选。

## 3. 语义角色与解析结果

### 3.1 角色集合

| 角色 | 含义 | 示例 |
|---|---|---|
| `BASE_ENTITY` | 基础材料实体 | 铝、莫来石、钢 |
| `ENTITY_TYPE` | 元素金属、氧化物、合金等类型限定 | 金属、氧化物 |
| `PROCESS` | 制造过程 | 电熔、烧结、煅烧 |
| `PRODUCT_FORM` | 产品形态 | 纤维、砖、粉、锭 |
| `GRADE` | 明确牌号 | 70、80、90 或系列牌号 |
| `GRADE_MODIFIER` | 牌号/质量修饰 | 高纯 |
| `PURITY` | 可量化纯度 | 95% |
| `COATING` | 镀层或表面处理 | 镀铜 |
| `ROUTE` | 原生、再生等路线 | 原铝、再生铝 |
| `APPLICATION` | 用途限定 | 钢包用 |
| `CONSTITUENT` | 复合材料组成 | 莫来石、碳化硅 |

### 3.2 典型解析

```text
金属铝
  金属 → ENTITY_TYPE
  铝   → BASE_ENTITY
  base_entity_id = mat.element.aluminium
  entity_type    = ELEMENTAL_METAL
  formula        = Al

钢纤维
  钢   → BASE_ENTITY
  纤维 → PRODUCT_FORM
  base_entity_id = mat.alloy.steel

电熔莫来石
  电熔   → PROCESS
  莫来石 → BASE_ENTITY
  base_entity_id = mat.mineral.mullite

95%高纯镁砂
  95%  → PURITY
  高纯 → GRADE_MODIFIER
  镁砂 → BASE_ENTITY

莫来石-碳化硅砖
  莫来石、碳化硅 → CONSTITUENT
  砖              → PRODUCT_FORM
  entity_type     = COMPOSITE
```

`金属`不是停用词。它不替代基础实体，但参与消歧：`硅 + 金属` 指向 elemental silicon，`硅 + 氧化物` 指向 silica，`硅 + 碳化物` 指向 silicon carbide。

## 4. 已实施的数据契约

### 4.1 MaterialMention

保存原始/规范化文本、带字符区间的语义 span、基础实体文本、实体类型提示、化学式、工艺、形态、牌号、纯度、镀层和多组成分。字符区间只指向请求名称内真实出现的文本，结构化请求字段不会伪造 span。

### 4.2 IdentityResolution

核心字段包括：

```text
outcome                    RESOLVED / PARTIAL / AMBIGUOUS / CONFLICT / UNKNOWN
selected_entity_id         基础实体 ID
selected_product_entity_id 可选产品/路线实体 ID
product_family_id          产品族 ID
proof_type                 主名称、审核 Alias、结构化实体、复合组成等
evidence_ids               命中的审核规则/证据 ID
alternatives               歧义候选
conflicts                  冲突说明
```

只有有充分证明的 `RESOLVED` 身份才能走 Same-Entity Related。UNKNOWN 与 UNKNOWN 不再被视为“没有发现冲突所以可用”。

### 4.3 RetrievalIntent

Repository 不再接收一个裸 `canonical_name` 扫描目录，而是接收：

```text
entity_id
allowed_entity_ids
aliases
entity_type
process
product_form
grade
purity
route
constituent_entity_ids
```

当请求含 process、form 或 purity 限定时，不把无条件基础材料 alias 当成完整产品同义词；同一实体的不同工艺/形态进入 Related 与 Gap Analysis。

### 4.4 CandidateAdmission

每条被评估的检索记录都形成确定性准入账本：

```text
source_id
retrieval_strategy
admitted
observation_only
identity_proof_ids
source_identity_rule_ids
hard_exclusions
```

它回答“为什么这条记录能或不能进入候选池”。评分发生在准入之后；模型判断和名称相似度不能绕过硬条件。

## 5. 注册表与实体模型

Registry V2 是可版本化、可审核的语义数据层，不是排放因子数据库。当前内置覆盖包括莫来石、尖晶石、铝硅酸盐、刚玉、镁砂、钢，以及铝/硅相关的元素、氧化物、碳化物、铝土矿和产品路线。

铝实体组示例：

```text
mat.element.aluminium
  ├─ mat.product.primary_aluminium
  ├─ mat.product.secondary_aluminium
  ├─ mat.product.aluminium_ingot
  └─ mat.alloy.aluminium

mat.compound.alumina       # 氧化铝，不是金属铝候选
mat.mineral.bauxite        # 铝土矿，不是金属铝候选
```

单字中文 alias 采用受控上下文。`钢`只在完整名称或明确产品形态等受控环境中识别，因此`钢纤维`可解析，而`钢包用透气元件`不会被误判为钢材料。

新材料问题按以下闭环解决：

```text
未识别请求
  → 形成 UNKNOWN/AMBIGUOUS Trace
  → LLM 只提出结构化 DRAFT 建议
  → 人工核对实体、alias、类型、组成和关系
  → 加入 gold-set 与负例回归
  → 发布新 registry version/SHA
  → Semantic Index 自动重建
```

不需要为每个新材料修改 Graph 或增加散落的 `if`。

## 6. Semantic Index

### 6.1 建立方式

`SemanticFactorIndex` 在目录载入时使用同一 Registry 预解析每个 `SourceRecord`，形成实体到来源记录的索引。当前实现为进程内缓存，不修改正式 SQLite 数据库。

索引锚点包含：

- 正式因子目录版本与 SHA-256；
- Registry version 与 SHA-256；
- 索引内容 digest 与 record count；
- 由上述锚点生成的 semantic index version。

目录或 Registry 更新时，HTTP Adapter 缓存键改变并重建索引。由此可以解释相同请求在更新前后的召回、排除和排名差异。

### 6.2 检索层级

```text
1. Exact Primary Name
2. Reviewed / Catalogue Alias
3. Same Base Entity Variant
4. Reviewed technical Proxy（当前仍由后置 Proxy Repository 承担）
5. Unresolved / supplier data / process model
```

前三层属于本地目录身份检索。第 3 层必须满足请求和来源实体都已解析、`base_entity_id` 完全相等。工艺词、形态或字符重合只能形成观察或 Gap，不能证明实体相同。

## 7. Graph 与 Router 行为

Graph 主拓扑没有因材料种类而膨胀。V2 把结构化语义结果放进 State，由既有 Router 消费：

```text
Normalize
  writes MaterialMention / IdentityResolution / RetrievalIntent

Local Retrieval
  reads RetrievalIntent
  writes SourceRecords / LinkAttempts / SemanticIndexAnchor

Local Evaluate
  writes Qualifications / CandidateAdmissions / Exclusions

Gap Analysis
  turns same-entity process/form/grade differences into structured gaps

Material Resolution / Proxy Resolution
  runs only after target-entity local paths are insufficient
```

通用铝请求若同时命中原铝与再生铝，不允许排序器替用户决定路线，而是生成 `RequestGap(field="route")`，返回 `MORE_INPUT_NEEDED`。用户补充路线后可形成新的规范化请求与 Trace。

## 8. LLM 与确定性边界

LLM 可以：

- 对 UNKNOWN/AMBIGUOUS 名称提出实体、组成、工艺或牌号建议；
- 对已限定候选补充语义适用性判断和局限；
- 帮助生成待审 Registry/ProxyEdge 草案。

LLM 不可以：

- 凭空给出排放因子或能源参数；
- 自动发布 alias、same-as 或 Proxy 关系；
- 绕过 Entity/FactorKind/indicator/boundary/unit/provenance 硬门；
- 决定单位换算、确定性公式、排名稳定规则或锁定结果。

## 9. Trace 可回答的问题

V2 的可更新 Trace 保留以下答案：

- 使用了哪个正式因子库版本与 SHA；
- 使用了哪个 Registry 与 Semantic Index 版本；
- Parser 把各文本片段解释成什么角色；
- 选择了哪个 entity/product entity，证明来自哪些规则；
- Local Exact/Alias/Same-Entity 各自查到了什么；
- 哪些记录只作为 observation，哪些通过 Candidate Admission；
- 为什么进入 Process/Grade/Proxy 路径；
- 哪些候选被排除以及 hard exclusion；
- 最终候选如何排名、有哪些 Gap/Assumption/Limitation；
- 目录或 Registry 更新后，相同业务请求为何得到不同结果。

本阶段遵循“可更新 Trace + 数据库版本锚点”，不建立不可变 Trace 快照；最终人工审批与 LockedResolution 仍按既有锁定契约执行。

## 10. 关键验收行为

### 10.1 金属铝安全性

对仅含“金属硅粉”和“氧化铝”的目录查询`金属铝`：

```text
identity = mat.element.aluminium
local_records = 0
candidates = 0
status = SUPPLIER_DATA_REQUIRED
```

系统不会把硅或氧化铝作为低质量铝候选返回。

### 10.2 路线歧义

目录同时有原铝与再生铝时查询`金属铝`：

```text
status = MORE_INPUT_NEEDED
required_choice.field = route
options = primary_aluminium / secondary_aluminium / unknown
```

### 10.3 工艺差值兼容

`电熔莫来石`仍可召回同一 mullite 实体的烧结记录，但策略为 Same-Entity Related，而非把“莫来石”当成完整产品同义词。随后由 Process Gap 与有来源的能耗参数决定是否可进行工艺差值计算。缺少完整参数时保留未调整参考值及局限，禁止生成伪精确值。

### 10.4 复合材料与上下文

- `莫来石-碳化硅砖`保留 mullite 与 silicon carbide 两个 constituent ID；
- `锆莫来石`保留 zirconia 与 mullite；
- `钢包用透气元件`保持 UNKNOWN，不因单字“钢”误判。

## 11. 测试与发布门槛

当前自动化覆盖：角色解析、复合组成、单字上下文负例、铝/硅/氧化物跨实体隔离、通用铝路线选择、同实体工艺变体、资格政策、因子种类、单位、过程/牌号解析、Trace 与锁定不变量。

每次 Registry 或目录映射更新至少应执行：

1. 正向实体 gold-set；
2. 跨元素、元素/氧化物、原生/再生、复合材料负例；
3. Exact/Alias/Same-Entity 分层测试；
4. 候选准入与排除 Trace 测试；
5. 全量 pytest、compileall 与 Ruff I/F；
6. 正式目录锚点下的只读 smoke test。

## 12. 已落地与后续范围

| 能力 | 当前状态 |
|---|---|
| 结构化 MaterialMention | 已落地 |
| Entity/Product/Family ID | 已落地 |
| Identity proof/outcome | 已落地 |
| RetrievalIntent Repository 契约 | 已落地 |
| 共享、版本锚定的进程内 Semantic Index | 已落地 |
| Entity-gated Related 与 CandidateAdmission | 已落地 |
| 铝/硅/氧化物/碳化物/复合材料关键规则 | 已落地 |
| 通用实体多路线追问 | 已落地 |
| 正式目录物理持久化 semantic tables | 后续；不影响当前 API 接入 |
| 审核式 ProxyEdge Registry | 后续；不得由 LLM 自动发布 |
| 全目录 177 条记录人工语义治理 | 后续按域分批完成 |
| 生产级 LLM Parser/候选判断 Adapter | 后续，必须受 bounded schema 与准入门约束 |

## 13. 文件落点

| 文件 | 职责 |
|---|---|
| `src/a1_factor_engine/models.py` | 语义角色、Mention、Identity、Intent、Index Anchor、Admission、State/Trace 合同 |
| `src/a1_factor_engine/material_registry.py` | Registry V2、实体/alias/工艺/形态规则、复合解析、来源 enrichment |
| `src/a1_factor_engine/semantic_index.py` | 目录预解析与 Exact/Alias/Same-Entity 索引 |
| `src/a1_factor_engine/adapters.py` | 内存/HTTP Repository 的共享索引接入与缓存 |
| `src/a1_factor_engine/nodes.py` | Normalize、Local Retrieval/Evaluate、候选准入 Trace |
| `src/a1_factor_engine/qualification.py` | Direct/Related/Proxy/Grade 统一资格政策 |
| `tests/test_engine.py` | 正向与对抗回归 |

## 14. 最终原则

CFR 不再把“能搜到相似名称”当成“有资格成为因子候选”。实体身份、来源记录资格和数值可追溯性是三个独立门槛：

```text
Identity Proof
  ∧ Record Qualification
  ∧ Numeric Provenance
  → Candidate
  → Deterministic Ranking
```

如果 Local、同实体变体和有审核依据的 Proxy 都无法闭合，系统明确进入 `UNRESOLVED`、`PROCESS_MODEL_REQUIRED` 或 `SUPPLIER_DATA_REQUIRED`，而不是无限检索、跨实体猜测或生成没有来源的排放因子。
