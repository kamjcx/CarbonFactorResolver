"""Versioned, entity-first material semantics used before factor retrieval.

The registry contains no emission-factor values. Only ACTIVE rules can affect
runtime identity. Text/LLM similarity can propose DRAFT rules, but cannot
admit a factor candidate or create a proxy relation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol, TypeVar

from .matching import normalize_text
from .models import (
    EntityType,
    GradeEvidenceScope,
    GradeInterpretationKind,
    IdentityOutcome,
    IdentityProofType,
    IdentityResolution,
    MaterialCategory,
    MaterialIdentity,
    MaterialMention,
    NumericTokenResolution,
    NumericTokenRole,
    PurityGrade,
    RegistryRuleStatus,
    RegistryRuleSuggestion,
    RetrievalIntent,
    SemanticRelationType,
    SemanticRole,
    SemanticSpan,
    SourceRecord,
    SpecificationOperator,
)


def _norm(value: str | None) -> str:
    return normalize_text(value).value


def _contains(value: str, alias: str) -> bool:
    if not alias:
        return False
    if any("\u4e00" <= char <= "\u9fff" for char in alias):
        return alias in value
    return re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", value) is not None


def _material_occurrences(value: str, alias: str) -> tuple[tuple[int, int], ...]:
    """Return entity spans; one-character Chinese aliases are exact-only."""

    if not alias:
        return ()
    is_cjk = any("\u4e00" <= char <= "\u9fff" for char in alias)
    if is_cjk and len(alias) == 1:
        if value == alias:
            return ((0, 1),)
        allowed_suffixes = ("纤维", "卷", "材", "板", "丝", "锭", "粉", "管")
        positions: list[tuple[int, int]] = []
        for match in re.finditer(re.escape(alias), value):
            prefix = value[max(0, match.start() - 2):match.start()]
            suffix = value[match.end():]
            if prefix == "金属" or suffix.startswith(allowed_suffixes):
                positions.append((match.start(), match.end()))
        return tuple(positions)
    if is_cjk:
        return tuple((match.start(), match.end()) for match in re.finditer(re.escape(alias), value))
    return tuple(
        (match.start(), match.end())
        for match in re.finditer(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", value)
    )


def _first_occurrence(value: str, alias: str) -> tuple[int, int] | None:
    if not _contains(value, alias):
        return None
    match = re.search(re.escape(alias), value)
    return (match.start(), match.end()) if match else None


@dataclass(frozen=True, slots=True)
class MaterialRule:
    rule_id: str
    head_material: str
    material_family: str
    category: MaterialCategory
    aliases: tuple[str, ...]
    confidence: float = 0.9
    status: RegistryRuleStatus = RegistryRuleStatus.ACTIVE
    provenance: str = "built-in-reviewed-rule"
    entity_id: str | None = None
    entity_type: EntityType = EntityType.ENGINEERED_MATERIAL
    chemical_formula: str | None = None
    product_entity_id: str | None = None
    product_family_id: str | None = None
    route: str | None = None
    constituent_entity_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProcessRule:
    rule_id: str
    process: str
    aliases: tuple[str, ...]
    status: RegistryRuleStatus = RegistryRuleStatus.ACTIVE
    provenance: str = "built-in-reviewed-rule"


@dataclass(frozen=True, slots=True)
class FormRule:
    rule_id: str
    product_form: str
    aliases: tuple[str, ...]
    status: RegistryRuleStatus = RegistryRuleStatus.ACTIVE
    provenance: str = "built-in-reviewed-rule"


@dataclass(frozen=True, slots=True)
class TypedRelation:
    relation_id: str
    source_rule_id: str
    relation_type: SemanticRelationType
    target_id: str
    status: RegistryRuleStatus = RegistryRuleStatus.ACTIVE
    provenance: str = "built-in-reviewed-relation"


@dataclass(frozen=True, slots=True)
class PurityGradeSchema:
    schema_id: str
    version: str
    entity_ids: tuple[str, ...]
    basis_component_id: str
    allowed_labels: tuple[float, ...]
    evidence_scope: GradeEvidenceScope
    evidence_ids: tuple[str, ...]
    ordered: bool = False
    label_prefixes: tuple[str, ...] = ()
    interpretation_kind: GradeInterpretationKind = GradeInterpretationKind.IMPLICIT_GRADE_CLASS
    priority: int = 0
    status: RegistryRuleStatus = RegistryRuleStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class RegistryResolution:
    identity: MaterialIdentity
    registry_version: str
    material_rule_ids: tuple[str, ...] = ()
    process_rule_ids: tuple[str, ...] = ()
    form_rule_ids: tuple[str, ...] = ()
    relation_ids: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    suggestion: RegistryRuleSuggestion | None = None
    mention: MaterialMention | None = None
    identity_resolution: IdentityResolution | None = None
    retrieval_intent: RetrievalIntent | None = None
    registry_sha256: str | None = None

    @property
    def sufficiently_identified(self) -> bool:
        if self.identity_resolution is not None:
            return self.identity_resolution.sufficiently_resolved
        return bool(self.identity.head_material and self.identity.category != MaterialCategory.UNKNOWN)


RegistryEntryT = TypeVar(
    "RegistryEntryT",
    MaterialRule,
    ProcessRule,
    FormRule,
    TypedRelation,
    PurityGradeSchema,
)
MatchRuleT = TypeVar("MatchRuleT", ProcessRule, FormRule)


class MaterialSemanticRegistryPort(Protocol):
    @property
    def version(self) -> str: ...

    @property
    def sha256(self) -> str: ...

    def resolve(
        self,
        name: str,
        *,
        product_form: str | None = None,
        composition: str | None = None,
        production_process: str | None = None,
    ) -> RegistryResolution: ...

    def enrich_source(self, source: SourceRecord) -> SourceRecord: ...


class MaterialRuleSuggestionPort(Protocol):
    async def suggest(self, normalized_name: str) -> RegistryRuleSuggestion | None: ...


@dataclass(frozen=True, slots=True)
class VersionedMaterialSemanticRegistry:
    version: str
    material_rules: tuple[MaterialRule, ...]
    process_rules: tuple[ProcessRule, ...]
    form_rules: tuple[FormRule, ...]
    relations: tuple[TypedRelation, ...] = ()
    grade_schemas: tuple[PurityGradeSchema, ...] = ()

    @staticmethod
    def _active(values: Sequence[RegistryEntryT]) -> tuple[RegistryEntryT, ...]:
        return tuple(
            value for value in values
            if getattr(value, "status", None) == RegistryRuleStatus.ACTIVE
        )

    @property
    def sha256(self) -> str:
        payload = {
            "version": self.version,
            "materials": [
                {
                    "rule_id": rule.rule_id,
                    "head_material": rule.head_material,
                    "family": rule.material_family,
                    "category": rule.category.value,
                    "aliases": rule.aliases,
                    "entity_id": rule.entity_id,
                    "entity_type": rule.entity_type.value,
                    "formula": rule.chemical_formula,
                    "product_entity_id": rule.product_entity_id,
                    "product_family_id": rule.product_family_id,
                    "route": rule.route,
                    "constituents": rule.constituent_entity_ids,
                    "status": rule.status.value,
                }
                for rule in self.material_rules
            ],
            "processes": [
                (rule.rule_id, rule.process, rule.aliases, rule.status.value)
                for rule in self.process_rules
            ],
            "forms": [
                (rule.rule_id, rule.product_form, rule.aliases, rule.status.value)
                for rule in self.form_rules
            ],
            "relations": [
                (relation.relation_id, relation.source_rule_id, relation.relation_type.value,
                 relation.target_id, relation.status.value)
                for relation in self.relations
            ],
            "grade_schemas": [
                {
                    "schema_id": schema.schema_id,
                    "version": schema.version,
                    "entity_ids": schema.entity_ids,
                    "basis": schema.basis_component_id,
                    "allowed_labels": schema.allowed_labels,
                    "evidence_scope": schema.evidence_scope.value,
                    "evidence_ids": schema.evidence_ids,
                    "ordered": schema.ordered,
                    "label_prefixes": schema.label_prefixes,
                    "interpretation_kind": schema.interpretation_kind.value,
                    "priority": schema.priority,
                    "status": schema.status.value,
                }
                for schema in self.grade_schemas
            ],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _material_matches(self, value: str) -> tuple[tuple[MaterialRule, str, int, int], ...]:
        matches = [
            (rule, alias, start, end)
            for rule in self._active(self.material_rules)
            for alias in (_norm(item) for item in rule.aliases)
            for start, end in _material_occurrences(value, alias)
        ]
        matches.sort(key=lambda item: (-(item[3] - item[2]), item[2], item[0].rule_id))
        selected: list[tuple[MaterialRule, str, int, int]] = []
        occupied: set[int] = set()
        for match in matches:
            positions = set(range(match[2], match[3]))
            if positions & occupied:
                continue
            selected.append(match)
            occupied.update(positions)
        return tuple(sorted(selected, key=lambda item: (item[2], item[3], item[0].rule_id)))

    @staticmethod
    def _best_rule_match(
        value: str, rules: Sequence[MatchRuleT]
    ) -> tuple[MatchRuleT, str, int, int] | None:
        matches: list[tuple[MatchRuleT, str, int, int]] = []
        for rule in rules:
            for raw_alias in rule.aliases:
                alias = _norm(raw_alias)
                occurrence = _first_occurrence(value, alias)
                if occurrence:
                    matches.append((rule, alias, occurrence[0], occurrence[1]))
        matches.sort(key=lambda item: (-(item[3] - item[2]), item[0].rule_id))
        return matches[0] if matches else None

    def _grade_schemas_for(self, entity_id: str | None) -> tuple[PurityGradeSchema, ...]:
        if not entity_id:
            return ()
        schemas = tuple(
            schema for schema in self._active(self.grade_schemas)
            if entity_id in schema.entity_ids
        )
        return tuple(sorted(schemas, key=lambda schema: (-schema.priority, schema.schema_id)))

    def _parse_numeric_grade(
        self,
        value: str,
        entity_id: str | None,
    ) -> tuple[PurityGrade | None, tuple[NumericTokenResolution, ...], float | None]:
        """Classify numbers before binding one material-scoped purity grade."""

        tokens: list[NumericTokenResolution] = []
        occupied: list[tuple[int, int]] = []

        def overlaps(start: int, end: int) -> bool:
            return any(start < used_end and end > used_start for used_start, used_end in occupied)

        def add_token(
            raw: str,
            start: int,
            end: int,
            role: NumericTokenRole,
            evidence_id: str,
            reason: str,
            *,
            rejected: tuple[NumericTokenRole, ...] = (),
        ) -> None:
            occupied.append((start, end))
            tokens.append(NumericTokenResolution(
                raw=raw,
                start=start,
                end=end,
                role=role,
                evidence_id=evidence_id,
                rejected_roles=rejected,
                reason=reason,
            ))

        # Strong negative contexts are classified before standalone numbers.
        negative_patterns = (
            (r"(?i)(?:^|[^a-z0-9])(?:f|p)\s*-?\s*\d{2,3}(?!\d)", NumericTokenRole.GRIT_SIZE, "numeric.fepa_grit/v1"),
            (r"(?i)(?:^|[^a-z0-9])(?:t|ct|ca)\s*-?\s*\d{1,4}(?!\d)", NumericTokenRole.MODEL_CODE, "numeric.product_model/v1"),
            (r"(?i)\baisi\s*\d{3,4}(?!\d)|\buns\s*[a-z]?\d+(?!\d)|\b\d{4}\s*铝合金|\b\d{4}\s+(?:aluminium|aluminum)\s+alloy\b", NumericTokenRole.ALLOY_GRADE, "numeric.alloy_grade/v1"),
            (r"(?i)\bgb\s*/?\s*t?\s*\d+(?:\.\d+)?(?:-\d{4})?", NumericTokenRole.STANDARD_NUMBER, "numeric.standard_number/v1"),
            (r"(?<!\d)20\d{2}(?:年)?(?!\d)", NumericTokenRole.YEAR, "numeric.year/v1"),
            (r"(?i)\d+(?:\.\d+)?\s*(?:-|~|–|—)\s*\d+(?:\.\d+)?\s*(?:mm|cm|µm|um|mesh|目)", NumericTokenRole.PARTICLE_SIZE, "numeric.particle_range/v1"),
            (r"(?i)\d+(?:\.\d+)?\s*(?:mm|cm|µm|um|mesh|目)\b", NumericTokenRole.PARTICLE_SIZE, "numeric.particle_size/v1"),
            (r"(?i)\d+(?:\.\d+)?\s*kg(?:\s*/\s*袋)?", NumericTokenRole.PACKAGING, "numeric.packaging/v1"),
            (r"型号\s*[-:]?\s*\d+", NumericTokenRole.MODEL_CODE, "numeric.model_label.zh/v1"),
        )
        for pattern, role, evidence_id in negative_patterns:
            for match in re.finditer(pattern, value):
                if not overlaps(match.start(), match.end()):
                    add_token(
                        match.group(0), match.start(), match.end(), role, evidence_id,
                        "numeric context is not a material purity grade",
                        rejected=(NumericTokenRole.PURITY_GRADE,),
                    )

        schemas = self._grade_schemas_for(entity_id)
        bare_schemas = tuple(schema for schema in schemas if not schema.label_prefixes)
        formula_basis = {
            "mgo": "component.MgO",
            "al2o3": "component.Al2O3",
            "sic": "component.SiC",
            "al": "element.Al",
            "si": "element.Si",
        }

        # Explicit percentage or chemistry has precedence over every implicit grade.
        explicit_pattern = re.compile(
            r"(?i)(?:(mgo|al2o3|sic|al|si)\s*)?(>=|≤|<=|≥|>|=)?\s*(\d+(?:\.\d+)?)\s*%"
        )
        explicit = next((match for match in explicit_pattern.finditer(value) if not overlaps(match.start(), match.end())), None)
        if explicit:
            grade_value = float(explicit.group(3))
            schema = bare_schemas[0] if len(bare_schemas) == 1 else None
            basis = formula_basis.get((explicit.group(1) or "").casefold()) or (
                schema.basis_component_id if schema else None
            )
            operator_text = explicit.group(2)
            operator = {
                ">=": SpecificationOperator.MINIMUM,
                "≥": SpecificationOperator.MINIMUM,
                ">": SpecificationOperator.MINIMUM_EXCLUSIVE,
                "=": SpecificationOperator.EXACT,
                "<=": SpecificationOperator.MAXIMUM,
                "≤": SpecificationOperator.MAXIMUM,
            }.get(operator_text or "", SpecificationOperator.NOMINAL)
            if basis and 0 < grade_value <= 100:
                schema_id = schema.schema_id if schema else f"explicit.{basis}/v1"
                schema_version = schema.version if schema else "1.0.0"
                evidence_ids = tuple(dict.fromkeys((
                    "purity.explicit_percent/v2",
                    *((schema.evidence_ids) if schema else ()),
                )))
                grade = PurityGrade(
                    raw_label=explicit.group(0),
                    grade_value=grade_value,
                    basis_component_id=basis,
                    interpretation_kind=GradeInterpretationKind.EXPLICIT_COMPOSITION,
                    schema_id=schema_id,
                    schema_version=schema_version,
                    evidence_scope=GradeEvidenceScope.EXPLICIT_TEXT,
                    evidence_ids=evidence_ids,
                    parser_rule_ids=("numeric.explicit_percent/v2",),
                    specification_operator=operator,
                    nominal_value=grade_value if operator == SpecificationOperator.NOMINAL else None,
                    specification_min=(
                        grade_value
                        if operator in {SpecificationOperator.MINIMUM, SpecificationOperator.MINIMUM_EXCLUSIVE}
                        else None
                    ),
                    specification_max=grade_value if operator == SpecificationOperator.MAXIMUM else None,
                    ordered=schema.ordered if schema else True,
                )
                add_token(
                    explicit.group(0), explicit.start(), explicit.end(),
                    NumericTokenRole.PURITY_GRADE, "numeric.explicit_percent/v2",
                    "explicit percentage bound to material/component chemistry",
                    rejected=(NumericTokenRole.PARTICLE_SIZE, NumericTokenRole.MODEL_CODE),
                )
                return grade, tuple(sorted(tokens, key=lambda token: (token.start, token.end))), grade_value

        # A component formula immediately followed by a value is also explicit
        # chemistry, even when the author omits the percent sign (for example,
        # ``MgO 90``). Requiring the formula keeps unrelated bare numbers out.
        formula_grade_pattern = re.compile(
            r"(?i)(?<![a-z0-9])(mgo|al2o3|sic|al|si)\s*(>=|≤|<=|≥|>|=)?\s*(\d+(?:\.\d+)?)(?![a-z0-9.])"
        )
        formula_grade = next(
            (
                match for match in formula_grade_pattern.finditer(value)
                if not overlaps(match.start(), match.end())
            ),
            None,
        )
        if formula_grade:
            grade_value = float(formula_grade.group(3))
            basis = formula_basis[formula_grade.group(1).casefold()]
            schema = next(
                (item for item in bare_schemas if item.basis_component_id == basis),
                None,
            )
            operator_text = formula_grade.group(2)
            operator = {
                ">=": SpecificationOperator.MINIMUM,
                "≥": SpecificationOperator.MINIMUM,
                ">": SpecificationOperator.MINIMUM_EXCLUSIVE,
                "=": SpecificationOperator.EXACT,
                "<=": SpecificationOperator.MAXIMUM,
                "≤": SpecificationOperator.MAXIMUM,
            }.get(operator_text or "", SpecificationOperator.NOMINAL)
            if 0 < grade_value <= 100:
                grade = PurityGrade(
                    raw_label=formula_grade.group(0),
                    grade_value=grade_value,
                    basis_component_id=basis,
                    interpretation_kind=GradeInterpretationKind.EXPLICIT_COMPOSITION,
                    schema_id=schema.schema_id if schema else f"explicit.{basis}/v1",
                    schema_version=schema.version if schema else "1.0.0",
                    evidence_scope=GradeEvidenceScope.EXPLICIT_TEXT,
                    evidence_ids=tuple(dict.fromkeys((
                        "purity.explicit_formula_value/v1",
                        *((schema.evidence_ids) if schema else ()),
                    ))),
                    parser_rule_ids=("numeric.explicit_formula_value/v1",),
                    specification_operator=operator,
                    nominal_value=(
                        grade_value if operator == SpecificationOperator.NOMINAL else None
                    ),
                    specification_min=(
                        grade_value
                        if operator in {
                            SpecificationOperator.MINIMUM,
                            SpecificationOperator.MINIMUM_EXCLUSIVE,
                        }
                        else None
                    ),
                    specification_max=(
                        grade_value if operator == SpecificationOperator.MAXIMUM else None
                    ),
                    ordered=schema.ordered if schema else True,
                )
                add_token(
                    formula_grade.group(0), formula_grade.start(), formula_grade.end(),
                    NumericTokenRole.PURITY_GRADE, "numeric.explicit_formula_value/v1",
                    "explicit component formula and value bound to material chemistry",
                    rejected=(NumericTokenRole.PARTICLE_SIZE, NumericTokenRole.MODEL_CODE),
                )
                return (
                    grade,
                    tuple(sorted(tokens, key=lambda token: (token.start, token.end))),
                    grade_value,
                )

        # Registered supplier/product prefixes outrank organization bare-number defaults.
        for schema in schemas:
            for prefix in schema.label_prefixes:
                prefix_pattern = re.compile(rf"(?i)(?<![a-z0-9]){re.escape(prefix)}\s*-?\s*(\d{{2}}(?:\.\d+)?)(?!\d)")
                prefix_match = next((
                    item for item in prefix_pattern.finditer(value)
                    if not overlaps(item.start(), item.end())
                ), None)
                if not prefix_match:
                    continue
                grade_value = float(prefix_match.group(1))
                if grade_value not in schema.allowed_labels:
                    continue
                grade = PurityGrade(
                    raw_label=prefix_match.group(0), grade_value=grade_value,
                    basis_component_id=schema.basis_component_id,
                    interpretation_kind=schema.interpretation_kind,
                    schema_id=schema.schema_id, schema_version=schema.version,
                    evidence_scope=schema.evidence_scope, evidence_ids=schema.evidence_ids,
                    parser_rule_ids=("numeric.prefixed_grade/v1",), ordered=schema.ordered,
                )
                add_token(
                    prefix_match.group(0), prefix_match.start(), prefix_match.end(), NumericTokenRole.PURITY_GRADE,
                    "numeric.prefixed_grade/v1", "registered product-grade prefix bound to entity schema",
                    rejected=(NumericTokenRole.MODEL_CODE, NumericTokenRole.GRIT_SIZE),
                )
                return grade, tuple(sorted(tokens, key=lambda token: (token.start, token.end))), None

        candidates: list[tuple[PurityGrade, int, int]] = []
        standalone_pattern = re.compile(r"(?<![a-z0-9.])(\d{2}(?:\.\d+)?)(?![a-z0-9.])", re.IGNORECASE)
        for match in standalone_pattern.finditer(value):
            if overlaps(match.start(), match.end()):
                continue
            grade_value = float(match.group(1))
            matching = tuple(schema for schema in bare_schemas if grade_value in schema.allowed_labels)
            if len(matching) == 1:
                schema = matching[0]
                candidates.append((PurityGrade(
                    raw_label=match.group(0), grade_value=grade_value,
                    basis_component_id=schema.basis_component_id,
                    interpretation_kind=schema.interpretation_kind,
                    schema_id=schema.schema_id, schema_version=schema.version,
                    evidence_scope=schema.evidence_scope, evidence_ids=schema.evidence_ids,
                    parser_rule_ids=("numeric.standalone_entity_grade/v1",), ordered=schema.ordered,
                ), match.start(), match.end()))
            elif grade_value in {70, 80, 90}:
                add_token(
                    match.group(0), match.start(), match.end(), NumericTokenRole.UNRESOLVED,
                    "numeric.unbound_grade/v1", "standalone grade-like number has no unique entity schema",
                    rejected=(NumericTokenRole.PURITY_GRADE,),
                )

        if len(candidates) == 1:
            grade, start, end = candidates[0]
            add_token(
                grade.raw_label, start, end, NumericTokenRole.PURITY_GRADE,
                "numeric.standalone_entity_grade/v1",
                "standalone number automatically bound by the entity-scoped grade schema",
                rejected=(NumericTokenRole.PARTICLE_SIZE, NumericTokenRole.MODEL_CODE, NumericTokenRole.YEAR),
            )
            return grade, tuple(sorted(tokens, key=lambda token: (token.start, token.end))), None
        if len(candidates) > 1:
            for grade, start, end in candidates:
                add_token(
                    grade.raw_label, start, end, NumericTokenRole.UNRESOLVED,
                    "numeric.multiple_grade_tokens/v1", "multiple grade-class numbers conflict",
                    rejected=(NumericTokenRole.PURITY_GRADE,),
                )
        return None, tuple(sorted(tokens, key=lambda token: (token.start, token.end))), None

    def resolve(
        self,
        name: str,
        *,
        product_form: str | None = None,
        composition: str | None = None,
        production_process: str | None = None,
    ) -> RegistryResolution:
        value = _norm(name)
        material_matches = self._material_matches(value)
        process_match = self._best_rule_match(
            value, self._active(self.process_rules)
        )
        process_input_match = None if process_match else self._best_rule_match(
            _norm(production_process), self._active(self.process_rules)
        )
        form_match = self._best_rule_match(
            value, self._active(self.form_rules)
        )
        form_input_match = None if form_match else self._best_rule_match(
            _norm(product_form), self._active(self.form_rules)
        )

        selected_rules = tuple(dict.fromkeys(match[0] for match in material_matches))
        explicit_composite = next(
            (rule for rule in selected_rules if rule.entity_type == EntityType.COMPOSITE), None
        )
        composite = explicit_composite is not None or len(selected_rules) > 1
        material_rule = explicit_composite or (selected_rules[0] if len(selected_rules) == 1 else None)
        selected_process_match = process_match or process_input_match
        selected_form_match = form_match or form_input_match
        process_rule = selected_process_match[0] if selected_process_match else None
        form_rule = selected_form_match[0] if selected_form_match else None

        constituent_ids = tuple(dict.fromkeys(
            entity_id
            for rule in selected_rules
            for entity_id in (
                rule.constituent_entity_ids
                if rule.constituent_entity_ids else ((rule.entity_id,) if rule.entity_id else ())
            )
        ))
        if composite and len(constituent_ids) >= 2:
            base_entity_id = "composite:" + "+".join(sorted(constituent_ids))
            head_material = "composite"
            material_family = "composite_materials"
            category = MaterialCategory.MANUFACTURED_MINERAL
            entity_type = EntityType.COMPOSITE
            formula = None
            product_entity_id = explicit_composite.product_entity_id if explicit_composite else None
            product_family_id = "family.composite_materials"
            confidence = min(rule.confidence for rule in selected_rules)
            proof_type = IdentityProofType.COMPOSITE_CONSTITUENTS
        elif material_rule:
            base_entity_id = material_rule.entity_id or f"material:{material_rule.head_material}"
            head_material = material_rule.head_material
            material_family = material_rule.material_family
            category = material_rule.category
            entity_type = material_rule.entity_type
            formula = material_rule.chemical_formula
            product_entity_id = material_rule.product_entity_id
            product_family_id = material_rule.product_family_id or material_rule.material_family
            confidence = material_rule.confidence
            proof_type = IdentityProofType.REGISTRY_EXACT_ALIAS
            constituent_ids = material_rule.constituent_entity_ids
        else:
            base_entity_id = None
            head_material = None
            material_family = None
            category = MaterialCategory.UNKNOWN
            entity_type = EntityType.UNKNOWN
            formula = None
            product_entity_id = None
            product_family_id = None
            confidence = 0.4
            proof_type = IdentityProofType.NONE
            constituent_ids = ()

        spans: list[SemanticSpan] = []
        for rule, alias, start, end in material_matches:
            role = SemanticRole.CONSTITUENT if composite else SemanticRole.BASE_ENTITY
            spans.append(SemanticSpan(
                text=value[start:end], normalized_text=alias, role=role,
                start=start, end=end, evidence_id=rule.rule_id, entity_id=rule.entity_id,
            ))
        if process_match:
            matched_process_rule, alias, start, end = process_match
            spans.append(SemanticSpan(
                text=value[start:end], normalized_text=alias, role=SemanticRole.PROCESS,
                start=start, end=end, evidence_id=matched_process_rule.rule_id,
            ))
        if form_match:
            matched_form_rule, alias, start, end = form_match
            spans.append(SemanticSpan(
                text=value[start:end], normalized_text=alias, role=SemanticRole.PRODUCT_FORM,
                start=start, end=end, evidence_id=matched_form_rule.rule_id,
            ))

        entity_type_hint = entity_type
        for qualifier, hint, evidence_id in (
            ("金属", EntityType.ELEMENTAL_METAL, "entity_type.metal.zh/v1"),
            ("metal", EntityType.ELEMENTAL_METAL, "entity_type.metal.en/v1"),
            ("合金", EntityType.ALLOY, "entity_type.alloy.zh/v1"),
            ("alloy", EntityType.ALLOY, "entity_type.alloy.en/v1"),
        ):
            occurrence = _first_occurrence(value, qualifier)
            if occurrence:
                spans.append(SemanticSpan(
                    text=value[occurrence[0]:occurrence[1]], normalized_text=qualifier,
                    role=SemanticRole.ENTITY_TYPE, start=occurrence[0], end=occurrence[1],
                    evidence_id=evidence_id,
                ))
                if entity_type != EntityType.COMPOSITE:
                    entity_type_hint = hint
                break

        name_grade, numeric_tokens, name_purity = self._parse_numeric_grade(value, base_entity_id)
        composition_grade = None
        composition_purity = None
        if composition:
            composition_grade, _, composition_purity = self._parse_numeric_grade(
                _norm(composition), base_entity_id
            )
        # A structured composition field is stronger than a grade embedded in
        # the display name. Numeric token offsets still refer only to `name`.
        numeric_grade = composition_grade or name_grade
        purity = composition_purity if composition_purity is not None else name_purity
        grade_token = next(
            (token for token in numeric_tokens if token.role == NumericTokenRole.PURITY_GRADE), None
        )
        if grade_token and numeric_grade:
            spans.append(SemanticSpan(
                text=grade_token.raw, normalized_text=grade_token.raw,
                role=(
                    SemanticRole.PURITY
                    if numeric_grade.interpretation_kind == GradeInterpretationKind.EXPLICIT_COMPOSITION
                    else SemanticRole.GRADE
                ),
                start=grade_token.start, end=grade_token.end,
                evidence_id=grade_token.evidence_id,
            ))
        grade_modifiers = tuple(
            modifier for modifier in ("高纯", "high purity") if _contains(value, modifier)
        )
        for modifier in grade_modifiers:
            occurrence = _first_occurrence(value, modifier)
            if occurrence:
                spans.append(SemanticSpan(
                    text=value[occurrence[0]:occurrence[1]], normalized_text=modifier,
                    role=SemanticRole.GRADE_MODIFIER, start=occurrence[0], end=occurrence[1],
                    evidence_id="grade_modifier.high_purity/v1",
                ))

        material_rule_ids = tuple(rule.rule_id for rule in selected_rules)
        process_rule_ids = (process_rule.rule_id,) if process_rule else ()
        form_rule_ids = (form_rule.rule_id,) if form_rule else ()
        relation_ids = tuple(
            relation.relation_id
            for relation in self._active(self.relations)
            if relation.source_rule_id in material_rule_ids
        )
        route = material_rule.route if material_rule else None
        resolved_process = process_rule.process if process_rule else _norm(production_process) or None
        resolved_form = form_rule.product_form if form_rule else _norm(product_form) or None

        identity = MaterialIdentity(
            canonical_name=value,
            base_entity_id=base_entity_id,
            product_entity_id=product_entity_id,
            product_family_id=product_family_id,
            entity_type=entity_type,
            chemical_formula=formula,
            constituent_entity_ids=constituent_ids,
            head_material=head_material,
            material_family=material_family,
            category=category,
            product_form=resolved_form,
            grade=numeric_grade.canonical_label if numeric_grade else None,
            composition=_norm(composition) or None,
            manufacturing_route=tuple(filter(None, (resolved_process, route))),
            rationale=(
                f"entity-first semantic registry {self.version}: "
                f"materials={material_rule_ids or ('unmatched',)}, "
                f"process={process_rule.rule_id if process_rule else 'unmatched'}, "
                f"form={form_rule.rule_id if form_rule else 'unmatched'}, "
                f"grade={numeric_grade.schema_id if numeric_grade else 'unmatched'}"
            ),
            confidence=confidence,
        )
        identity = self._enrich_identity(identity, value, production_process)
        unresolved_grade = any(token.role == NumericTokenRole.UNRESOLVED for token in numeric_tokens)
        alloy_grade_token = next(
            (token for token in numeric_tokens if token.role == NumericTokenRole.ALLOY_GRADE), None
        )
        if numeric_grade:
            identity = replace(identity, grade=numeric_grade.canonical_label)
        elif unresolved_grade:
            identity = replace(
                identity,
                unresolved_attributes=tuple(dict.fromkeys((
                    *identity.unresolved_attributes, "numeric_grade_basis",
                ))),
            )
        elif alloy_grade_token:
            designation = next(
                (part for part in re.findall(r"\d{4}", alloy_grade_token.raw)),
                alloy_grade_token.raw,
            )
            identity = replace(
                identity,
                grade=designation,
                unresolved_attributes=tuple(dict.fromkeys((
                    *identity.unresolved_attributes, "alloy_grade",
                ))),
            )
        mention = MaterialMention(
            raw_text=name,
            normalized_text=value,
            spans=tuple(sorted(spans, key=lambda span: (span.start, span.end, span.role.value))),
            base_entity_text=(
                value[material_matches[0][2]:material_matches[0][3]]
                if len(material_matches) == 1 else None
            ),
            entity_type_hint=entity_type_hint,
            chemical_formula=formula,
            process=resolved_process,
            route=route,
            product_form=resolved_form,
            grade=identity.grade,
            grade_modifiers=grade_modifiers,
            purity=purity,
            coating=identity.surface_coating,
            application=identity.application,
            constituent_entity_ids=constituent_ids,
            numeric_grade=numeric_grade,
            numeric_tokens=numeric_tokens,
        )
        identity_resolution = IdentityResolution(
            outcome=IdentityOutcome.RESOLVED if base_entity_id else IdentityOutcome.UNKNOWN,
            selected_base_entity_id=base_entity_id,
            selected_product_entity_id=product_entity_id,
            product_family_id=product_family_id,
            candidate_entity_ids=(base_entity_id,) if base_entity_id else (),
            proof_type=proof_type,
            evidence_ids=tuple(dict.fromkeys((*material_rule_ids, *relation_ids))),
            unresolved_attributes=identity.unresolved_attributes,
        )
        aliases = tuple(dict.fromkeys(
            _norm(alias)
            for rule in selected_rules
            for alias in rule.aliases
            if _norm(alias) and _norm(alias) != value
        ))
        # Base aliases must not erase any request qualifier. This includes
        # negative numeric roles: "碳化硅" is not a full synonym for "F80碳化硅",
        # even though F80 was correctly classified as grit rather than purity.
        has_request_qualifier = bool(
            resolved_process
            or resolved_form
            or purity is not None
            or numeric_grade is not None
            or numeric_tokens
        )
        intent_aliases = () if has_request_qualifier else aliases
        retrieval_intent = RetrievalIntent(
            canonical_name=value,
            base_entity_id=base_entity_id,
            product_entity_id=product_entity_id,
            product_family_id=product_family_id,
            allowed_base_entity_ids=(base_entity_id,) if base_entity_id else (),
            allowed_product_entity_ids=(
                ("mat.product.primary_aluminium", "mat.product.secondary_aluminium")
                if base_entity_id == "mat.element.aluminium"
                and product_family_id == "family.aluminium_products"
                and product_entity_id is None
                else (product_entity_id,) if product_entity_id else ()
            ),
            aliases=intent_aliases,
            process=resolved_process,
            route=route,
            product_form=resolved_form,
            grade=identity.grade,
            purity=purity,
            identity_outcome=identity_resolution.outcome,
            identity_proof_ids=identity_resolution.evidence_ids,
            numeric_grade=numeric_grade,
        )
        return RegistryResolution(
            identity=identity,
            registry_version=self.version,
            material_rule_ids=material_rule_ids,
            process_rule_ids=process_rule_ids,
            form_rule_ids=form_rule_ids,
            relation_ids=relation_ids,
            aliases=aliases,
            mention=mention,
            identity_resolution=identity_resolution,
            retrieval_intent=retrieval_intent,
            registry_sha256=self.sha256,
        )

    @staticmethod
    def _enrich_identity(
        identity: MaterialIdentity, value: str, production_process: str | None
    ) -> MaterialIdentity:
        if identity.entity_type == EntityType.PRODUCT_FAMILY and identity.product_entity_id is None:
            return replace(identity, unresolved_attributes=("product_variant",))
        if identity.head_material != "steel":
            return identity
        is_fiber = identity.product_form == "fiber"
        grade = "AISI 446 / UNS S44600" if any(token in value for token in ("446", "s44600")) else None
        family = "ferritic_stainless_steel" if grade or "耐热不锈钢" in value else identity.material_family
        coating = (
            "copper" if any(token in value for token in ("copper plated", "copper plating", "镀铜"))
            else "none" if any(token in value for token in ("uncoated", "without copper", "未镀铜"))
            else None
        )
        unresolved: tuple[str, ...]
        if is_fiber and grade is None:
            unresolved = () if coating is not None else (
                "steel_fiber_type", "steel_grade_or_family", "surface_coating", "application"
            )
        elif is_fiber and grade is not None and not (production_process or identity.manufacturing_route):
            unresolved = ("manufacturing_route",)
        else:
            unresolved = ()
        return replace(
            identity, material_family=family, grade=grade, surface_coating=coating,
            application="high_temperature_refractory" if grade else None,
            unresolved_attributes=unresolved,
        )

    def enrich_source(self, source: SourceRecord) -> SourceRecord:
        resolved = self.resolve(
            source.material_name,
            product_form=source.product_form,
            composition=source.composition,
            production_process=source.production_process,
        )
        identity = resolved.identity
        metadata = {
            **source.metadata,
            "semantic_registry_version": self.version,
            "semantic_registry_sha256": self.sha256,
            "material_rule_ids": ",".join(resolved.material_rule_ids),
            "process_rule_ids": ",".join(resolved.process_rule_ids),
            "form_rule_ids": ",".join(resolved.form_rule_ids),
            "relation_ids": ",".join(resolved.relation_ids),
            "material_category": identity.category.value,
            "base_entity_id": identity.base_entity_id or "",
            "product_entity_id": identity.product_entity_id or "",
            "product_family_id": identity.product_family_id or "",
            "entity_type": identity.entity_type.value,
            "constituent_entity_ids": ",".join(identity.constituent_entity_ids),
            "identity_outcome": (
                resolved.identity_resolution.outcome.value
                if resolved.identity_resolution else IdentityOutcome.UNKNOWN.value
            ),
            "grade": (
                f"{resolved.mention.numeric_grade.grade_value:g}"
                if resolved.mention and resolved.mention.numeric_grade
                else source.metadata.get("grade", "")
            ),
            "grade_schema_id": (
                resolved.mention.numeric_grade.schema_id
                if resolved.mention and resolved.mention.numeric_grade else ""
            ),
            "grade_schema_version": (
                resolved.mention.numeric_grade.schema_version
                if resolved.mention and resolved.mention.numeric_grade else ""
            ),
            "grade_basis_component_id": (
                resolved.mention.numeric_grade.basis_component_id
                if resolved.mention and resolved.mention.numeric_grade else ""
            ),
            "grade_interpretation_kind": (
                resolved.mention.numeric_grade.interpretation_kind.value
                if resolved.mention and resolved.mention.numeric_grade else ""
            ),
            "grade_evidence_scope": (
                resolved.mention.numeric_grade.evidence_scope.value
                if resolved.mention and resolved.mention.numeric_grade else ""
            ),
        }
        return replace(
            source,
            product_form=source.product_form or identity.product_form,
            production_process=source.production_process
            or (identity.manufacturing_route[0] if identity.manufacturing_route else None),
            metadata=metadata,
        )


class NullMaterialRuleSuggestion:
    async def suggest(self, normalized_name: str) -> RegistryRuleSuggestion | None:
        return None


DEFAULT_MATERIAL_REGISTRY = VersionedMaterialSemanticRegistry(
    version="material-semantic-registry/2.2.1",
    material_rules=(
        MaterialRule("energy.electricity/v1", "electricity", "energy_carriers", MaterialCategory.ENERGY_CARRIER, ("electricity", "electric power", "grid electricity", "电力", "电能"), entity_id="energy.carrier.electricity", entity_type=EntityType.ENERGY_CARRIER, product_family_id="family.electricity"),
        MaterialRule("product.gas_purging_brick/v1", "gas_purging_brick", "gas_purging_brick_products", MaterialCategory.MANUFACTURED_MINERAL, ("gas-purging brick", "gas purging brick", "透气砖"), entity_id="mat.product_family.gas_purging_brick", entity_type=EntityType.ENGINEERED_MATERIAL, product_entity_id="mat.product.gas_purging_brick", product_family_id="family.gas_purging_brick"),
        MaterialRule("product.fused_white_alumina/v1", "fused_white_alumina", "white_alumina_products", MaterialCategory.MANUFACTURED_MINERAL, ("fused white alumina", "white fused alumina", "白刚玉", "电熔白刚玉制品"), entity_id="mat.compound.alumina", entity_type=EntityType.ENGINEERED_MATERIAL, product_entity_id="mat.product.fused_white_alumina", product_family_id="family.white_alumina"),
        MaterialRule("product.aluminium_cell_brick/v1", "aluminium_cell_brick", "aluminium_cell_brick_products", MaterialCategory.MANUFACTURED_MINERAL, ("aluminum electrolysis cell brick", "aluminium electrolysis cell brick", "铝电解槽砖", "铝电解槽用砖"), entity_id="mat.product_family.aluminium_cell_brick", entity_type=EntityType.ENGINEERED_MATERIAL, product_entity_id="mat.product.aluminium_cell_brick", product_family_id="family.aluminium_cell_brick"),
        MaterialRule("product.low_creep_clay_brick/v1", "clay_brick", "clay_brick_products", MaterialCategory.MANUFACTURED_MINERAL, ("clay brick including low-creep clay brick", "clay brick", "粘土砖", "低蠕变粘土砖", "粘土砖（含低蠕变粘土砖）"), entity_id="mat.product_family.clay_brick", entity_type=EntityType.ENGINEERED_MATERIAL, product_entity_id="mat.product.low_creep_clay_brick", product_family_id="family.clay_brick"),
        MaterialRule("product.sliding_gate.low_temperature/v1", "sliding_gate", "sliding_gate_products", MaterialCategory.MANUFACTURED_MINERAL, ("low-temperature-treated sliding gate", "low temperature treated sliding gate", "低温滑动水口", "低温处理滑动水口"), entity_id="mat.product_family.sliding_gate", entity_type=EntityType.ENGINEERED_MATERIAL, product_entity_id="mat.product.sliding_gate.low_temperature", product_family_id="family.sliding_gate"),
        MaterialRule("product.sliding_gate.medium_temperature/v1", "sliding_gate", "sliding_gate_products", MaterialCategory.MANUFACTURED_MINERAL, ("medium-temperature-treated sliding gate", "medium temperature treated sliding gate", "中温滑动水口"), entity_id="mat.product_family.sliding_gate", entity_type=EntityType.ENGINEERED_MATERIAL, product_entity_id="mat.product.sliding_gate.medium_temperature", product_family_id="family.sliding_gate"),
        MaterialRule("product.sliding_gate.high_temperature/v1", "sliding_gate", "sliding_gate_products", MaterialCategory.MANUFACTURED_MINERAL, ("high-temperature-treated sliding gate", "high temperature treated sliding gate", "高温滑动水口", "高温处理滑动水口"), entity_id="mat.product_family.sliding_gate", entity_type=EntityType.ENGINEERED_MATERIAL, product_entity_id="mat.product.sliding_gate.high_temperature", product_family_id="family.sliding_gate"),
        MaterialRule("product.sliding_gate.family/v1", "sliding_gate", "sliding_gate_products", MaterialCategory.MANUFACTURED_MINERAL, ("sliding gate", "滑动水口"), entity_id="mat.product_family.sliding_gate", entity_type=EntityType.PRODUCT_FAMILY, product_family_id="family.sliding_gate"),
        MaterialRule("product.precast.rotary_kiln/v1", "precast", "precast_products", MaterialCategory.MANUFACTURED_MINERAL, ("rotary kiln precast brick", "回转窑预制件", "回转窑用预制砖"), entity_id="mat.product_family.precast", entity_type=EntityType.ENGINEERED_MATERIAL, product_entity_id="mat.product.precast.rotary_kiln", product_family_id="family.precast"),
        MaterialRule("product.precast.family/v1", "precast", "precast_products", MaterialCategory.MANUFACTURED_MINERAL, ("precast shape", "precast", "预制件"), entity_id="mat.product_family.precast", entity_type=EntityType.PRODUCT_FAMILY, product_family_id="family.precast"),
        MaterialRule("product.wear_castable.explosion_resistant/v1", "wear_resistant_castable", "wear_resistant_castable_products", MaterialCategory.MANUFACTURED_MINERAL, ("explosion-resistant high-wear-resistant castable", "explosion resistant high wear resistant castable", "防爆高耐磨浇注料"), entity_id="mat.product_family.wear_resistant_castable", entity_type=EntityType.ENGINEERED_MATERIAL, product_entity_id="mat.product.wear_castable.explosion_resistant", product_family_id="family.wear_resistant_castable"),
        MaterialRule("product.wear_castable.high_strength/v1", "wear_resistant_castable", "wear_resistant_castable_products", MaterialCategory.MANUFACTURED_MINERAL, ("high-strength wear-resistant castables", "high strength wear resistant castable", "高强耐磨浇注料"), entity_id="mat.product_family.wear_resistant_castable", entity_type=EntityType.ENGINEERED_MATERIAL, product_entity_id="mat.product.wear_castable.high_strength", product_family_id="family.wear_resistant_castable"),
        MaterialRule("product.wear_castable.family/v1", "wear_resistant_castable", "wear_resistant_castable_products", MaterialCategory.MANUFACTURED_MINERAL, ("wear-resistant castable", "wear resistant castable", "耐磨浇注料"), entity_id="mat.product_family.wear_resistant_castable", entity_type=EntityType.PRODUCT_FAMILY, product_family_id="family.wear_resistant_castable"),
        MaterialRule("product.silica_brick.coke_hot_blast/v1", "silica_brick", "silica_brick_products", MaterialCategory.MANUFACTURED_MINERAL, ("silica brick for coke oven and hot-blast stove", "silica brick for coke oven and hot blast stove", "焦炉热风炉硅砖"), entity_id="mat.compound.silica", entity_type=EntityType.ENGINEERED_MATERIAL, product_entity_id="mat.product.silica_brick.coke_hot_blast", product_family_id="family.silica_brick"),
        MaterialRule("product.silica_brick.low_creep/v1", "silica_brick", "silica_brick_products", MaterialCategory.MANUFACTURED_MINERAL, ("silicon brick exhibits low creep properties", "low-creep silica brick", "低蠕变硅砖"), entity_id="mat.compound.silica", entity_type=EntityType.ENGINEERED_MATERIAL, product_entity_id="mat.product.silica_brick.low_creep", product_family_id="family.silica_brick"),
        MaterialRule("product.silica_brick.family/v1", "silica_brick", "silica_brick_products", MaterialCategory.MANUFACTURED_MINERAL, ("silica brick", "硅砖"), entity_id="mat.compound.silica", entity_type=EntityType.PRODUCT_FAMILY, product_family_id="family.silica_brick"),
        MaterialRule("material.zircon_mullite/v2", "zircon_mullite", "composite_materials", MaterialCategory.MANUFACTURED_MINERAL, ("锆莫来石", "zircon mullite"), entity_id="mat.composite.zircon_mullite", entity_type=EntityType.COMPOSITE, product_family_id="family.composite_materials", constituent_entity_ids=("mat.compound.zirconia", "mat.mineral.mullite")),
        MaterialRule("material.primary_aluminium/v2", "aluminium", "aluminium_products", MaterialCategory.METAL, ("原铝", "电解铝", "primary aluminium", "primary aluminum"), entity_id="mat.element.aluminium", entity_type=EntityType.ELEMENTAL_METAL, chemical_formula="Al", product_entity_id="mat.product.primary_aluminium", product_family_id="family.aluminium_products", route="primary"),
        MaterialRule("material.secondary_aluminium/v2", "aluminium", "aluminium_products", MaterialCategory.RECYCLED_MATERIAL, ("再生铝", "secondary aluminium", "secondary aluminum", "recycled aluminium", "recycled aluminum"), entity_id="mat.element.aluminium", entity_type=EntityType.ELEMENTAL_METAL, chemical_formula="Al", product_entity_id="mat.product.secondary_aluminium", product_family_id="family.aluminium_products", route="secondary_recycling"),
        MaterialRule("material.aluminium_ingot/v2", "aluminium", "aluminium_products", MaterialCategory.METAL, ("铝锭", "aluminium ingot", "aluminum ingot"), entity_id="mat.element.aluminium", entity_type=EntityType.ELEMENTAL_METAL, chemical_formula="Al", product_family_id="family.aluminium_products"),
        MaterialRule("material.aluminium_alloy/v2", "aluminium", "aluminium_alloys", MaterialCategory.METAL, ("铝合金", "aluminium alloy", "aluminum alloy"), entity_id="mat.element.aluminium", entity_type=EntityType.ALLOY, chemical_formula="Al", product_entity_id="mat.alloy.aluminium", product_family_id="family.aluminium_alloys"),
        MaterialRule("material.alumina/v2", "alumina", "alumina_products", MaterialCategory.MANUFACTURED_MINERAL, ("氧化铝", "aluminium oxide", "aluminum oxide", "alumina", "al2o3", "fused alumina"), entity_id="mat.compound.alumina", entity_type=EntityType.OXIDE, chemical_formula="Al2O3", product_family_id="family.alumina_products"),
        MaterialRule("material.bauxite/v2", "bauxite", "bauxite_products", MaterialCategory.NATURAL_MINERAL, ("铝土矿", "铝矾土", "bauxite"), entity_id="mat.ore.bauxite", entity_type=EntityType.MINERAL, product_family_id="family.bauxite_products"),
        MaterialRule("material.aluminium/v2", "aluminium", "aluminium_products", MaterialCategory.METAL, ("铝", "铝金属", "aluminium", "aluminum", "al metal", "metal aluminium", "metal aluminum"), entity_id="mat.element.aluminium", entity_type=EntityType.ELEMENTAL_METAL, chemical_formula="Al", product_family_id="family.aluminium_products"),
        MaterialRule("material.silica/v2", "silica", "silica_products", MaterialCategory.MANUFACTURED_MINERAL, ("二氧化硅", "硅石", "silica", "silicon dioxide", "sio2"), entity_id="mat.compound.silica", entity_type=EntityType.OXIDE, chemical_formula="SiO2", product_family_id="family.silica_products"),
        MaterialRule("material.silicon_carbide/v2", "silicon_carbide", "silicon_carbide_products", MaterialCategory.MANUFACTURED_MINERAL, ("碳化硅", "silicon carbide", "sic"), entity_id="mat.compound.silicon_carbide", entity_type=EntityType.CHEMICAL_COMPOUND, chemical_formula="SiC", product_family_id="family.silicon_carbide_products"),
        MaterialRule("material.silicon/v2", "silicon", "silicon_products", MaterialCategory.METAL, ("硅", "silicon metal", "metallurgical silicon", "silicon"), entity_id="mat.element.silicon", entity_type=EntityType.ELEMENTAL_METAL, chemical_formula="Si", product_family_id="family.silicon_products"),
        MaterialRule("material.zirconia/v2", "zirconia", "zirconia_products", MaterialCategory.MANUFACTURED_MINERAL, ("氧化锆", "zirconia", "zirconium oxide", "zro2"), entity_id="mat.compound.zirconia", entity_type=EntityType.OXIDE, chemical_formula="ZrO2", product_family_id="family.zirconia_products"),
        MaterialRule("material.mullite/v2", "mullite", "mullite_products", MaterialCategory.MANUFACTURED_MINERAL, ("莫来石", "mullite"), entity_id="mat.mineral.mullite", entity_type=EntityType.MINERAL, product_family_id="family.mullite_products"),
        MaterialRule("material.spinel/v2", "spinel", "spinel_products", MaterialCategory.MANUFACTURED_MINERAL, ("尖晶石", "spinel"), entity_id="mat.engineered.spinel", entity_type=EntityType.ENGINEERED_MATERIAL, product_family_id="family.spinel_products"),
        MaterialRule("material.aluminosilicate/v2", "aluminosilicate", "aluminosilicate_refractory", MaterialCategory.MANUFACTURED_MINERAL, ("硅酸铝", "aluminosilicate", "ceramic fiber", "陶瓷纤维"), entity_id="mat.compound.aluminosilicate", entity_type=EntityType.CHEMICAL_COMPOUND, product_family_id="family.aluminosilicate_refractory"),
        MaterialRule("material.corundum/v2", "corundum", "corundum_products", MaterialCategory.MANUFACTURED_MINERAL, ("刚玉", "corundum"), entity_id="mat.mineral.corundum", entity_type=EntityType.MINERAL, product_family_id="family.corundum_products"),
        MaterialRule("material.magnesia/v2", "magnesia", "magnesia_products", MaterialCategory.MANUFACTURED_MINERAL, ("镁砂", "氧化镁", "magnesia"), entity_id="mat.compound.magnesia", entity_type=EntityType.OXIDE, chemical_formula="MgO", product_family_id="family.magnesia_products"),
        MaterialRule("material.steel/v2", "steel", "steel_products", MaterialCategory.METAL, ("不锈钢", "合金钢", "steel", "stainless", "钢"), entity_id="mat.alloy.steel", entity_type=EntityType.ALLOY, product_family_id="family.steel_products"),
    ),
    process_rules=(
        ProcessRule("process.electrofused/v2", "electrofused", ("电熔", "electrofused", "electric fusion", "fused")),
        ProcessRule("process.sintered/v2", "sintered", ("烧结", "sintered")),
        ProcessRule("process.calcined/v2", "calcined", ("煅烧", "calcined")),
        ProcessRule("process.eaf/v2", "electric arc furnace", ("electric arc furnace", "eaf", "电弧炉")),
        ProcessRule("process.bof/v2", "basic oxygen furnace", ("basic oxygen furnace", "bof", "转炉")),
    ),
    form_rules=(
        FormRule("form.fiber/v2", "fiber", ("钢纤维", "陶瓷纤维", "纤维", "fiber", "fibre")),
        FormRule("form.coil/v2", "coil", ("钢卷", "卷材", "coil")),
        FormRule("form.brick/v2", "brick", ("砖", "brick")),
        FormRule("form.powder/v2", "powder", ("粉", "粉末", "powder")),
        FormRule("form.ingot/v2", "ingot", ("锭", "ingot")),
    ),
    relations=(
        TypedRelation("relation.mullite-is-aluminosilicate/v2", "material.mullite/v2", SemanticRelationType.IS_A, "aluminosilicate_mineral"),
        TypedRelation("relation.spinel-is-engineered-oxide/v2", "material.spinel/v2", SemanticRelationType.IS_A, "engineered_mixed_oxide"),
        TypedRelation("relation.corundum-is-alumina/v2", "material.corundum/v2", SemanticRelationType.IS_A, "family.alumina_products"),
    ),
    grade_schemas=(
        PurityGradeSchema(
            "grade.spinel.almatis-ar-al2o3/v1", "1.0.0", ("mat.engineered.spinel",),
            "component.Al2O3", (78, 90), GradeEvidenceScope.SUPPLIER_SPECIFIC_RULE,
            ("almatis.magnesium-aluminate-spinel-ar-series/v1",), ordered=True,
            label_prefixes=("ar",),
            interpretation_kind=GradeInterpretationKind.PRODUCT_GRADE_CLASS, priority=100,
        ),
        PurityGradeSchema(
            "grade.magnesia.mgo.organization-default/v1", "1.0.0", ("mat.compound.magnesia",),
            "component.MgO", (70, 80, 85, 88, 90, 92, 94, 95, 96, 97, 98, 99),
            GradeEvidenceScope.ORGANIZATION_BUSINESS_RULE,
            ("policy.refractory-numeric-grade-is-purity/v1",), ordered=True, priority=10,
        ),
        PurityGradeSchema(
            "grade.spinel.al2o3.organization-default/v1", "1.0.0", ("mat.engineered.spinel",),
            "component.Al2O3", (70, 78, 80, 90), GradeEvidenceScope.ORGANIZATION_BUSINESS_RULE,
            ("policy.refractory-numeric-grade-is-purity/v1",), ordered=True, priority=10,
        ),
        PurityGradeSchema(
            "grade.corundum.al2o3.organization-default/v1", "1.0.0", ("mat.mineral.corundum",),
            "component.Al2O3", (70, 80, 85, 88, 90, 95, 97, 98, 99),
            GradeEvidenceScope.ORGANIZATION_BUSINESS_RULE,
            ("policy.refractory-numeric-grade-is-purity/v1",), ordered=True, priority=10,
        ),
        PurityGradeSchema(
            "grade.alumina.al2o3.organization-default/v1", "1.0.0", ("mat.compound.alumina",),
            "component.Al2O3", (70, 80, 85, 88, 90, 95, 97, 98, 99),
            GradeEvidenceScope.ORGANIZATION_BUSINESS_RULE,
            ("policy.refractory-numeric-grade-is-purity/v1",), ordered=True, priority=10,
        ),
        PurityGradeSchema(
            "grade.bauxite.al2o3.organization-default/v1", "1.0.0", ("mat.mineral.bauxite",),
            "component.Al2O3", (70, 75, 80, 82, 85, 88, 90),
            GradeEvidenceScope.ORGANIZATION_BUSINESS_RULE,
            ("policy.refractory-numeric-grade-is-purity/v1",), ordered=True, priority=10,
        ),
        PurityGradeSchema(
            "grade.mullite.al2o3.organization-default/v1", "1.0.0", ("mat.mineral.mullite",),
            "component.Al2O3", (70, 80, 90), GradeEvidenceScope.ORGANIZATION_BUSINESS_RULE,
            ("policy.refractory-numeric-grade-is-purity/v1",), ordered=True, priority=10,
        ),
        PurityGradeSchema(
            "grade.silicon-carbide.sic.organization-default/v1", "1.0.0",
            ("mat.compound.silicon_carbide",), "component.SiC", (70, 80, 85, 88, 90, 95, 97, 98, 99),
            GradeEvidenceScope.ORGANIZATION_BUSINESS_RULE,
            ("policy.refractory-numeric-grade-is-purity/v1",), ordered=True, priority=10,
        ),
        PurityGradeSchema(
            "grade.aluminium.al.organization-default/v1", "1.0.0", ("mat.element.aluminium",),
            "element.Al", (70, 80, 90, 95, 97, 98, 99), GradeEvidenceScope.ORGANIZATION_BUSINESS_RULE,
            ("policy.material-numeric-grade-is-purity/v1",), ordered=True, priority=10,
        ),
        PurityGradeSchema(
            "grade.silicon.si.organization-default/v1", "1.0.0", ("mat.element.silicon",),
            "element.Si", (70, 80, 90, 95, 97, 98, 99), GradeEvidenceScope.ORGANIZATION_BUSINESS_RULE,
            ("policy.material-numeric-grade-is-purity/v1",), ordered=True, priority=10,
        ),
    ),
)
