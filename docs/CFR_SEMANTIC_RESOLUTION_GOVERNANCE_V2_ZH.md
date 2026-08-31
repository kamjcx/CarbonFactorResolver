# CFR 语义解析现状诊断与彻底治理方案 V2

> 文档对象：A1 Factor Resolution Engine（CFR）当前 `0.6.0` 实现及下一阶段语义架构<br>
> 文档日期：2026-08-20  
> 基线注册表：`material-semantic-registry/1.0.0`  
> 正式因子目录：`factor-catalog-v0.2.1`，177 条记录  
> 正式因子库 SHA-256：`799bff31f6cae963d07441b2ac8f7439f27628fef0f9586bbc5f5e38b8434e06`  
> 文档性质：现状审计、目标架构、数据契约、迁移路线和验收标准；本文不直接修改运行时代码

## 1. 执行结论

当前 CFR 已经具备一个正确的语义治理雏形：版本化注册表、ACTIVE/DRAFT 状态、Material/Process/Form 分层规则、Typed Relations、Trace 可见规则 ID，以及“LLM 建议不能自动发布”的边界。这些设计应保留。

但是，当前实现仍属于“受治理的小型规则集”，尚未成为能够稳定支撑正式因子检索的材料语义基础设施。`金属铝 → 金属硅粉` 误召回不是单一词条缺失，而是四个边界同时偏松：

1. **身份识别不完整**：金属铝和金属硅都没有稳定的材料实体 ID；
2. **Related Recall 过宽**：中文二元字片段只要共享“金属”即可召回；
3. **资格准入不充分**：unknown-vs-unknown 不会形成材料冲突，材料匹配为 0 也没有被硬阻断；
4. **终态判定偏宽**：任何已排名候选都可让状态成为 `recommendation_ready`，即便它只是身份不成立的 `REFERENCE_ONLY`。

彻底解决不能依靠不断增加 `if` 或扩大同义词表，而应建立以下闭环：

```text
文本标准化
  → 材料提及结构化解析
  → 版本化材料实体注册表
  → 身份候选与冲突判定
  → 分层检索（Exact / Alias / Same-Entity Related / Reviewed Proxy）
  → 确定性 Candidate Admission
  → Gap Resolution
  → Rank / Top-K
  → Human Approval
  → 未识别样本回流、规则审核、回归测试、版本发布
```

其中必须坚持三个核心不变量：

- **召回证据不等于身份资格**：词面、embedding 和 LLM 相似度只能扩大观察集，不能单独让候选进入 Candidate Pool；
- **材料类别不等于 Proxy 关系**：METAL 与 METAL 不是可替代证明，铝和硅都属于金属也不能互为 Proxy；
- **Score 只排序已准入候选**：不得用低分代替硬排除，也不得让缺失维度的“中性分”掩盖材料身份冲突。

## 2. 当前系统语义链路

### 2.1 当前 Graph 中的位置

当前主流程保持了“直接数据优先，Material Class 仅在后备路径使用”的正确业务原则：

```text
INPUT
  → VALIDATE
  → NORMALIZE + Semantic Registry
  → LOCAL RETRIEVAL
      exact_link
      synonym_link
      related_candidate_recall
  → LOCAL EVALUATE / Qualification
  → GAP ANALYSIS
  → RESOLUTION PLANNER
  → Unit / Reference Flow / Process / Grade Routers
  → 若仍需要材料 Proxy
      MATERIAL RESOLUTION
      CLASS-AWARE PROXY RETRIEVAL
      PROXY EVALUATE
  → CANDIDATE POOL
  → RANK
  → TOP-K
```

这个路由顺序本身不需要推翻。问题主要位于 Normalize、Related Recall、Qualification、Candidate Admission 和 Top-K Status 的契约之间。

### 2.2 当前文本标准化

`normalize_text()` 当前执行：

- Unicode NFKC；
- 大小写归一；
- 常见分隔符转空格；
- 连续空白折叠。

优点是规则确定、带版本 ID、Trace 可见。局限是尚未覆盖：

- 化学式规范化，如 `Al₂O₃ / Al2O3 / 氧化铝`；
- 元素符号和普通英文单词的歧义，如 `Al`；
- 牌号、纯度、再生含量、状态、涂层的结构化抽取；
- 中文领域词边界；
- 行业上下文词与材料词的区分，如“钢包”中的“钢”不是产品材料；
- 组合材料的多实体解析，如“莫来石-碳化硅砖”。

### 2.3 当前 Material Semantic Registry V1

V1 注册表包含四类对象：

- `MaterialRule`；
- `ProcessRule`；
- `FormRule`；
- `TypedRelation`。

当前内置 Material Rule 仅覆盖：

| Head Material | Family | 类别 |
|---|---|---|
| mullite | mullite_products | MANUFACTURED_MINERAL |
| spinel | spinel_products | MANUFACTURED_MINERAL |
| aluminosilicate | aluminosilicate_refractory | MANUFACTURED_MINERAL |
| alumina | alumina_products | MANUFACTURED_MINERAL |
| corundum | corundum_products | MANUFACTURED_MINERAL |
| magnesia | magnesia_products | MANUFACTURED_MINERAL |
| steel | steel_products | METAL |

当前匹配机制是“别名包含 + 最长别名优先”。中文别名直接使用子串包含；英文别名使用近似单词边界。

注册表的优点：

- 规则具有 `rule_id` 和版本；
- 只有 `ACTIVE` 规则参与运行；
- DRAFT 建议不能自动影响结果；
- Request 和 SourceRecord 共用同一个注册表；
- Material、Process、Form 不再全部混在名称判断中；
- Trace 保存命中的规则与关系 ID。

注册表的局限：

- 一个输入只选择一个 MaterialRule，不能表达多组分材料；
- 没有稳定的 `entity_id`、化学实体 ID、CAS/EC/内部主数据 ID；
- 别名没有匹配模式、语言、词边界、上下文、排除条件和歧义组；
- 单字别名可能造成强假阳性，例如 `钢包` 命中 `钢`；
- Typed Relations 当前主要作为 Trace 元数据，并未成为检索/资格的可执行约束；
- 没有 `NOT_SAME_AS`、`COMPOSED_OF`、`FEEDSTOCK_FOR`、`VALID_PROXY_FOR` 等关键关系；
- 没有将“元素、氧化物、矿石、合金、制成品、能源载体”严格区分为不同实体层级；
- 未识别材料统一给出 `confidence=0.4`，但 confidence 不能表达歧义、冲突和证据类型。

### 2.4 当前正式目录覆盖情况

使用当前注册表对正式目录 177 条记录进行只读解析：

```text
充分识别：37
UNKNOWN：140
表面覆盖率：20.9%
```

37 条已识别记录分布：

| Head Material | 数量 |
|---|---:|
| mullite | 8 |
| corundum | 7 |
| alumina | 7 |
| aluminosilicate | 6 |
| magnesia | 4 |
| spinel | 3 |
| steel | 2 |

20.9% 还是一个偏乐观的数字，因为其中存在假阳性：

- `钢包用透气元件` 因包含单字“钢”被识别为 steel；
- `锆莫来石` 被压扁为 mullite，丢失 zirconia 组分；
- `莫来石-碳化硅砖` 被压扁为 mullite，丢失 silicon carbide 组分。

此外，能源载体、电力、运输、氧化锆、铝矾土、粘土、树脂、石墨、硅石、碳化硅、水泥等大量正式记录尚未进入注册表。需要注意：能源和运输应先按 Factor Domain/Kind 分流，不应为了提高“材料注册表覆盖率”而强行全部塞进材料本体。

### 2.5 当前 Related Recall

Related Recall 的核心逻辑是：

1. 若 Request 和 Source 都有已知 `head_material` 且相同，则召回；
2. 若产品形态相同，则召回；
3. 否则对英文词或中文二元字片段求交集，只要有交集就召回。

中文示例：

```text
金属铝   → {金属, 属铝}
金属硅粉 → {金属, 属硅, 硅粉}
交集     → {金属}
```

因此“金属”这个通用类别词足以产生 Related candidate。当前没有：

- stop-term / 通用词过滤；
- 术语权重或 IDF；
- 最小覆盖率；
- 元素冲突检测；
- 结构化实体一致性门槛；
- 多词组合证据；
- 负关系和禁止关系。

产品形态相同也不能证明材料相关。例如“两种粉末”或“两种纤维”不必然属于同一材料。

### 2.6 当前 Qualification

共用 Qualification Policy 会比较：

- material category；
- material family；
- head material；
- factor kind；
- indicator；
- declared product；
- boundary；
- unit；
- Grade Anchor 专用 series/provider/process 等条件。

已知的 category/family/head 冲突在 Direct 策略下会被硬排除，这是正确的。但比较函数对缺失值采取“跳过”：只要目标或来源一方为空，就不产生 mismatch。

因此：

```text
金属铝：head_material=None, category=UNKNOWN
金属硅：head_material=None, category=UNKNOWN
```

两者比较结果不是 MISMATCH，而是 UNKNOWN。UNKNOWN 当前不会自动形成身份排除。

### 2.7 当前 Scoring、Gap 和 Top-K

候选评分包含 material/process/form/composition/geography/time/boundary。缺少目标或来源字段时，多个维度会得到中性值 `0.5`。这对“已通过资格的候选排序”可以接受，但不能用于准入。

Related candidate 如果材料不同，会产生：

```text
MATERIAL_ABSENT_GAP
severity = 1.0
resolvable_by = CLASS_AWARE_MATERIAL_PROXY
```

这是有价值的 Gap 表达，但当前缺少一个先决问题：这个候选是否拥有成为 Proxy 的技术资格。如果没有显式 Proxy 关系，`MATERIAL_ABSENT_GAP` 不能自动把任意词面相近记录升级成 Generic Proxy。

当前 `candidate_rejection_reasons()` 返回空集合，因此所有排名候选都被视为 sufficient。`REFERENCE_ONLY` 能限制普通审批，却仍可以令结果状态成为 `recommendation_ready`。这正是金属铝测试中“数值没有被自动锁定，但错误材料仍进入推荐列表”的原因。

## 3. 金属铝失败案例复盘

### 3.1 请求

```text
material_name = 金属铝
quantity      = 1 t
geography     = CN
year          = 2024
boundary      = cradle-to-gate
```

### 3.2 实际 Trace

```text
NORMALIZE
  canonical_name      = 金属铝
  head_material       = null
  material_family     = null
  category            = UNKNOWN
  confidence          = 0.4

EXACT LINK
  no_match

SYNONYM LINK
  no_match

RELATED RECALL
  金属硅粉 × 2

QUALIFICATION
  identity = UNKNOWN
  eligible = true

SCORING
  material match = 0.00

GAP
  MATERIAL_ABSENT_GAP

TOP-K
  金属硅粉 13.123521594 kgCO2e/kg
  金属硅粉 12.810037 kgCO2e/kg
  均为 CLASS_GENERIC_PROXY / REFERENCE_ONLY
```

### 3.3 正式目录事实

当前目录没有原铝、金属铝、电解铝、再生铝等直接生命周期因子。目录中的氧化铝是金属铝生产的上游原料，金属硅是另一个元素材料，两者都不能直接替代金属铝。

正确终态应为：

```text
无直接金属铝因子
无经审核的金属铝 Proxy Edge
→ supplier_data_required / process_model_required / unresolved
```

系统可以展示“曾召回但已排除的金属硅记录”，但不得将其放入 Top-K Recommendation。

## 4. 根因分层

| 层 | 当前问题 | 后果 | 应由哪层解决 |
|---|---|---|---|
| 标准化 | 不识别元素、化合物和行业语境 | 铝/氧化铝/铝矾土边界模糊 | Mention Parser |
| 注册表 | 缺少 aluminium、silicon 等实体 | Request/Source 都 UNKNOWN | Entity Registry |
| 别名 | 子串、单字、无排除上下文 | 钢包误识别为 steel | Alias Policy |
| Related Recall | 单一通用 bigram 即可召回 | 金属铝召回金属硅 | Recall Policy |
| Qualification | unknown-vs-unknown 不阻断 | 错误候选进入 Candidate | Admission Policy |
| Relations | IS_A 只展示不执行 | 无法证明同实体或合法 Proxy | Relation Engine |
| Scoring | 缺失维度得到 0.5 | 错误候选仍有非零总分 | Rank，仅限准入后 |
| Top-K | sufficient hard gate 为空 | Reference-Only 也变 ready | Terminal Policy |
| 测试 | 缺少跨元素对抗集 | 回归未捕获 | Semantic Gold Set |

## 5. 目标语义架构

### 5.1 总体架构

```text
Raw Request / Source Record
          │
          ▼
TEXT NORMALIZATION
NFKC / case / punctuation / chemical formula / units
          │
          ▼
MATERIAL MENTION PARSER
base entity / constituents / process / form / grade / purity / coating / route
          │
          ▼
ENTITY RESOLUTION
exact primary name / reviewed alias / structured chemical identity
          │
          ├── RESOLVED
          ├── PARTIAL
          ├── AMBIGUOUS → MORE_INPUT
          ├── CONFLICT  → EXCLUDE / MORE_INPUT
          └── UNKNOWN   → exact catalog observation + draft suggestion
          │
          ▼
LOCAL LINKING
catalog exact → reviewed alias → same-entity related
          │
          ▼
CANDIDATE ADMISSION
identity proof + factor semantics + declared product + boundary + unit
          │
          ▼
GAP ANALYSIS / ROUTERS
process / grade / form / reference flow
          │
          ▼
LATE PROXY RESOLUTION
reviewed directed Proxy Edge + technical constraints
          │
          ▼
RANK / TOP-K / HUMAN APPROVAL / LOCK
```

### 5.2 关键分离

必须把四个容易混淆的概念拆开：

1. **Mention**：文本里提到了什么；
2. **Identity**：它对应哪个受治理实体；
3. **Relation**：两个实体之间是什么关系；
4. **Suitability**：在指定工艺、形态、地域、时间和边界下是否适合作为因子候选。

名称相似只回答 Mention Recall，不能直接回答后三项。

## 6. 目标数据模型

### 6.1 SemanticEntity

```python
SemanticEntity(
    entity_id="mat.element.aluminium",
    canonical_name_zh="铝",
    canonical_name_en="aluminium",
    entity_type="ELEMENTAL_METAL",
    material_family="nonferrous_metals",
    category="METAL",
    chemical_formula="Al",
    identifiers={"internal": "MAT-AL", "cas": "7429-90-5"},
    status="ACTIVE",
    provenance="reviewed-material-master/v1",
)
```

`entity_type` 至少区分：

- ELEMENT；
- ELEMENTAL_METAL；
- OXIDE；
- MINERAL；
- ALLOY；
- CHEMICAL_COMPOUND；
- COMPOSITE；
- ENGINEERED_MATERIAL；
- PRODUCT_FAMILY；
- ENERGY_CARRIER；
- TRANSPORT_SERVICE。

### 6.2 SemanticAlias

```python
SemanticAlias(
    alias_id="alias.aluminium.metal.zh/v1",
    entity_id="mat.element.aluminium",
    value="金属铝",
    language="zh-CN",
    match_mode="EXACT_PHRASE",
    priority=100,
    required_context=(),
    forbidden_context=("氧化铝", "铝矾土", "铝酸盐"),
    ambiguity_group=None,
    status="ACTIVE",
    provenance="reviewed-material-master/v1",
)
```

允许的匹配模式应明确：

- `PRIMARY_EXACT`；
- `EXACT_PHRASE`；
- `TOKEN_BOUNDARY`；
- `FORMULA_EXACT`；
- `CONTROLLED_REGEX`；
- `ABBREVIATION_WITH_CONTEXT`。

禁止默认使用任意中文子串作为材料身份依据。单字别名必须有严格上下文或不得用于自动身份确认。

### 6.3 MaterialMention

```python
MaterialMention(
    raw_text="再生铝合金锭 6061",
    normalized_text="再生铝合金锭 6061",
    base_entity_candidates=("mat.alloy.aluminium",),
    constituents=("mat.element.aluminium",),
    route="secondary_recycling",
    product_form="ingot",
    grade="6061",
    recycled_content=None,
    purity=None,
    coating=None,
    unresolved_attributes=("recycled_content",),
)
```

### 6.4 IdentityResolution

```python
IdentityResolution(
    outcome="RESOLVED",
    selected_entity_id="mat.element.aluminium",
    candidate_entity_ids=("mat.element.aluminium",),
    proof_type="REGISTRY_EXACT_ALIAS",
    evidence_ids=("alias.aluminium.metal.zh/v1",),
    conflicts=(),
    unresolved_attributes=(),
    confidence_label="DETERMINISTIC",
)
```

`outcome` 不应再被一个 0–1 confidence 替代，应显式区分：

- `RESOLVED`；
- `PARTIAL`；
- `AMBIGUOUS`；
- `CONFLICT`；
- `UNKNOWN`。

### 6.5 SemanticRelation

```python
SemanticRelation(
    relation_id="rel.alumina-feedstock-for-primary-aluminium/v1",
    source_entity_id="mat.compound.alumina",
    relation_type="FEEDSTOCK_FOR",
    target_entity_id="mat.product.primary_aluminium",
    directed=True,
    status="ACTIVE",
    provenance="reviewed-process-ontology/v1",
)
```

关系类型建议包含：

- `SAME_AS`；
- `IS_A`；
- `COMPOSED_OF`；
- `FORM_VARIANT_OF`；
- `PROCESS_VARIANT_OF`；
- `GRADE_VARIANT_OF`；
- `FEEDSTOCK_FOR`；
- `PRODUCED_BY`；
- `NOT_SAME_AS`；
- `INCOMPATIBLE_WITH`。

注意：`FEEDSTOCK_FOR` 不是 `SAME_AS`，也不是 `VALID_PROXY_FOR`。氧化铝可以是原铝生产的上游输入，但不能因此直接作为金属铝排放因子。

### 6.6 ProxyEdge

Proxy 不宜仅用普通本体关系表达，应有单独的、有方向、带资格条件的数据结构：

```python
ProxyEdge(
    proxy_edge_id="proxy.primary-aluminium-region-fallback/v1",
    target_entity_id="mat.product.primary_aluminium",
    proxy_entity_id="mat.product.primary_aluminium",
    allowed_target_routes=("hall_heroult",),
    allowed_proxy_routes=("hall_heroult",),
    required_form="ingot",
    required_composition_family="primary_aluminium",
    geography_policy="electricity-mix-sensitive",
    temporal_limit_years=5,
    boundary_policy="equal_or_superset_with_decomposition",
    adjustment_router="PROCESS_VARIANT_RESOLUTION",
    evidence_ids=(...),
    status="ACTIVE",
)
```

材料类别只能帮助搜索 ProxyEdge，不能代替 ProxyEdge。

### 6.7 CandidateAdmission

```python
CandidateAdmission(
    source_id="...",
    retrieval_strategy="RELATED_SAME_ENTITY",
    identity_status="PASS",
    identity_proof_ids=(...),
    hard_exclusions=(),
    resolvable_gaps=("PROCESS_VARIANT_GAP",),
    observation_only=False,
    admitted=True,
)
```

Admission 必须发生在评分前。

## 7. 身份证据等级

建议采用确定性证据等级，而不是把所有判断压成一个相似度：

| 等级 | 证据 | 可用于 Direct | 可用于 Related | 可用于 Proxy |
|---|---|---:|---:|---:|
| A | Catalog primary name exact + declared product compatible | 是 | 否 | 否 |
| A | Registry primary/exact alias | 是 | 是 | 可作为目标身份 |
| A | 结构化化学/内部主数据 ID 一致 | 是 | 是 | 可作为目标身份 |
| B | Reviewed SAME_AS relation | 是 | 是 | 可作为目标身份 |
| B | Same entity，Process/Form/Grade 不同 | 否 | 是 | 否 |
| B | Reviewed ProxyEdge | 否 | 否 | 是 |
| C | 多术语高覆盖召回、embedding | 否 | 仅 Observation | 仅搜索 ProxyEdge |
| C | LLM 结构化判断 | 否 | 仅建议/辅助解释 | 仅在 bounded IDs 内评估 |
| D | 单一通用词、单一中文 bigram | 否 | 否 | 否 |

重要例外：如果注册表尚未覆盖某个新材料，但请求名称与正式目录 primary name 完全一致，且 declared product、factor kind、indicator、boundary、unit 合格，可以形成 Direct Exact。这样注册表治理不会阻塞所有新目录数据；但该证明仅适用于这条 Direct 记录，不能自动开启 Related 或 Proxy。

## 8. 检索策略重构

### 8.1 Exact Link

允许：

- normalized primary name exact；
- catalog code exact；
- structured entity ID exact。

Exact 仍需完整 Qualification，坏 Exact 不得阻断合法 Alias。

### 8.2 Alias Link

只允许 ACTIVE、无歧义、满足上下文规则的 reviewed alias。Alias 必须返回 alias ID、entity ID 和 provenance。

### 8.3 Related Same-Entity Recall

Related 不再表示“名字看起来相关”，而应定义为：

```text
Request entity_id == Source entity_id
AND differences are limited to declared Process/Form/Grade/Composition variants
```

典型合法案例：

- 电熔莫来石 ↔ 烧结莫来石；
- 同一钢系不同牌号；
- 同一材料粉体 ↔ 块体，但需 Form Gap；
- 同一产品不同地域/年份。

典型非法案例：

- 金属铝 ↔ 金属硅；
- 铝 ↔ 氧化铝；
- 钢纤维 ↔ 陶瓷纤维；
- 莫来石 ↔ 碳化硅；
- 任意两个“粉末”或任意两个“金属”。

词面或 embedding Related 结果只能进入 `RecallObservation`，不能直接进入 Candidate Pool。

### 8.4 Class-Aware Proxy Retrieval

只在直接/同实体候选不足后执行：

```text
Material Class
  → 搜索 ACTIVE ProxyEdge
  → 根据工艺、形态、组成、地域、时间、边界过滤
  → 返回受限 Proxy IDs
  → LLM 可在这些 IDs 内给出技术判断
  → 确定性 Qualification 和 Router 决定是否可用
```

不得在本体图中自动寻找“最短路径”并把邻近实体当 Proxy。本体距离是检索线索，不是技术替代证明。

## 9. Candidate Admission Policy V2

### 9.1 Direct

Direct 候选至少满足一种身份证明：

- Catalog primary exact；
- reviewed alias/SAME_AS；
- structured entity ID exact。

以下情况硬排除：

- 已知实体 ID 不同；
- 元素/化合物类型冲突；
- declared product 明确不兼容；
- factor kind 不是生命周期因子/EPD/合规派生因子；
- indicator 明确不是目标 GWP；
- boundary 明确不覆盖目标；
- 单位语义不成立。

### 9.2 Related

Related 必须同时满足：

- Request 与 Source 的 entity ID 相同；
- 或存在 reviewed SAME_AS；
- 差异能够被 Process/Form/Grade/Composition Gap 表达；
- 不存在 constituent conflict。

Request 或 Source 任一身份 UNKNOWN 时，词面 related 只能作为 Observation。

### 9.3 Proxy

Proxy 必须满足：

- 存在 ACTIVE、方向正确的 ProxyEdge；
- 技术过程、产品形态、组成和边界没有硬冲突；
- 地域和时间符合边的适用策略；
- 所需调整参数有 provenance；
- 不存在禁止关系。

同类别、同 family 或 embedding 相似本身不够。

### 9.4 Unknown 和 Ambiguous

| Request 身份 | Local Exact | Related | Proxy | 终态 |
|---|---|---|---|---|
| RESOLVED | 正常 | same-entity | reviewed edge | 正常 |
| PARTIAL | 仅明确部分可用 | 通常暂停 | 需补充输入 | MORE_INPUT |
| AMBIGUOUS | 可展示精确候选但不自动选 | 禁止 | 禁止 | MORE_INPUT |
| CONFLICT | 禁止 | 禁止 | 禁止 | MORE_INPUT/ERROR |
| UNKNOWN | primary exact 可单条验证 | 仅 Observation | 不自动 | UNRESOLVED/SUPPLIER_DATA |

## 10. Scoring 和终态策略

### 10.1 Admission before Score

推荐顺序：

```text
Recall
  → Identity Qualification
  → Factor Qualification
  → Candidate Admission
  → Gap Analysis
  → Resolution
  → Score
  → Rank
```

`material score=0` 不能只是降分。当 identity proof 不成立时，它应是 Observation 或 Exclusion。

### 10.2 缺失值

缺失字段应拆成两个信号：

- `suitability_score`：只对可比较维度评分；
- `evidence_coverage`：反映多少关键维度有证据。

缺失值不应凭空贡献 0.5 适配度。若为了兼容现有公式保留 0.5，也必须确保它只在 Admission 通过后参与排序。

### 10.3 `REFERENCE_ONLY` 的两种语义

建议拆分：

- `REVIEWABLE_REFERENCE`：身份关系成立，但指标/边界/年份等证据不足；可以进入 Top-K，需 override；
- `DIAGNOSTIC_OBSERVATION`：仅词面召回或身份未证明；不得进入 Recommendation，只在 Trace 的 excluded/observations 中展示。

### 10.4 `recommendation_ready`

只有至少一个 `admitted=True` 且属于以下类别的候选才能进入：

- PRIMARY_RECOMMENDATION；
- USABLE_WITH_ASSUMPTIONS；
- REVIEWABLE_REFERENCE，且身份资格已经证明。

如果只有 DIAGNOSTIC_OBSERVATION，应进入：

- `unresolved`；
- `process_model_required`；
- `supplier_data_required`；
- `more_input_needed`。

## 11. Graph 和 State 更新建议

### 11.1 新增/调整节点

不需要让 Material Class 过早参与主路由。建议在 Normalize 内部或其后新增确定性语义子图：

```text
NORMALIZE_TEXT
  → PARSE_MATERIAL_MENTION
  → RESOLVE_MATERIAL_IDENTITY
  → IDENTITY_SUFFICIENCY_ROUTER
      RESOLVED → LOCAL EXACT/ALIAS
      PARTIAL/AMBIGUOUS → MORE_INPUT
      UNKNOWN → LOCAL PRIMARY EXACT OBSERVATION + SUGGESTION
```

Local Retrieval 后新增明确的：

```text
RECALL OBSERVATION
  → CANDIDATE ADMISSION
  → admitted candidates only
```

Material Resolution 仍保持在同实体 Resolution 失败之后，专门寻找 ProxyEdge。

### 11.2 GraphState 新字段

```python
GraphState:
    material_mention: MaterialMention | None
    request_identity: IdentityResolution | None
    source_identities: dict[source_id, IdentityResolution]
    identity_conflicts: list[IdentityConflict]
    recall_observations: tuple[RecallObservation, ...]
    candidate_admissions: tuple[CandidateAdmission, ...]
    semantic_registry_anchor: SemanticRegistryAnchor | None
    semantic_index_anchor: SemanticIndexAnchor | None
    proxy_edge_ids: tuple[str, ...]
```

### 11.3 Router 不变量

- Identity AMBIGUOUS 不得直接进入 Related/Proxy；
- Related 必须证明 same entity；
- Proxy 必须引用 ProxyEdge ID；
- 每个候选最多一次有界 Resolution Plan；
- LLM 不得改变 admission、数值、公式或锁定状态；
- 无合格候选必须终止，不得循环扩大语义搜索。

## 12. LLM 的正确职责

LLM 适合：

- 从复杂商品名中提出结构化 MaterialMention；
- 识别可能的材料实体候选；
- 从 bounded entity IDs 中判断语义解释；
- 解释工艺、形态和组成差异；
- 对未知名称生成 DRAFT rule suggestion；
- 在 reviewed ProxyEdge 候选内总结技术适配理由和局限。

LLM 不得：

- 自动发布实体、别名或 ProxyEdge；
- 用自由文本创造排放因子；
- 用 embedding 相似度绕过 identity mismatch；
- 把元素、化合物、矿石和制品自动视为同一材料；
- 在未引用证据时断言某个 Proxy 技术等价；
- 决定最终锁定。

LLM 输出必须符合 JSON Schema，并包含：候选 entity IDs、字段级证据片段、冲突、未知项和建议问题。任何未在输入 bounded IDs 中的 entity ID 均不得直接参与本次运行。

## 13. 注册表治理和新材料处理

“彻底解决”不意味着一次性录入全世界材料，而是让每次新问题都通过一致的治理流程解决：

```text
未知/冲突样本
  → 自动聚类和频次统计
  → LLM/规则工具生成 DRAFT suggestion
  → 数据管理员确认实体边界
  → 定义 aliases、排除上下文、relations
  → 生成正向与负向回归测试
  → 影响分析：哪些历史请求会改变
  → REVIEWED
  → 发布新 registry version/hash
  → 重跑 gold set
  → ACTIVE
```

每条规则应记录：

- owner/reviewer；
- created_at/reviewed_at；
- provenance；
- source document or material-master reference；
- language/region；
- effective version；
- supersedes；
- positive examples；
- negative examples；
- known ambiguity group；
- change note。

删除或变更别名不能原地静默修改，应发布新版本并保留 Trace 可比较性。

## 14. 金属铝实体组建议

短期最少应建立以下不同实体，禁止用一个“铝”规则全部吞并：

| Entity ID | 名称 | 类型 | 说明 |
|---|---|---|---|
| `mat.element.aluminium` | 金属铝/铝 | ELEMENTAL_METAL | 基础元素身份 |
| `mat.product.primary_aluminium` | 原铝/电解铝 | METAL_PRODUCT | 原生路线产品 |
| `mat.product.secondary_aluminium` | 再生铝 | RECYCLED_MATERIAL | 再生路线产品 |
| `mat.alloy.aluminium` | 铝合金 | ALLOY | 需要牌号/系列 |
| `mat.compound.alumina` | 氧化铝/Al2O3 | OXIDE | 金属铝上游，不是同物 |
| `mat.ore.bauxite` | 铝土矿/铝矾土 | MINERAL/ORE | 更上游原料 |
| `mat.compound.aluminate` | 铝酸盐 | CHEMICAL_COMPOUND | 不等于金属铝 |
| `mat.element.silicon` | 金属硅/硅 | ELEMENT | 与铝明确不同 |
| `mat.compound.silica` | 二氧化硅/SiO2 | OXIDE | 与金属硅明确不同 |

建议关系：

```text
alumina FEEDSTOCK_FOR primary_aluminium
bauxite FEEDSTOCK_FOR alumina
primary_aluminium IS_A aluminium_product
secondary_aluminium IS_A aluminium_product
aluminium_alloy COMPOSED_OF aluminium + alloying_elements
aluminium NOT_SAME_AS alumina
aluminium NOT_SAME_AS silicon
silicon NOT_SAME_AS silica
```

这些关系不会自动产生排放因子，只用于身份、检索和资格约束。

## 15. Trace V2

每次请求应回答：

- 使用哪个正式因子库版本；
- 使用哪个语义注册表版本和 hash；
- 原始文本经过哪些标准化规则；
- 解析出哪些 mention 字段；
- 命中哪些实体候选、别名和关系；
- 是否有歧义、冲突或未识别字段；
- Local Exact/Alias/Related 各召回什么；
- 哪些仅为 Observation；
- 每条候选凭什么 admitted 或 excluded；
- 为什么进入 Proxy；
- 使用了哪个 ProxyEdge；
- 最终如何排名；
- 数据库或注册表更新后为什么结果变化。

建议 Trace 片段：

```json
{
  "semantic_registry": {
    "version": "material-semantic-registry/2.0.0",
    "sha256": "..."
  },
  "request_identity": {
    "outcome": "RESOLVED",
    "entity_id": "mat.element.aluminium",
    "proof_type": "REGISTRY_EXACT_ALIAS",
    "evidence_ids": ["alias.aluminium.metal.zh/v1"]
  },
  "recall_observations": [
    {
      "source_id": "...SILICON_METAL_POWDER",
      "basis": ["lexical_generic_term:金属"],
      "admitted": false,
      "exclusion": "entity_id_mismatch"
    }
  ],
  "terminal_decision": {
    "status": "supplier_data_required",
    "reason": "no direct factor and no reviewed proxy edge"
  }
}
```

## 16. 版本锚点

除正式因子库和能耗库外，增加：

```python
SemanticRegistryAnchor(
    registry_name,
    registry_version,
    registry_sha256,
    schema_version,
    active_rule_count,
    locator,
)

SemanticIndexAnchor(
    catalog_database_sha256,
    registry_sha256,
    index_version,
    generated_at,
)
```

目录更新或注册表更新都应重建 Semantic Index。相同 normalized business fingerprint 的 Trace 比较应区分：

- factor database changed；
- semantic registry changed；
- semantic index changed；
- request interpretation changed；
- candidate admission changed；
- ranking-only changed。

## 17. 分阶段迁移计划

### P0：立即阻断当前错误

目标：不等待完整 V2 本体即可停止明显错误推荐。

- Related candidate 若 Request/Source identity 均 UNKNOWN，不得进入 Candidate Pool；
- 去掉“同 product form 即 Related”的自动准入；
- 中文 bigram 只作为 Observation，不作为候选准入；
- 已知不同 head/entity、元素或化学实体必须硬排除；
- `material dimension == 0` 且无 reviewed ProxyEdge 时硬排除；
- 实现非空的 `candidate_rejection_reasons()`；
- 只有 identity-qualified Reference 才能令状态为 `recommendation_ready`；
- 加入金属铝、金属硅、氧化铝、二氧化硅的最小实体规则和负向测试。

P0 的正确金属铝结果：无合格本地/Proxy 时进入 supplier/process-model/unresolved，同时 Trace 保留被排除的金属硅观察。

### P1：Semantic Registry V2

- 引入 entity/alias/relation/negative-context 数据结构；
- 支持多 identity candidates、ambiguity/conflict/outcome；
- 化学式、牌号、纯度、再生含量和多组分 mention parser；
- SourceRecord 预解析并保存 entity ID；
- 注册表 hash/version anchor；
- 迁移 V1 内置规则并处理 `钢包`、复合材料等反例。

### P2：Catalog Semantic Index

- 对正式目录离线预计算实体、别名、工艺、形态、组成；
- Exact/Alias/Entity 索引查询替代运行时全表模糊扫描；
- 保存未识别、歧义和冲突队列；
- 目录 SHA 或注册表 SHA 变化时确定性重建；
- 建立覆盖率和误识别报告。

### P3：Reviewed Proxy Graph

- 独立 ProxyEdge Registry；
- 定义材料族内的技术替代边和适用条件；
- 将 Process/Grade/Form Router 与 ProxyEdge 要求绑定；
- 禁止通过普通 IS_A 或 embedding 自动生成可用 Proxy；
- 建立 Proxy rejection reason taxonomy。

### P4：LLM 辅助和持续治理

- bounded entity candidate 判断；
- DRAFT suggestion 工作流；
- 人工反馈回流；
- 规则发布前历史 Trace replay；
- 按材料族校准与监控。

## 18. 回归测试矩阵

### 18.1 必须通过的身份测试

| 请求 | 候选 | 预期 |
|---|---|---|
| 金属铝 | 金属铝 | Direct Exact/ Alias |
| 金属铝 | 金属硅粉 | hard exclude |
| 金属铝 | 氧化铝 | exclude；可记录 FEEDSTOCK relation |
| 金属铝 | 铝矾土 | exclude |
| 金属硅 | 二氧化硅 | exclude |
| 钢包用透气元件 | steel | 不得因“钢”自动识别 |
| 钢纤维 | 陶瓷纤维 | form 相同但材料冲突，exclude |
| 电熔莫来石 | 烧结莫来石 | same entity + Process Gap |
| 电熔莫来石 | 电熔刚玉 | process 相同但实体冲突，exclude |
| 锆莫来石 | 莫来石 | composite/constituent difference，不得当完全同一 |
| 莫来石-SiC | 莫来石 | composition gap，不能丢失 SiC |
| 6061 铝合金 | 原铝 | alloy/grade difference，不得 Direct |
| 再生铝 | 原铝 | route identity difference，需 Process/Proxy evidence |

### 18.2 歧义测试

- `铝`：根据业务域可解析为 elemental aluminium，但不得命中所有含“铝”的化合物；
- `Al`：只有化学/材料上下文才能作为 aluminium；
- `钢包`：不得识别为 steel product；
- `硅粉`：区分 silicon powder 与 silica powder；
- 中英文混写、全角、化学下标和牌号符号应得到等价 fingerprint。

### 18.3 状态测试

- 只有 lexical observations → `unresolved`，不是 `recommendation_ready`；
- 只有 identity-qualified Reference-Only → 可 `recommendation_ready`，但仅允许 reference override；
- Request AMBIGUOUS → `more_input_needed`；
- 无直接因子且无 ProxyEdge → `supplier_data_required` 或 `process_model_required`；
- Registry 更新前后同一请求 Trace 能解释 admission 变化。

### 18.4 属性测试

- 任意不同 element entity ID 不能通过 Related；
- 任意同 form、不同 entity 不能仅凭 form 进入 Candidate；
- DRAFT/DEPRECATED/REJECTED 规则不能改变运行结果；
- LLM suggestion 不能包含因子数值或自动变 ACTIVE；
- 每个 admitted Proxy 必须拥有 ACTIVE ProxyEdge ID；
- 每个 Recommendation candidate 必须拥有 identity proof ID。

## 19. 评估指标

不能只看“注册表覆盖率”。建议同时监控：

### 身份质量

- entity resolution precision；
- entity resolution recall；
- ambiguous rate；
- unknown rate；
- false-positive identity rate；
- composite constituent retention rate；
- alias collision rate。

### 召回与准入

- Exact/Alias/Same-Entity Related Recall@K；
- lexical observation → admitted 的误转化率，目标应为 0；
- cross-entity admission rate，目标应为 0；
- form-only admission rate，目标应为 0；
- Proxy without edge rate，目标应为 0。

### 业务结果

- Top-1 human acceptance；
- Top-K acceptance；
- human material correction rate；
- unresolved/process-model/supplier-data rate；
- false recommendation rate；
- registry update result-drift rate。

### 当前基线

```text
正式目录记录数             177
Registry V1 sufficiently identified 37
UNKNOWN                    140
表面覆盖率                 20.9%
已发现 cross-element 错误  金属铝 → 金属硅粉
已发现 substring 错误      钢包 → steel
已发现 composite 信息损失  锆莫来石、莫来石-SiC
```

在材料身份场景中应优先提高 precision，再逐步提高 recall。宁可把未知项送入有界治理队列，也不要把错误材料作为有数值的 Top-K 推荐。

## 20. 验收标准

Semantic Resolution V2 至少满足：

1. 每个 Recommendation candidate 都有可追溯 identity proof；
2. Direct、Related、Proxy 使用不同的身份准入契约；
3. Related 必须 same entity，词面相似只能形成 Observation；
4. Proxy 必须有 ACTIVE ProxyEdge，类别相同不能代替边；
5. unknown-vs-unknown 不再自动 eligible；
6. 元素、氧化物、矿石、合金、复合材料和制品可区分；
7. 多组分材料不被压扁成单一 head material；
8. alias 支持 exact/boundary/context/forbidden/ambiguity；
9. `钢包` 不再命中 steel，金属铝不再召回金属硅；
10. 金属铝无直接因子时进入明确后续状态；
11. LLM 只能提出结构化建议或判断 bounded IDs；
12. Trace 同时锚定正式目录、语义注册表和语义索引版本；
13. 注册表每次发布必须通过正向、负向、歧义和历史 replay 测试；
14. 新材料扩展不要求修改 Graph 或数值公式；
15. 系统不会无限重试或无限扩展语义图搜索。

## 21. 不建议采用的做法

- 为每个新错误在 `_related_material()` 里追加一个 `if`；
- 维护一个无版本、无来源的大型同义词 JSON；
- 把所有含“铝”的名称归到 aluminium；
- 仅靠 embedding cosine similarity 决定 Proxy；
- 让 LLM 在全库自由选择候选或生成实体 ID；
- 以 Material Class 相同作为材料可替代证明；
- 用低分或低 confidence 代替 hard exclusion；
- 为追求覆盖率把 ENERGY/TRANSPORT 等全部强塞进 Material Registry；
- 自动沿 IS_A 图多跳寻找 Proxy；
- 在没有数据库/注册表版本锚点时更新规则。

## 22. 推荐实施顺序

建议首先实施 P0，因为它可以最小代价阻断当前错误：

1. 把 lexical Related 降为 Observation；
2. unknown-vs-unknown Related 不准入；
3. 实现 identity hard gate 和有效的 `candidate_rejection_reasons()`；
4. 修正 Top-K status；
5. 增加铝/硅/氧化物/钢包对抗测试；
6. 再建设 Entity Registry V2 和 Semantic Index；
7. 最后建设 Reviewed Proxy Graph。

这一路径不会破坏“目标材料本身优先、Material Class 延迟参与、Proxy 作为后备、数值确定性、Trace 可解释”的现有核心原则。它真正改变的是：从“先找到像的名字再降分”转为“先证明候选有资格，再对合格候选排序”。

## 23. 最终结论

当前语义问题的本质不是 LLM 能力不足，也不是注册表词条数量单独不足，而是材料身份尚未成为 Candidate Admission 的强类型前置条件。

彻底治理后的系统应具备以下行为：

```text
金属铝
  → 识别 aluminium entity
  → 正式目录无 Direct factor
  → 金属硅因 entity conflict 仅保留为 excluded observation
  → 氧化铝因 FEEDSTOCK_FOR 而非 SAME_AS 被排除为直接候选
  → 若存在 reviewed aluminium ProxyEdge，则进入技术 Proxy 评估
  → 否则明确进入 supplier-data / process-model / unresolved
```

这才符合 Graph Engineering：每个节点只承担清晰责任，每条边有确定性 guard，每个候选携带身份和来源证据，每个失败都有可终止状态，每次注册表或数据库更新都能通过 Trace 解释结果变化。
