# API / Data Contract Change: Unit System v1

## Change goal

Expose structured unit failure reasons and the effective target unit without changing
existing endpoint paths or removing response fields.

## Current contract

Unit parser failures are represented by free-text qualification reasons and commonly end as
`supplier_data_required`. The diagnostics endpoint omits qualification diagnostics and the
Recommendation has no stable reason-code field.

## Frozen additive contract

```json
{
  "status": "unresolved | more_input_needed | recommendation_ready | ...",
  "follow_up": "unresolved | more-input | data-governance | ...",
  "reason_codes": [
    "UNIT_SYNTAX_UNSUPPORTED | CATALOG_FACTOR_UNIT_INVALID | UNIT_DIMENSION_MISMATCH | UNIT_CONVERSION_EVIDENCE_REQUIRED"
  ]
}
```

`GET /api/v1/diagnostics/{request_id}` additionally returns:

```json
{
  "follow_up": "unresolved",
  "reason_codes": ["UNIT_DIMENSION_MISMATCH"],
  "required_fields": [],
  "qualification_diagnostics": [],
  "conversion_diagnostics": []
}
```

`ResolutionRequest.target_factor_unit` becomes nullable/omittable. Omission derives an
effective target from `quantity_unit`; explicit values remain authoritative. An optional
structured unit-conversion evidence record may carry an evidence ID, versioned Formula ID,
source/target activity units and Decimal multiplier for controlled conversions such as
`m3 ↔ Nm3`.

## Contract status

- Contract ID: `cfr-unit-api/v1`
- Parent version: `0.13.1 + portfolio validation PR #2`
- Status: **FROZEN**

## Compatibility

- Additive response fields: yes.
- Existing endpoint paths and JSON-only request body: unchanged.
- Existing explicit `target_factor_unit` clients: unchanged.
- Existing omitted `kg` target: still resolves to `kgCO2e/kg`; other mass units derive their canonical denominator.
- Data migration: none.
- Rollback: revert unit-contract commit; no persistent data migration.
- Idempotency and approval/lock semantics: unchanged.

## Test requirements

- Exact reason/status matrix for request syntax, catalogue invalidity, dimension mismatch,
  evidence requirement and genuine missing supplier data.
- POST resolve, GET resolution, GET trace and GET diagnostics serialization.
- Existing API, approval, lock and product-scope tests remain green.

## Main-agent approval

- Decision: approved as a scoped additive contract.
- Date: 2026-09-01.
