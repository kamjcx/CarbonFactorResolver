# CarbonFactorResolver architecture

CarbonFactorResolver keeps one domain graph. External discovery and diagnostics extend the existing registry, semantic index, qualification, gap-analysis, approval, and locking path; they do not create a second factor model.

```mermaid
flowchart LR
    A[Input] --> B[Entity resolution]
    B --> C[Retrieval intent]
    C --> D[Raw catalogue search]
    D --> E[Semantic index: entity / alias / lexical / fuzzy]
    E --> F[SourceRecord conversion]
    F --> G[Qualification]
    G --> H[Gap analysis]
    H --> I{Local sufficient?}
    I -- no --> J[External discovery]
    J --> K[Fetch + hash]
    K --> L[Evidence extraction]
    L --> G
    I -- yes --> M[Resolution planner]
    M --> N[Ranking]
    N --> O[Human approval and immutable lock]
```

Every numerical value enters through `SourceRecord` or versioned parameter evidence. Retrieval confidence, qualification, suitability, evidence completeness, and final rank remain separate fields.
