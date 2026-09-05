"""Immutable domain models for the factor-resolution graph.

The model deliberately has no database or LLM dependency.  A factor value can
only be represented by :class:`SourceRecord`, which requires provenance.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from .integrity import (
    DECISION_SCHEMA_VERSION,
    LOCK_SCHEMA_VERSION,
    TRACE_SCHEMA_VERSION,
    PersistenceIntegrityError,
    canonical_json_bytes,
    stable_sha256,
)
from .units import UnitConversionEvidence


def _now() -> datetime:
    return datetime.now(UTC)


class FactorSourceType(str, Enum):
    LOCAL_DATABASE = "local_database"
    EXTERNAL_DATABASE = "external_database"
    EPD = "epd"
    LITERATURE = "literature"
    SUPPLIER = "supplier"


class FactorKind(str, Enum):
    """Numeric meaning of a catalogue record, separate from its source."""

    LIFECYCLE_FACTOR = "lifecycle_factor"
    EPD_INDICATOR = "epd_indicator"
    EMISSION_LIMIT = "emission_limit"
    COMBUSTION_FACTOR = "combustion_factor"
    ENERGY_FACTOR = "energy_factor"
    TRANSPORT_FACTOR = "transport_factor"
    STOICHIOMETRIC_FACTOR = "stoichiometric_factor"
    DERIVED_PROXY_FACTOR = "derived_proxy_factor"
    OTHER = "other"


class FactorSubjectType(str, Enum):
    """Business subject represented by a factor, independent of its numeric kind."""

    RAW_MATERIAL = "raw_material"
    FINISHED_PRODUCT = "finished_product"
    ENERGY = "energy"
    TRANSPORT = "transport"
    PROCESS = "process"
    WASTE = "waste"
    UNKNOWN = "unknown"


class SourceQualityStatus(str, Enum):
    VERIFIED = "VERIFIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REJECTED = "REJECTED"


class CandidateOrigin(str, Enum):
    LOCAL = "local"
    EXTERNAL = "external"
    PROXY = "proxy"


class ResolutionStatus(str, Enum):
    RECOMMENDATION_READY = "recommendation_ready"
    UNRESOLVED = "unresolved"
    PROCESS_MODEL_REQUIRED = "process_model_required"
    SUPPLIER_DATA_REQUIRED = "supplier_data_required"
    LOCKED = "locked"
    ERROR = "error"
    MORE_INPUT_NEEDED = "more_input_needed"
    REFERENCE_REVIEW_REQUIRED = "reference_review_required"


class FollowUp(str, Enum):
    UNRESOLVED = "unresolved"
    PROCESS_MODEL = "process-model"
    SUPPLIER_DATA = "supplier-data"
    MORE_INPUT = "more-input"
    DATA_GOVERNANCE = "data-governance"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    LOCKED = "locked"


class LinkStrategy(str, Enum):
    EXACT = "exact_link"
    SYNONYM = "synonym_link"
    RELATED = "related_candidate_recall"
    CLASS_AWARE_PROXY = "class_aware_proxy_link"
    UNRESOLVED = "unresolved"


class LinkOutcome(str, Enum):
    MATCHED = "matched"
    NO_MATCH = "no_match"
    SKIPPED = "skipped"
    CANDIDATE_SET = "candidate_set"


class ParameterSourceType(str, Enum):
    INTERNAL_MEASUREMENT = "internal_measurement"
    USER_CONFIRMED_ENGINEERING_DATA = "user_confirmed_engineering_data"
    SUPPLIER_SPECIFICATION = "supplier_specification"
    FORMAL_STANDARD = "formal_standard"
    INTERNAL_CATALOG = "internal_catalog"
    LITERATURE_IMPORT = "literature_import"


class AccountingModule(str, Enum):
    A1_UPSTREAM_INPUT = "A1_UPSTREAM_INPUT"
    A3_DIRECT_PROCESS = "A3_DIRECT_PROCESS"


class AccountingRole(str, Enum):
    TARGET_PRODUCT = "TARGET_PRODUCT"
    PURCHASED_RAW_MATERIAL = "PURCHASED_RAW_MATERIAL"
    CONSUMABLE_ELECTRODE = "CONSUMABLE_ELECTRODE"
    REDUCTANT = "REDUCTANT"
    PROCESS_FUEL = "PROCESS_FUEL"
    DIRECT_PROCESS_EMISSION = "DIRECT_PROCESS_EMISSION"
    RETAINED_CONSTITUENT = "RETAINED_CONSTITUENT"
    UNKNOWN = "UNKNOWN"


class AccountingQuantificationStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    IDENTIFIED_NOT_QUANTIFIED = "IDENTIFIED_NOT_QUANTIFIED"
    QUANTIFIED = "QUANTIFIED"


class GapType(str, Enum):
    UNIT_SCALE = "UNIT_SCALE_GAP"
    REFERENCE_FLOW = "REFERENCE_FLOW_GAP"
    PROCESS_VARIANT = "PROCESS_VARIANT_GAP"
    GRADE_COMPOSITION = "GRADE_COMPOSITION_GAP"
    MATERIAL_ABSENT = "MATERIAL_ABSENT_GAP"
    BOUNDARY = "BOUNDARY_GAP"
    GEOGRAPHY = "GEOGRAPHY_GAP"
    TEMPORAL = "TEMPORAL_GAP"
    FORM = "FORM_GAP"


class RouterType(str, Enum):
    UNIT_SCALE = "UNIT_SCALE_CONVERSION"
    REFERENCE_FLOW = "REFERENCE_FLOW_CONVERSION"
    PROCESS_VARIANT = "PROCESS_VARIANT_RESOLUTION"
    GRADE_COMPOSITION = "GRADE_COMPOSITION_RESOLUTION"
    CLASS_AWARE_PROXY = "CLASS_AWARE_MATERIAL_PROXY"


class ResolutionType(str, Enum):
    DIRECT_EXACT = "DIRECT_EXACT"
    DIRECT_ALIAS = "DIRECT_ALIAS"
    UNIT_CONVERTED = "UNIT_CONVERTED"
    REFERENCE_FLOW_CONVERTED = "REFERENCE_FLOW_CONVERTED"
    PROCESS_ADJUSTED = "PROCESS_ADJUSTED"
    UNADJUSTED_PROCESS_PROXY = "UNADJUSTED_PROCESS_PROXY"
    GRADE_INTERPOLATED = "GRADE_INTERPOLATED"
    GRADE_EXACT_ANCHOR = "GRADE_EXACT_ANCHOR"
    GRADE_ADJUSTED = "GRADE_ADJUSTED"
    GRADE_PROXY = "GRADE_PROXY"
    CLASS_TECHNICAL_PROXY = "CLASS_TECHNICAL_PROXY"
    CLASS_GENERIC_PROXY = "CLASS_GENERIC_PROXY"


class ResultTier(str, Enum):
    PRIMARY_RECOMMENDATION = "PRIMARY_RECOMMENDATION"
    USABLE_WITH_ASSUMPTIONS = "USABLE_WITH_ASSUMPTIONS"
    REFERENCE_ONLY = "REFERENCE_ONLY"


class ProcessResolutionMode(str, Enum):
    DECOMPOSE_AND_REBUILD = "DECOMPOSE_AND_REBUILD"
    DELTA_ADJUST = "DELTA_ADJUST"
    UNADJUSTED_PROCESS_PROXY = "UNADJUSTED_PROCESS_PROXY"


class MaterialCategory(str, Enum):
    NATURAL_MINERAL = "NATURAL_MINERAL"
    MANUFACTURED_MINERAL = "MANUFACTURED_MINERAL"
    SYNTHETIC_CHEMICAL = "SYNTHETIC_CHEMICAL"
    METAL = "METAL"
    RECYCLED_MATERIAL = "RECYCLED_MATERIAL"
    BYPRODUCT = "BYPRODUCT"
    ENERGY_CARRIER = "ENERGY_CARRIER"
    UNKNOWN = "UNKNOWN"


class SemanticRole(str, Enum):
    BASE_ENTITY = "BASE_ENTITY"
    ENTITY_TYPE = "ENTITY_TYPE"
    PROCESS = "PROCESS"
    PRODUCT_FORM = "PRODUCT_FORM"
    GRADE = "GRADE"
    GRADE_MODIFIER = "GRADE_MODIFIER"
    PURITY = "PURITY"
    COATING = "COATING"
    ROUTE = "ROUTE"
    APPLICATION = "APPLICATION"
    CONSTITUENT = "CONSTITUENT"


class NumericTokenRole(str, Enum):
    PURITY_GRADE = "PURITY_GRADE"
    PARTICLE_SIZE = "PARTICLE_SIZE"
    GRIT_SIZE = "GRIT_SIZE"
    MODEL_CODE = "MODEL_CODE"
    ALLOY_GRADE = "ALLOY_GRADE"
    STANDARD_NUMBER = "STANDARD_NUMBER"
    YEAR = "YEAR"
    PACKAGING = "PACKAGING"
    UNRESOLVED = "UNRESOLVED"


class GradeInterpretationKind(str, Enum):
    EXPLICIT_COMPOSITION = "EXPLICIT_COMPOSITION"
    IMPLICIT_GRADE_CLASS = "IMPLICIT_GRADE_CLASS"
    PRODUCT_GRADE_CLASS = "PRODUCT_GRADE_CLASS"


class GradeEvidenceScope(str, Enum):
    EXPLICIT_TEXT = "EXPLICIT_TEXT"
    REVIEWED_STANDARD_RULE = "REVIEWED_STANDARD_RULE"
    SUPPLIER_SPECIFIC_RULE = "SUPPLIER_SPECIFIC_RULE"
    ORGANIZATION_BUSINESS_RULE = "ORGANIZATION_BUSINESS_RULE"


class SpecificationOperator(str, Enum):
    EXACT = "EXACT"
    NOMINAL = "NOMINAL"
    MINIMUM = "MINIMUM"
    MINIMUM_EXCLUSIVE = "MINIMUM_EXCLUSIVE"
    MAXIMUM = "MAXIMUM"
    RANGE = "RANGE"


class EntityType(str, Enum):
    ELEMENTAL_METAL = "ELEMENTAL_METAL"
    ELEMENT = "ELEMENT"
    OXIDE = "OXIDE"
    MINERAL = "MINERAL"
    ALLOY = "ALLOY"
    CHEMICAL_COMPOUND = "CHEMICAL_COMPOUND"
    COMPOSITE = "COMPOSITE"
    ENGINEERED_MATERIAL = "ENGINEERED_MATERIAL"
    PRODUCT_FAMILY = "PRODUCT_FAMILY"
    ENERGY_CARRIER = "ENERGY_CARRIER"
    TRANSPORT_SERVICE = "TRANSPORT_SERVICE"
    UNKNOWN = "UNKNOWN"


class IdentityOutcome(str, Enum):
    RESOLVED = "RESOLVED"
    PARTIAL = "PARTIAL"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


class IdentityProofType(str, Enum):
    CATALOG_PRIMARY_EXACT = "CATALOG_PRIMARY_EXACT"
    REGISTRY_PRIMARY_NAME = "REGISTRY_PRIMARY_NAME"
    REGISTRY_EXACT_ALIAS = "REGISTRY_EXACT_ALIAS"
    REGISTRY_SAME_AS = "REGISTRY_SAME_AS"
    STRUCTURED_ENTITY = "STRUCTURED_ENTITY"
    COMPOSITE_CONSTITUENTS = "COMPOSITE_CONSTITUENTS"
    NONE = "NONE"


class RegistryRuleStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    REJECTED = "rejected"


class SemanticRelationType(str, Enum):
    IS_A = "is_a"
    SAME_AS = "same_as"
    PROCESS_VARIANT_OF = "process_variant_of"
    FORM_VARIANT_OF = "form_variant_of"
    GRADE_VARIANT_OF = "grade_variant_of"


class RequestGapType(str, Enum):
    INPUT_SPECIFICATION = "INPUT_SPECIFICATION_GAP"
    MATERIAL_IDENTITY = "MATERIAL_IDENTITY_GAP"


class QualificationStatus(str, Enum):
    PASS = "pass"  # noqa: S105 - domain status, not a credential
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"
    NOT_EVALUATED = "not_evaluated"


class QualificationPolicy(str, Enum):
    DIRECT = "direct"
    RELATED = "related"
    PROXY = "proxy"
    GRADE_ANCHOR = "grade_anchor"


class ApprovalMode(str, Enum):
    STANDARD = "standard"
    ASSUMPTION_ACCEPTANCE = "assumption_acceptance"
    REFERENCE_OVERRIDE = "reference_override"


@dataclass(frozen=True, slots=True)
class ParameterEvidence:
    parameter_id: str
    name: str
    value: float
    unit: str
    source_type: ParameterSourceType
    provider: str
    locator: str
    citation: str = ""
    observed_at: datetime = field(default_factory=_now)
    quality_note: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.parameter_id.strip() or not self.name.strip() or not self.unit.strip():
            raise ValueError("parameter evidence requires id, name and unit")
        if not self.provider.strip() or not self.locator.strip():
            raise ValueError("parameter evidence requires provider and locator")
        if not isfinite(self.value):
            raise ValueError("parameter evidence value must be finite")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_id": self.parameter_id,
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "source_type": self.source_type.value,
            "provider": self.provider,
            "locator": self.locator,
            "citation": self.citation,
            "observed_at": self.observed_at.isoformat(),
            "quality_note": self.quality_note,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ReferenceFlowRecord:
    record_id: str
    material_name: str
    reference_unit: str
    mass_per_unit_kg: float
    evidence: ParameterEvidence
    method: str = "mass_per_unit"
    declared_product: str | None = None
    product_form: str | None = None
    specification: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.record_id.strip() or not self.material_name.strip() or not self.reference_unit.strip():
            raise ValueError("reference-flow record requires id, material and unit")
        if not isfinite(self.mass_per_unit_kg) or self.mass_per_unit_kg <= 0:
            raise ValueError("mass_per_unit_kg must be finite and positive")
        if abs(self.mass_per_unit_kg - self.evidence.value) > 1e-12:
            raise ValueError("reference-flow mass must equal its parameter evidence value")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ResolutionGap:
    gap_id: str
    candidate_id: str
    gap_type: GapType
    target_value: str | None
    candidate_value: str | None
    severity: float
    reason: str
    resolvable_by: tuple[RouterType, ...]

    def __post_init__(self) -> None:
        if not self.gap_id.strip() or not self.candidate_id.strip() or not self.reason.strip():
            raise ValueError("resolution gap requires ids and reason")
        if not 0 <= self.severity <= 1:
            raise ValueError("gap severity must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "candidate_id": self.candidate_id,
            "gap_type": self.gap_type.value,
            "target_value": self.target_value,
            "candidate_value": self.candidate_value,
            "severity": self.severity,
            "reason": self.reason,
            "resolvable_by": tuple(router.value for router in self.resolvable_by),
        }


@dataclass(frozen=True, slots=True)
class AccountingAssignment:
    subject: str
    role: AccountingRole
    modules: tuple[AccountingModule, ...]
    rationale: str
    evidence_ids: tuple[str, ...] = ()
    quantification_status: AccountingQuantificationStatus = (
        AccountingQuantificationStatus.IDENTIFIED_NOT_QUANTIFIED
    )
    missing_inputs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "role": self.role.value,
            "modules": tuple(module.value for module in self.modules),
            "rationale": self.rationale,
            "evidence_ids": self.evidence_ids,
            "quantification_status": self.quantification_status.value,
            "missing_inputs": self.missing_inputs,
        }


@dataclass(frozen=True, slots=True)
class MaterialIdentity:
    canonical_name: str
    base_entity_id: str | None = None
    product_entity_id: str | None = None
    product_family_id: str | None = None
    entity_type: EntityType = EntityType.UNKNOWN
    chemical_formula: str | None = None
    constituent_entity_ids: tuple[str, ...] = ()
    head_material: str | None = None
    material_family: str | None = None
    category: MaterialCategory = MaterialCategory.UNKNOWN
    product_form: str | None = None
    grade: str | None = None
    composition: str | None = None
    surface_coating: str | None = None
    manufacturing_route: tuple[str, ...] = ()
    application: str | None = None
    unresolved_attributes: tuple[str, ...] = ()
    rationale: str = ""
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if not self.canonical_name.strip():
            raise ValueError("material identity canonical_name is required")
        if not 0 <= self.confidence <= 1:
            raise ValueError("material identity confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "base_entity_id": self.base_entity_id,
            "product_entity_id": self.product_entity_id,
            "product_family_id": self.product_family_id,
            "entity_type": self.entity_type.value,
            "chemical_formula": self.chemical_formula,
            "constituent_entity_ids": self.constituent_entity_ids,
            "head_material": self.head_material,
            "material_family": self.material_family,
            "category": self.category.value,
            "product_form": self.product_form,
            "grade": self.grade,
            "composition": self.composition,
            "surface_coating": self.surface_coating,
            "manufacturing_route": self.manufacturing_route,
            "application": self.application,
            "unresolved_attributes": self.unresolved_attributes,
            "rationale": self.rationale,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class SemanticSpan:
    text: str
    normalized_text: str
    role: SemanticRole
    start: int
    end: int
    evidence_id: str
    entity_id: str | None = None

    def __post_init__(self) -> None:
        if not self.text or not self.normalized_text or not self.evidence_id:
            raise ValueError("semantic span requires text, normalized text and evidence id")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("semantic span offsets are invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "normalized_text": self.normalized_text,
            "role": self.role.value,
            "start": self.start,
            "end": self.end,
            "evidence_id": self.evidence_id,
            "entity_id": self.entity_id,
        }


@dataclass(frozen=True, slots=True)
class NumericTokenResolution:
    raw: str
    start: int
    end: int
    role: NumericTokenRole
    evidence_id: str
    rejected_roles: tuple[NumericTokenRole, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.raw or not self.evidence_id or not self.reason:
            raise ValueError("numeric token resolution requires raw text, evidence and reason")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("numeric token resolution offsets are invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "span": (self.start, self.end),
            "role": self.role.value,
            "evidence_id": self.evidence_id,
            "rejected_roles": tuple(role.value for role in self.rejected_roles),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PurityGrade:
    raw_label: str
    grade_value: float
    basis_component_id: str
    interpretation_kind: GradeInterpretationKind
    schema_id: str
    schema_version: str
    evidence_scope: GradeEvidenceScope
    evidence_ids: tuple[str, ...]
    parser_rule_ids: tuple[str, ...]
    specification_operator: SpecificationOperator | None = None
    nominal_value: float | None = None
    specification_min: float | None = None
    specification_max: float | None = None
    ordered: bool = False

    def __post_init__(self) -> None:
        if not self.raw_label.strip() or not self.schema_id.strip() or not self.schema_version.strip():
            raise ValueError("purity grade requires label and schema identity")
        if (
            not self.basis_component_id.strip()
            or not isfinite(self.grade_value)
            or not 0 < self.grade_value <= 100
        ):
            raise ValueError("purity grade requires a basis component and value in (0, 100]")
        specification_values = (
            self.nominal_value, self.specification_min, self.specification_max,
        )
        if any(value is not None and not isfinite(value) for value in specification_values):
            raise ValueError("purity grade specification values must be finite")

    @property
    def canonical_label(self) -> str:
        return f"{self.schema_id}:{self.grade_value:g}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_label": self.raw_label,
            "grade_value": self.grade_value,
            "basis_component_id": self.basis_component_id,
            "interpretation_kind": self.interpretation_kind.value,
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "evidence_scope": self.evidence_scope.value,
            "evidence_ids": self.evidence_ids,
            "parser_rule_ids": self.parser_rule_ids,
            "specification_operator": (
                self.specification_operator.value if self.specification_operator else None
            ),
            "nominal_value": self.nominal_value,
            "specification_min": self.specification_min,
            "specification_max": self.specification_max,
            "ordered": self.ordered,
            "canonical_label": self.canonical_label,
        }


@dataclass(frozen=True, slots=True)
class MaterialMention:
    raw_text: str
    normalized_text: str
    spans: tuple[SemanticSpan, ...] = ()
    base_entity_text: str | None = None
    entity_type_hint: EntityType = EntityType.UNKNOWN
    chemical_formula: str | None = None
    process: str | None = None
    route: str | None = None
    product_form: str | None = None
    grade: str | None = None
    grade_modifiers: tuple[str, ...] = ()
    purity: float | None = None
    coating: str | None = None
    application: str | None = None
    constituent_entity_ids: tuple[str, ...] = ()
    numeric_grade: PurityGrade | None = None
    numeric_tokens: tuple[NumericTokenResolution, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "spans": tuple(span.to_dict() for span in self.spans),
            "base_entity_text": self.base_entity_text,
            "entity_type_hint": self.entity_type_hint.value,
            "chemical_formula": self.chemical_formula,
            "process": self.process,
            "route": self.route,
            "product_form": self.product_form,
            "grade": self.grade,
            "grade_modifiers": self.grade_modifiers,
            "purity": self.purity,
            "coating": self.coating,
            "application": self.application,
            "constituent_entity_ids": self.constituent_entity_ids,
            "numeric_grade": self.numeric_grade.to_dict() if self.numeric_grade else None,
            "numeric_tokens": tuple(token.to_dict() for token in self.numeric_tokens),
        }


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    outcome: IdentityOutcome
    selected_base_entity_id: str | None = None
    selected_product_entity_id: str | None = None
    product_family_id: str | None = None
    candidate_entity_ids: tuple[str, ...] = ()
    proof_type: IdentityProofType = IdentityProofType.NONE
    evidence_ids: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    unresolved_attributes: tuple[str, ...] = ()

    @property
    def sufficiently_resolved(self) -> bool:
        return self.outcome == IdentityOutcome.RESOLVED and bool(self.selected_base_entity_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "selected_base_entity_id": self.selected_base_entity_id,
            "selected_product_entity_id": self.selected_product_entity_id,
            "product_family_id": self.product_family_id,
            "candidate_entity_ids": self.candidate_entity_ids,
            "proof_type": self.proof_type.value,
            "evidence_ids": self.evidence_ids,
            "conflicts": self.conflicts,
            "unresolved_attributes": self.unresolved_attributes,
            "sufficiently_resolved": self.sufficiently_resolved,
        }


@dataclass(frozen=True, slots=True)
class RetrievalIntent:
    canonical_name: str
    base_entity_id: str | None
    product_entity_id: str | None = None
    product_family_id: str | None = None
    allowed_base_entity_ids: tuple[str, ...] = ()
    allowed_product_entity_ids: tuple[str, ...] = ()
    excluded_entity_ids: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    process: str | None = None
    route: str | None = None
    product_form: str | None = None
    grade: str | None = None
    purity: float | None = None
    identity_outcome: IdentityOutcome = IdentityOutcome.UNKNOWN
    identity_proof_ids: tuple[str, ...] = ()
    numeric_grade: PurityGrade | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "base_entity_id": self.base_entity_id,
            "product_entity_id": self.product_entity_id,
            "product_family_id": self.product_family_id,
            "allowed_base_entity_ids": self.allowed_base_entity_ids,
            "allowed_product_entity_ids": self.allowed_product_entity_ids,
            "excluded_entity_ids": self.excluded_entity_ids,
            "aliases": self.aliases,
            "process": self.process,
            "route": self.route,
            "product_form": self.product_form,
            "grade": self.grade,
            "purity": self.purity,
            "identity_outcome": self.identity_outcome.value,
            "identity_proof_ids": self.identity_proof_ids,
            "numeric_grade": self.numeric_grade.to_dict() if self.numeric_grade else None,
        }


@dataclass(frozen=True, slots=True)
class RegistryRuleSuggestion:
    """A non-authoritative semantic proposal awaiting human review."""

    suggestion_id: str
    normalized_name: str
    proposed_head_material: str | None = None
    proposed_material_family: str | None = None
    proposed_category: MaterialCategory = MaterialCategory.UNKNOWN
    proposed_aliases: tuple[str, ...] = ()
    rationale: str = ""
    confidence: float = 0.0
    status: RegistryRuleStatus = RegistryRuleStatus.DRAFT

    def __post_init__(self) -> None:
        if not self.suggestion_id.strip() or not self.normalized_name.strip():
            raise ValueError("registry suggestion requires id and normalized_name")
        if not 0 <= self.confidence <= 1:
            raise ValueError("registry suggestion confidence must be between 0 and 1")
        if self.status != RegistryRuleStatus.DRAFT:
            raise ValueError("runtime registry suggestions must remain draft until human review")

    def to_dict(self) -> dict[str, Any]:
        return {
            "suggestion_id": self.suggestion_id,
            "normalized_name": self.normalized_name,
            "proposed_head_material": self.proposed_head_material,
            "proposed_material_family": self.proposed_material_family,
            "proposed_category": self.proposed_category.value,
            "proposed_aliases": self.proposed_aliases,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class RequestGap:
    gap_id: str
    gap_type: RequestGapType
    field: str
    reason: str
    required: bool
    options: tuple[str, ...] = ()
    depends_on: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "gap_type": self.gap_type.value,
            "field": self.field,
            "reason": self.reason,
            "required": self.required,
            "options": self.options,
            "depends_on": self.depends_on,
        }


@dataclass(frozen=True, slots=True)
class ProvisionalOption:
    option_type: str
    not_selected_because: str

    def to_dict(self) -> dict[str, str]:
        return {"option_type": self.option_type, "not_selected_because": self.not_selected_because}


@dataclass(frozen=True, slots=True)
class QualificationDimension:
    status: QualificationStatus
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateQualification:
    source_id: str
    identity: QualificationDimension
    factor_kind: QualificationDimension
    subject_type: QualificationDimension
    source_quality: QualificationDimension
    indicator: QualificationDimension
    declared_product: QualificationDimension
    boundary: QualificationDimension
    unit: QualificationDimension
    eligible: bool
    policy: QualificationPolicy = QualificationPolicy.DIRECT
    policy_checks: Mapping[str, QualificationDimension] = field(default_factory=dict)
    primary_exclusion: str | None = None
    additional_exclusions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_checks", MappingProxyType(dict(self.policy_checks)))

    def to_dict(self) -> dict[str, Any]:
        def dimension(value: QualificationDimension) -> dict[str, Any]:
            return {"status": value.status.value, "reasons": value.reasons}
        return {
            "source_id": self.source_id,
            "identity": dimension(self.identity),
            "factor_kind": dimension(self.factor_kind),
            "subject_type": dimension(self.subject_type),
            "source_quality": dimension(self.source_quality),
            "indicator": dimension(self.indicator),
            "declared_product": dimension(self.declared_product),
            "boundary": dimension(self.boundary),
            "unit": dimension(self.unit),
            "eligible": self.eligible,
            "policy": self.policy.value,
            "policy_checks": {key: dimension(item) for key, item in self.policy_checks.items()},
            "primary_exclusion": self.primary_exclusion,
            "additional_exclusions": self.additional_exclusions,
        }


@dataclass(frozen=True, slots=True)
class CandidateAdmission:
    source_id: str
    retrieval_strategy: LinkStrategy
    admitted: bool
    observation_only: bool
    identity_proof_ids: tuple[str, ...] = ()
    source_identity_rule_ids: tuple[str, ...] = ()
    hard_exclusions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "retrieval_strategy": self.retrieval_strategy.value,
            "admitted": self.admitted,
            "observation_only": self.observation_only,
            "identity_proof_ids": self.identity_proof_ids,
            "source_identity_rule_ids": self.source_identity_rule_ids,
            "hard_exclusions": self.hard_exclusions,
        }


@dataclass(frozen=True, slots=True)
class RecallObservation:
    source_id: str
    material_name: str
    retrieval_strategy: LinkStrategy
    retrieval_basis: tuple[str, ...]
    identity_compatibility: str
    factor_kind: FactorKind
    eligible_for_candidate_pool: bool
    primary_exclusion: str | None = None
    additional_exclusions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "material_name": self.material_name,
            "retrieval_strategy": self.retrieval_strategy.value,
            "retrieval_basis": self.retrieval_basis,
            "identity_compatibility": self.identity_compatibility,
            "factor_kind": self.factor_kind.value,
            "eligible_for_candidate_pool": self.eligible_for_candidate_pool,
            "primary_exclusion": self.primary_exclusion,
            "additional_exclusions": self.additional_exclusions,
        }


@dataclass(frozen=True, slots=True)
class RequestResolutionPlan:
    request_id: str
    gaps: tuple[RequestGap, ...]
    next_question: RequestGap | None = None
    provisional_options: tuple[ProvisionalOption, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "gaps": tuple(gap.to_dict() for gap in self.gaps),
            "next_question": self.next_question.to_dict() if self.next_question else None,
            "provisional_options": tuple(option.to_dict() for option in self.provisional_options),
        }


@dataclass(frozen=True, slots=True)
class ResolutionPlan:
    plan_id: str
    candidate_id: str
    gap_ids: tuple[str, ...]
    steps: tuple[RouterType, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "candidate_id": self.candidate_id,
            "gap_ids": self.gap_ids,
            "steps": tuple(step.value for step in self.steps),
        }


@dataclass(frozen=True, slots=True)
class TransformationStep:
    step_id: str
    router_type: RouterType
    method: str
    input_source_ids: tuple[str, ...]
    parameter_ids: tuple[str, ...]
    formula_id: str
    formula_expression: str
    input_values: Mapping[str, float]
    output_value: float
    output_unit: str
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.step_id.strip() or not self.formula_id.strip() or not self.output_unit.strip():
            raise ValueError("transformation step requires id, formula and output unit")
        if not isfinite(self.output_value) or self.output_value < 0:
            raise ValueError("transformation output must be finite and non-negative")
        object.__setattr__(self, "input_values", MappingProxyType(dict(self.input_values)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "router_type": self.router_type.value,
            "method": self.method,
            "input_source_ids": self.input_source_ids,
            "parameter_ids": self.parameter_ids,
            "formula_id": self.formula_id,
            "formula_expression": self.formula_expression,
            "input_values": dict(self.input_values),
            "output_value": self.output_value,
            "output_unit": self.output_unit,
            "assumptions": self.assumptions,
            "warnings": self.warnings,
        }


@dataclass(frozen=True, slots=True)
class LinkAttempt:
    strategy: LinkStrategy
    outcome: LinkOutcome
    candidate_source_ids: tuple[str, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "outcome": self.outcome.value,
            "candidate_source_ids": self.candidate_source_ids,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RecommendationConfidence:
    value: float
    level: str
    top_score: float
    score_margin: float
    evidence_coverage: float
    rationale: tuple[str, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("value", self.value),
            ("top_score", self.top_score),
            ("evidence_coverage", self.evidence_coverage),
        ):
            if not isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite and between 0 and 1")
        if not isfinite(self.score_margin) or self.score_margin < 0:
            raise ValueError("score_margin must be finite and non-negative")
        if self.level not in {"low", "medium", "high"}:
            raise ValueError("confidence level must be low, medium or high")

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "level": self.level,
            "top_score": self.top_score,
            "score_margin": self.score_margin,
            "evidence_coverage": self.evidence_coverage,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class DatabaseVersionAnchor:
    """Identity of the formal factor catalogue observed by one resolution run."""

    catalog_name: str
    catalog_version: str
    database_sha256: str | None
    locator: str
    observed_at: datetime = field(default_factory=_now)
    schema_version: str = "legacy-catalog/v1"
    publisher_id: str = "unverified-legacy"
    publisher_identity_verified: bool = False
    catalog_content_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.catalog_name.strip() or not self.catalog_version.strip() or not self.locator.strip():
            raise ValueError("database anchor requires catalog_name, catalog_version and locator")
        if self.database_sha256 is not None:
            digest = self.database_sha256.strip().lower()
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("database_sha256 must be a lowercase SHA-256 or None")
            object.__setattr__(self, "database_sha256", digest)
        if self.catalog_content_sha256 is not None:
            digest = self.catalog_content_sha256.strip().lower()
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("catalog_content_sha256 must be a lowercase SHA-256 or None")
            object.__setattr__(self, "catalog_content_sha256", digest)

    @property
    def identity(self) -> str:
        return self.database_sha256 or f"{self.catalog_name}:{self.catalog_version}"

    @property
    def content_sha256(self) -> str | None:
        return self.catalog_content_sha256 or self.database_sha256

    @property
    def anchor_sha256(self) -> str:
        return stable_sha256({
            "catalog_name": self.catalog_name,
            "catalog_version": self.catalog_version,
            "database_artifact_sha256": self.database_sha256,
            "catalog_content_sha256": self.content_sha256,
            "locator": self.locator,
            "schema_version": self.schema_version,
            "publisher_id": self.publisher_id,
            "publisher_identity_verified": self.publisher_identity_verified,
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_name": self.catalog_name,
            "catalog_version": self.catalog_version,
            "database_sha256": self.database_sha256,
            "catalog_content_sha256": self.content_sha256,
            "locator": self.locator,
            "observed_at": self.observed_at.isoformat(),
            "schema_version": self.schema_version,
            "publisher_id": self.publisher_id,
            "publisher_identity_verified": self.publisher_identity_verified,
            "anchor_sha256": self.anchor_sha256,
        }


@dataclass(frozen=True, slots=True)
class SemanticIndexAnchor:
    index_version: str
    catalog_database_sha256: str | None
    registry_version: str
    registry_sha256: str
    record_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "index_version": self.index_version,
            "catalog_database_sha256": self.catalog_database_sha256,
            "registry_version": self.registry_version,
            "registry_sha256": self.registry_sha256,
            "record_count": self.record_count,
        }


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Records returned together with the exact catalogue version queried."""

    records: tuple[SourceRecord, ...]
    database_anchor: DatabaseVersionAnchor
    attempts: tuple[LinkAttempt, ...] = ()
    observations: tuple[RecallObservation, ...] = ()
    semantic_index_anchor: SemanticIndexAnchor | None = None
    retrieval_diagnostics: tuple[RetrievalDiagnostic, ...] = ()
    conversion_diagnostics: tuple[RecordConversionDiagnostic, ...] = ()
    funnel: PipelineFunnel | None = None


@dataclass(frozen=True, slots=True)
class RetrievalDiagnostic:
    stage: str
    strategy: str
    query: str
    outcome: str
    reason_code: str
    entity_id: str | None = None
    source_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage, "strategy": self.strategy, "query": self.query,
            "entity_id": self.entity_id, "source_id": self.source_id,
            "outcome": self.outcome, "reason_code": self.reason_code,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class RecordConversionDiagnostic:
    source_id: str
    raw_name: str
    success: bool
    dropped_fields: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id, "raw_name": self.raw_name,
            "success": self.success, "dropped_fields": self.dropped_fields,
            "reason_codes": self.reason_codes,
        }


@dataclass(frozen=True, slots=True)
class QualificationDiagnostic:
    source_id: str
    dimension: str
    status: str
    reason_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id, "dimension": self.dimension,
            "status": self.status, "reason_codes": self.reason_codes,
        }


@dataclass(frozen=True, slots=True)
class PipelineFunnel:
    raw_catalog_records: int = 0
    retrieval_hits: int = 0
    converted_records: int = 0
    qualified_records: int = 0
    candidate_pool: int = 0
    ranked_candidates: int = 0
    returned_candidates: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "raw_catalog_records": self.raw_catalog_records,
            "retrieval_hits": self.retrieval_hits,
            "converted_records": self.converted_records,
            "qualified_records": self.qualified_records,
            "candidate_pool": self.candidate_pool,
            "ranked_candidates": self.ranked_candidates,
            "returned_candidates": self.returned_candidates,
        }


@dataclass(frozen=True, slots=True)
class CandidateExclusion:
    source_id: str
    origin: CandidateOrigin
    reasons: tuple[str, ...]
    candidate_id: str | None = None


@dataclass(frozen=True, slots=True)
class TraceEntry:
    revision: int
    stage: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)
    at: datetime = field(default_factory=_now)
    previous_hash: str = ""
    entry_hash: str = ""

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("trace entry revision must be positive")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))
        expected = stable_sha256({
            "schema_version": TRACE_SCHEMA_VERSION,
            "revision": self.revision,
            "stage": self.stage,
            "message": self.message,
            "details": dict(self.details),
            "at": self.at,
            "previous_hash": self.previous_hash,
        })
        if self.entry_hash and self.entry_hash != expected:
            raise PersistenceIntegrityError("trace entry hash does not match its content")
        object.__setattr__(self, "entry_hash", expected)


@dataclass(slots=True)
class ResolutionTrace:
    """Mutable, appendable explanation record; deliberately not a locked snapshot."""

    trace_id: str
    request_id: str
    request_fingerprint: str
    raw_request_fingerprint: str | None = None
    normalized_business_fingerprint: str | None = None
    database_anchor: DatabaseVersionAnchor | None = None
    revision: int = 0
    entries: list[TraceEntry] = field(default_factory=list)

    def append(self, stage: str, message: str, details: Mapping[str, Any] | None = None) -> TraceEntry:
        self.revision += 1
        previous_hash = self.entries[-1].entry_hash if self.entries else ""
        entry = TraceEntry(
            self.revision, stage, message, details or {}, previous_hash=previous_hash
        )
        self.entries.append(entry)
        return entry

    def verify_hash_chain(self) -> None:
        previous_hash = ""
        if self.revision != len(self.entries):
            raise PersistenceIntegrityError("trace revision does not match entry count")
        for expected_revision, entry in enumerate(self.entries, start=1):
            if entry.revision != expected_revision or entry.previous_hash != previous_hash:
                raise PersistenceIntegrityError("trace hash chain order is invalid")
            expected_hash = stable_sha256({
                "schema_version": TRACE_SCHEMA_VERSION,
                "revision": entry.revision,
                "stage": entry.stage,
                "message": entry.message,
                "details": dict(entry.details),
                "at": entry.at,
                "previous_hash": entry.previous_hash,
            })
            if entry.entry_hash != expected_hash:
                raise PersistenceIntegrityError("trace hash chain content is invalid")
            previous_hash = entry.entry_hash

    @property
    def chain_sha256(self) -> str:
        return self.chain_sha256_at_revision(self.revision)

    def chain_sha256_at_revision(self, revision: int) -> str:
        """Hash an immutable prefix using the same contract as the live trace head."""

        self.verify_hash_chain()
        if revision < 0 or revision > self.revision:
            raise PersistenceIntegrityError("trace prefix revision is outside the stored chain")
        return stable_sha256({
            "schema_version": TRACE_SCHEMA_VERSION,
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "request_fingerprint": self.request_fingerprint,
            "raw_request_fingerprint": self.raw_request_fingerprint,
            "normalized_business_fingerprint": self.normalized_business_fingerprint,
            "database_anchor_sha256": (
                self.database_anchor.anchor_sha256 if self.database_anchor else None
            ),
            "revision": revision,
            "entry_hashes": tuple(
                entry.entry_hash for entry in self.entries[:revision]
            ),
        })

    def set_database_anchor(self, anchor: DatabaseVersionAnchor) -> None:
        self.database_anchor = anchor

    def clone(self) -> ResolutionTrace:
        """Copy the live trace so a store can commit an append atomically."""

        return ResolutionTrace(
            trace_id=self.trace_id,
            request_id=self.request_id,
            request_fingerprint=self.request_fingerprint,
            raw_request_fingerprint=self.raw_request_fingerprint,
            normalized_business_fingerprint=self.normalized_business_fingerprint,
            database_anchor=self.database_anchor,
            revision=self.revision,
            entries=list(self.entries),
        )

    def latest(self, stage: str) -> TraceEntry | None:
        return next((entry for entry in reversed(self.entries) if entry.stage == stage), None)

    def explain(self) -> dict[str, Any]:
        """Return the current answer-oriented view of this appendable trace."""
        local = self.latest("local_retrieval")
        route = self.latest("local_evaluate")
        ranking = self.latest("rank")
        top_k = self.latest("top_k")
        gap_analysis = self.latest("gap_analysis")
        planner = self.latest("resolution_planner")
        re_evaluate = self.latest("re_evaluate")
        normalize = self.latest("normalize")
        process_entries = tuple(
            dict(entry.details)
            for entry in self.entries
            if entry.stage == "process_variant_resolution"
        )
        parameter_databases: dict[str, Mapping[str, Any]] = {}
        for entry in process_entries:
            for anchor in entry.get("parameter_databases", ()):
                digest = anchor.get("database_sha256")
                if digest:
                    parameter_databases.setdefault(digest, anchor)
        return {
            "trace_id": self.trace_id,
            "trace_revision": self.revision,
            "request_fingerprint": self.request_fingerprint,
            "raw_request_fingerprint": self.raw_request_fingerprint or self.request_fingerprint,
            "normalized_business_fingerprint": self.normalized_business_fingerprint,
            "database_version": self.database_anchor.to_dict() if self.database_anchor else None,
            "semantic_registry": dict(normalize.details.get("semantic_registry") or {}) if normalize else None,
            "material_mention": dict(normalize.details.get("material_mention") or {}) if normalize else None,
            "identity_resolution": dict(normalize.details.get("identity_resolution") or {}) if normalize else None,
            "retrieval_intent": dict(normalize.details.get("retrieval_intent") or {}) if normalize else None,
            "semantic_index": (
                dict(local.details.get("semantic_index_anchor") or {}) if local else None
            ),
            "process_resolution": process_entries,
            "parameter_databases": tuple(parameter_databases[key] for key in sorted(parameter_databases)),
            "local_retrieval": dict(local.details) if local else None,
            "retrieval_diagnostics": tuple(local.details.get("retrieval_diagnostics", ())) if local else (),
            "conversion_diagnostics": (
                tuple(top_k.details.get("conversion_diagnostics", ())) if top_k
                else tuple(local.details.get("conversion_diagnostics", ())) if local else ()
            ),
            "pipeline_funnel": (
                dict(top_k.details.get("pipeline_funnel") or {}) if top_k
                else dict(local.details.get("pipeline_funnel") or {}) if local else {}
            ),
            "proxy_decision": dict(route.details) if route else None,
            "excluded_candidates": tuple(top_k.details.get("excluded", ())) if top_k else (),
            "final_ranking": tuple(ranking.details.get("ranking", ())) if ranking else (),
            "selected_candidate_ids": tuple(top_k.details.get("selected_candidate_ids", ())) if top_k else (),
            "link_attempts": tuple(top_k.details.get("link_attempts", ())) if top_k else (),
            "confidence": top_k.details.get("confidence") if top_k else None,
            "resolution_strength": top_k.details.get("resolution_strength") if top_k else None,
            "candidate_gaps": tuple(gap_analysis.details.get("candidate_gaps", ())) if gap_analysis else (),
            "resolution_plans": tuple(planner.details.get("plans", ())) if planner else (),
            "transformation_steps": tuple(re_evaluate.details.get("transformation_steps", ())) if re_evaluate else (),
            "assumptions": tuple(re_evaluate.details.get("assumptions", ())) if re_evaluate else (),
            "warnings": tuple(re_evaluate.details.get("warnings", ())) if re_evaluate else (),
            "required_fields": tuple(top_k.details.get("required_fields", ())) if top_k else (),
            "reason_codes": tuple(top_k.details.get("reason_codes", ())) if top_k else (),
            "material_identity": dict(top_k.details.get("material_identity") or {}) if top_k and top_k.details.get("material_identity") else None,
            "request_gaps": tuple(top_k.details.get("request_gaps", ())) if top_k else (),
            "raw_related_hits": tuple(top_k.details.get("raw_related_hits", ())) if top_k else (),
            "record_qualifications": tuple(top_k.details.get("record_qualifications", ())) if top_k else (),
            "qualification_diagnostics": tuple(top_k.details.get("qualification_diagnostics", ())) if top_k else (),
            "candidate_admissions": tuple(top_k.details.get("candidate_admissions", ())) if top_k else (),
            "required_choice": top_k.details.get("required_choice") if top_k else None,
            "provisional_options": tuple(top_k.details.get("provisional_options", ())) if top_k else (),
            "request_resolution_plan": top_k.details.get("request_resolution_plan") if top_k else None,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize the live trace without claiming snapshot immutability."""
        return {
            **self.explain(),
            "entries": tuple(
                {
                    "revision": entry.revision,
                    "stage": entry.stage,
                    "message": entry.message,
                    "details": dict(entry.details),
                    "at": entry.at.isoformat(),
                    "previous_hash": entry.previous_hash,
                    "entry_hash": entry.entry_hash,
                }
                for entry in self.entries
            ),
            "chain_sha256": self.chain_sha256,
        }


@dataclass(frozen=True, slots=True)
class LockedResolutionEvidenceSnapshot:
    """Byte-stable trace evidence frozen independently from the live trace."""

    trace_id: str
    request_id: str
    trace_revision: int
    trace_chain_sha256: str
    database_anchor_sha256: str
    registry_anchor_sha256: str
    policy_anchor_sha256: str
    canonical_bytes: bytes
    snapshot_sha256: str
    schema_version: str = TRACE_SCHEMA_VERSION

    @classmethod
    def from_trace(
        cls,
        trace: ResolutionTrace,
        *,
        registry_anchor_sha256: str,
        policy_anchor_sha256: str,
    ) -> LockedResolutionEvidenceSnapshot:
        trace.verify_hash_chain()
        if trace.database_anchor is None:
            raise PersistenceIntegrityError("trace has no catalog anchor")
        payload = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "trace_id": trace.trace_id,
            "request_id": trace.request_id,
            "trace_revision": trace.revision,
            "trace_chain_sha256": trace.chain_sha256,
            "database_anchor_sha256": trace.database_anchor.anchor_sha256,
            "registry_anchor_sha256": registry_anchor_sha256,
            "policy_anchor_sha256": policy_anchor_sha256,
            "entries": tuple({
                "revision": entry.revision,
                "stage": entry.stage,
                "message": entry.message,
                "details": dict(entry.details),
                "at": entry.at,
                "previous_hash": entry.previous_hash,
                "entry_hash": entry.entry_hash,
            } for entry in trace.entries),
        }
        frozen = canonical_json_bytes(payload)
        return cls(
            trace_id=trace.trace_id,
            request_id=trace.request_id,
            trace_revision=trace.revision,
            trace_chain_sha256=trace.chain_sha256,
            database_anchor_sha256=trace.database_anchor.anchor_sha256,
            registry_anchor_sha256=registry_anchor_sha256,
            policy_anchor_sha256=policy_anchor_sha256,
            canonical_bytes=frozen,
            snapshot_sha256=hashlib.sha256(frozen).hexdigest(),
        )


def resolution_request_fingerprint(request: ResolutionRequest) -> str:
    """Hash business inputs while deliberately excluding the per-run request ID."""

    payload = {
        "material_name": request.material_name,
        "quantity": request.quantity,
        "quantity_unit": request.quantity_unit,
        "geography": request.geography,
        "year": request.year,
        "product_form": request.product_form,
        "composition": request.composition,
        "production_process": request.production_process,
        "subject_type": request.subject_type.value,
        "boundary": request.boundary,
        "target_factor_unit": request.target_factor_unit,
        "unit_conversion_evidence": (
            {
                "evidence_id": request.unit_conversion_evidence.evidence_id,
                "version": request.unit_conversion_evidence.version,
                "source_canonical_unit": request.unit_conversion_evidence.source_canonical_unit,
                "target_canonical_unit": request.unit_conversion_evidence.target_canonical_unit,
                "multiplier": str(request.unit_conversion_evidence.multiplier),
            }
            if request.unit_conversion_evidence else None
        ),
        "top_k": request.top_k,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalized_business_fingerprint(activity: NormalizedActivity) -> str:
    """Hash normalized business identity, independent of run and display settings."""

    def normalized(value: object) -> object:
        if value is None:
            return None
        return " ".join(str(value).casefold().replace("-", " ").split())

    payload = {
        "material_name": normalized(activity.canonical_name),
        "base_entity_id": (
            activity.identity_resolution.selected_base_entity_id
            if activity.identity_resolution else None
        ),
        "product_entity_id": (
            activity.identity_resolution.selected_product_entity_id
            if activity.identity_resolution else None
        ),
        "quantity_kg": activity.quantity_kg,
        "unresolved_quantity": (
            (activity.original_quantity, normalized(activity.original_quantity_unit))
            if activity.quantity_kg is None else None
        ),
        "geography": normalized(activity.geography),
        "year": activity.year,
        "product_form": normalized(activity.product_form),
        "composition": normalized(activity.composition),
        "production_process": normalized(activity.production_process),
        "subject_type": activity.subject_type.value,
        "numeric_grade": (
            {
                "schema_id": activity.material_mention.numeric_grade.schema_id,
                "grade_value": activity.material_mention.numeric_grade.grade_value,
                "basis": activity.material_mention.numeric_grade.basis_component_id,
            }
            if activity.material_mention and activity.material_mention.numeric_grade else None
        ),
        "boundary": normalized(activity.boundary),
        "target_factor_unit": normalized(activity.target_factor_unit),
        "quantity_base": activity.quantity_base,
        "quantity_base_unit": normalized(activity.quantity_base_unit),
        "activity_dimension": activity.activity_dimension,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Provenance:
    """Traceability for an observed factor value."""

    source_id: str
    source_type: FactorSourceType
    provider: str
    locator: str
    retrieved_at: datetime = field(default_factory=_now)
    citation: str = ""
    excerpt: str = ""
    catalog_locator: str | None = None
    source_document_sha256: str | None = None
    page: str | None = None
    table: str | None = None
    row: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.provider.strip() or not self.locator.strip():
            raise ValueError("provenance requires source_id, provider and locator")


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """An externally observed numeric factor and its source metadata.

    This is the sole ingress for numeric factors.  Adapters must not return a
    bare float; they return records that can be audited later.
    """

    source_id: str
    source_type: FactorSourceType
    provider: str
    locator: str
    material_name: str
    factor_value: float
    factor_unit: str
    geography: str | None = None
    year: int | None = None
    product_form: str | None = None
    composition: str | None = None
    production_process: str | None = None
    boundary: str | None = None
    citation: str = ""
    excerpt: str = ""
    retrieved_at: datetime = field(default_factory=_now)
    metadata: Mapping[str, str] = field(default_factory=dict)
    factor_kind: FactorKind = FactorKind.OTHER
    subject_type: FactorSubjectType = FactorSubjectType.UNKNOWN
    source_quality_status: SourceQualityStatus = SourceQualityStatus.VERIFIED
    admission_eligible: bool = True
    indicator: str | None = None
    declared_product: str | None = None
    boundary_modules: tuple[str, ...] = ()
    catalog_locator: str | None = None
    source_document_sha256: str | None = None
    page: str | None = None
    table: str | None = None
    row: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.material_name.strip():
            raise ValueError("source record requires source_id and material_name")
        if not self.provider.strip() or not self.locator.strip():
            raise ValueError("source record requires provider and locator")
        if not isfinite(self.factor_value) or self.factor_value < 0:
            raise ValueError("factor_value must be a finite non-negative number")
        if not self.factor_unit.strip():
            raise ValueError("factor_unit is required")
        if self.year is not None and not 0 < self.year < 3000:
            raise ValueError("year must be a plausible calendar year")
        if not isinstance(self.factor_kind, FactorKind):
            try:
                object.__setattr__(self, "factor_kind", FactorKind(str(self.factor_kind)))
            except ValueError as exc:
                raise ValueError("factor_kind must be a supported FactorKind") from exc
        if not isinstance(self.subject_type, FactorSubjectType):
            try:
                object.__setattr__(self, "subject_type", FactorSubjectType(str(self.subject_type)))
            except ValueError as exc:
                raise ValueError("subject_type must be a supported FactorSubjectType") from exc
        if not isinstance(self.source_quality_status, SourceQualityStatus):
            try:
                object.__setattr__(
                    self,
                    "source_quality_status",
                    SourceQualityStatus(str(self.source_quality_status).upper()),
                )
            except ValueError as exc:
                raise ValueError("source_quality_status must be VERIFIED, NEEDS_REVIEW or REJECTED") from exc
        if type(self.admission_eligible) is not bool:
            raise ValueError("admission_eligible must be boolean")
        object.__setattr__(self, "boundary_modules", tuple(self.boundary_modules))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def provenance(self) -> Provenance:
        return Provenance(
            source_id=self.source_id,
            source_type=self.source_type,
            provider=self.provider,
            locator=self.locator,
            retrieved_at=self.retrieved_at,
            citation=self.citation,
            excerpt=self.excerpt,
            catalog_locator=self.catalog_locator,
            source_document_sha256=self.source_document_sha256,
            page=self.page,
            table=self.table,
            row=self.row,
        )

    @property
    def content_sha256(self) -> str:
        """Stable digest of every field that can affect a factor decision."""

        return stable_sha256({
            "schema_version": DECISION_SCHEMA_VERSION,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "provider": self.provider,
            "locator": self.locator,
            "material_name": self.material_name,
            "factor_value": self.factor_value,
            "factor_unit": self.factor_unit,
            "geography": self.geography,
            "year": self.year,
            "product_form": self.product_form,
            "composition": self.composition,
            "production_process": self.production_process,
            "boundary": self.boundary,
            "citation": self.citation,
            "excerpt": self.excerpt,
            "metadata": dict(self.metadata),
            "factor_kind": self.factor_kind,
            "subject_type": self.subject_type,
            "source_quality_status": self.source_quality_status,
            "admission_eligible": self.admission_eligible,
            "indicator": self.indicator,
            "declared_product": self.declared_product,
            "boundary_modules": self.boundary_modules,
            "catalog_locator": self.catalog_locator,
            "source_document_sha256": self.source_document_sha256,
            "page": self.page,
            "table": self.table,
            "row": self.row,
        })


@dataclass(frozen=True, slots=True)
class ResolutionRequest:
    material_name: str
    quantity: float
    quantity_unit: str = "kg"
    geography: str | None = None
    year: int | None = None
    product_form: str | None = None
    composition: str | None = None
    production_process: str | None = None
    subject_type: FactorSubjectType = FactorSubjectType.UNKNOWN
    boundary: str = "cradle-to-gate"
    target_factor_unit: str | None = None
    unit_conversion_evidence: UnitConversionEvidence | None = None
    top_k: int = 3
    request_id: str = field(default_factory=lambda: str(uuid4()))
    # Debug-only compatibility field. Formal resolution ignores request-owned
    # thresholds and uses the deployment's immutable policy instead.
    min_score: float | None = None

    def __post_init__(self) -> None:
        if not self.material_name.strip():
            raise ValueError("material_name is required")
        if not isfinite(self.quantity) or self.quantity <= 0:
            raise ValueError("quantity must be a finite positive number")
        if self.year is not None and not 0 < self.year < 3000:
            raise ValueError("year must be a plausible calendar year")
        if not 1 <= self.top_k <= 50:
            raise ValueError("top_k must be between 1 and 50")
        if self.min_score is not None and not 0 <= self.min_score <= 1:
            raise ValueError("min_score must be between 0 and 1")
        if not isinstance(self.subject_type, FactorSubjectType):
            try:
                object.__setattr__(self, "subject_type", FactorSubjectType(str(self.subject_type)))
            except ValueError as exc:
                raise ValueError("subject_type must be a supported FactorSubjectType") from exc

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], *, allow_debug_controls: bool = False
    ) -> ResolutionRequest:
        payload = dict(value)
        if "min_score" in payload and not allow_debug_controls:
            raise ValueError("min_score is a deployment policy and is not accepted by formal requests")
        evidence = payload.get("unit_conversion_evidence")
        if isinstance(evidence, Mapping):
            evidence_payload = dict(evidence)
            evidence_payload["multiplier"] = Decimal(str(evidence_payload["multiplier"]))
            payload["unit_conversion_evidence"] = UnitConversionEvidence(**evidence_payload)
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class MaterialInterpretation:
    canonical_name: str
    aliases: tuple[str, ...] = ()
    product_form: str | None = None
    composition: str | None = None
    production_process: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedActivity:
    request_id: str
    canonical_name: str
    aliases: tuple[str, ...]
    quantity_kg: float | None
    geography: str | None
    year: int | None
    product_form: str | None
    composition: str | None
    production_process: str | None
    subject_type: FactorSubjectType
    boundary: str
    target_factor_unit: str
    normalization_rule_ids: tuple[str, ...] = ()
    original_quantity: float = 0.0
    original_quantity_unit: str = "kg"
    material_identity: MaterialIdentity | None = None
    request_gaps: tuple[RequestGap, ...] = ()
    semantic_registry_version: str | None = None
    material_rule_ids: tuple[str, ...] = ()
    process_rule_ids: tuple[str, ...] = ()
    form_rule_ids: tuple[str, ...] = ()
    relation_ids: tuple[str, ...] = ()
    registry_suggestion: RegistryRuleSuggestion | None = None
    material_mention: MaterialMention | None = None
    identity_resolution: IdentityResolution | None = None
    retrieval_intent: RetrievalIntent | None = None
    quantity_base: float | None = None
    quantity_base_unit: str | None = None
    activity_dimension: str | None = None
    unit_reason_codes: tuple[str, ...] = ()
    unit_conversion_evidence: UnitConversionEvidence | None = None
    target_factor_unit_derived: bool = False


@dataclass(frozen=True, slots=True)
class MaterialClass:
    name: str
    family: str = "unknown"
    rationale: str = ""
    confidence: float = 0.0
    category: MaterialCategory = MaterialCategory.UNKNOWN

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("material class name is required")
        if not 0 <= self.confidence <= 1:
            raise ValueError("material class confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class SemanticAssessment:
    eligible: bool = True
    note: str = ""
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Candidate:
    candidate_id: str
    origin: CandidateOrigin
    source: SourceRecord
    provenance: Provenance
    factor_value: float
    factor_unit: str
    score: float
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]
    dimensions: Mapping[str, float]
    proxy_material: str | None = None
    proxy_class: str | None = None
    evidence_coverage: float = 0.0
    evidence_gaps: tuple[str, ...] = ()
    resolution_type: ResolutionType = ResolutionType.DIRECT_EXACT
    result_tier: ResultTier = ResultTier.PRIMARY_RECOMMENDATION
    resolution_strength: float = 0.0
    gaps: tuple[ResolutionGap, ...] = ()
    transformation_steps: tuple[TransformationStep, ...] = ()
    parameter_evidence_ids: tuple[str, ...] = ()
    base_source_ids: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    resolved_activity_value: float | None = None
    resolved_activity_unit: str | None = None
    activity_dimension: str | None = None
    resolved_quantity_kg: float | None = None
    total_emissions_kgco2e: float | None = None

    def __post_init__(self) -> None:
        if self.provenance.source_id != self.source.source_id:
            raise ValueError("candidate provenance must point to its source record")
        if not isfinite(self.factor_value) or self.factor_value < 0:
            raise ValueError("candidate factor must be finite and non-negative")
        if not 0 <= self.score <= 1:
            raise ValueError("candidate score must be between 0 and 1")
        if not self.factor_unit.strip():
            raise ValueError("candidate factor unit is required")
        if not isfinite(self.evidence_coverage) or not 0 <= self.evidence_coverage <= 1:
            raise ValueError("candidate evidence coverage must be between 0 and 1")
        if not isfinite(self.resolution_strength) or not 0 <= self.resolution_strength <= 1:
            raise ValueError("candidate resolution strength must be between 0 and 1")
        if self.resolved_quantity_kg is not None and (
            not isfinite(self.resolved_quantity_kg) or self.resolved_quantity_kg <= 0
        ):
            raise ValueError("resolved quantity must be finite and positive")
        if (
            self.resolved_quantity_kg is not None
            and self.activity_dimension is not None
            and self.activity_dimension != "MASS"
        ):
            raise ValueError("resolved_quantity_kg is valid only for mass activity")
        if self.resolved_activity_value is not None and (
            not isfinite(self.resolved_activity_value) or self.resolved_activity_value <= 0
        ):
            raise ValueError("resolved activity value must be finite and positive")
        if self.resolved_activity_value is not None and not self.resolved_activity_unit:
            raise ValueError("resolved activity unit is required with a resolved activity value")
        if self.total_emissions_kgco2e is not None and (
            not isfinite(self.total_emissions_kgco2e) or self.total_emissions_kgco2e < 0
        ):
            raise ValueError("total emissions must be finite and non-negative")
        object.__setattr__(self, "dimensions", MappingProxyType(dict(self.dimensions)))

    @property
    def content_sha256(self) -> str:
        return stable_sha256({
            "schema_version": DECISION_SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "origin": self.origin,
            "source_content_sha256": self.source.content_sha256,
            "provenance": {
                "source_id": self.provenance.source_id,
                "source_type": self.provenance.source_type,
                "provider": self.provenance.provider,
                "locator": self.provenance.locator,
                "citation": self.provenance.citation,
                "excerpt": self.provenance.excerpt,
                "catalog_locator": self.provenance.catalog_locator,
                "source_document_sha256": self.provenance.source_document_sha256,
                "page": self.provenance.page,
                "table": self.provenance.table,
                "row": self.provenance.row,
            },
            "factor_value": self.factor_value,
            "factor_unit": self.factor_unit,
            "score": self.score,
            "reasons": self.reasons,
            "limitations": self.limitations,
            "dimensions": dict(self.dimensions),
            "proxy_material": self.proxy_material,
            "proxy_class": self.proxy_class,
            "evidence_coverage": self.evidence_coverage,
            "evidence_gaps": self.evidence_gaps,
            "resolution_type": self.resolution_type,
            "result_tier": self.result_tier,
            "resolution_strength": self.resolution_strength,
            "gaps": self.gaps,
            "transformation_steps": self.transformation_steps,
            "parameter_evidence_ids": self.parameter_evidence_ids,
            "base_source_ids": self.base_source_ids,
            "assumptions": self.assumptions,
            "warnings": self.warnings,
            "resolved_activity_value": self.resolved_activity_value,
            "resolved_activity_unit": self.resolved_activity_unit,
            "activity_dimension": self.activity_dimension,
            "resolved_quantity_kg": self.resolved_quantity_kg,
            "total_emissions_kgco2e": self.total_emissions_kgco2e,
        })


@dataclass(frozen=True, slots=True)
class DerivedFactorCandidate:
    candidate_id: str
    resolution_type: ResolutionType
    base_source_ids: tuple[str, ...]
    parameter_evidence_ids: tuple[str, ...]
    transformation_steps: tuple[TransformationStep, ...]
    factor_value: float
    factor_unit: str
    boundary: str | None
    geography: str | None
    year: int | None
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]
    evidence_coverage: float
    resolution_strength: float
    provenance_lineage: tuple[str, ...]
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    resolved_activity_value: float | None = None
    resolved_activity_unit: str | None = None
    activity_dimension: str | None = None
    resolved_quantity_kg: float | None = None
    total_emissions_kgco2e: float | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.base_source_ids:
            raise ValueError("derived candidate requires id and base source lineage")
        if not isfinite(self.factor_value) or self.factor_value < 0:
            raise ValueError("derived factor must be finite and non-negative")
        if not 0 <= self.evidence_coverage <= 1 or not 0 <= self.resolution_strength <= 1:
            raise ValueError("derived coverage and strength must be between 0 and 1")
        if self.resolved_quantity_kg is not None and (
            not isfinite(self.resolved_quantity_kg) or self.resolved_quantity_kg <= 0
        ):
            raise ValueError("resolved quantity must be finite and positive")
        if (
            self.resolved_quantity_kg is not None
            and self.activity_dimension is not None
            and self.activity_dimension != "MASS"
        ):
            raise ValueError("resolved_quantity_kg is valid only for mass activity")
        if self.resolved_activity_value is not None and (
            not isfinite(self.resolved_activity_value) or self.resolved_activity_value <= 0
        ):
            raise ValueError("resolved activity value must be finite and positive")
        if self.resolved_activity_value is not None and not self.resolved_activity_unit:
            raise ValueError("resolved activity unit is required with a resolved activity value")
        if self.total_emissions_kgco2e is not None and (
            not isfinite(self.total_emissions_kgco2e) or self.total_emissions_kgco2e < 0
        ):
            raise ValueError("total emissions must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class Recommendation:
    request_id: str
    status: ResolutionStatus
    candidates: tuple[Candidate, ...]
    follow_up: FollowUp | None = None
    message: str = ""
    trace: ResolutionTrace | None = None
    confidence: RecommendationConfidence | None = None
    resolution_strength: RecommendationConfidence | None = None
    reviewable_candidates: tuple[Candidate, ...] = ()
    reviewable_candidate_reasons: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    diagnostic_candidates: tuple[Candidate, ...] = ()
    missing_gaps: tuple[ResolutionGap, ...] = ()
    questions: tuple[str, ...] = ()
    accounting_assignments: tuple[AccountingAssignment, ...] = ()
    reason_codes: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=_now)
    revision: int = 1
    database_anchor_sha256: str | None = None
    registry_anchor_sha256: str | None = None
    policy_anchor_sha256: str | None = None
    schema_version: str = DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reviewable_candidate_reasons",
            MappingProxyType(dict(self.reviewable_candidate_reasons)),
        )
        if self.revision < 1:
            raise ValueError("recommendation revision must be positive")

    @property
    def content_sha256(self) -> str:
        return stable_sha256({
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "revision": self.revision,
            "status": self.status,
            "candidate_digests": tuple(item.content_sha256 for item in self.candidates),
            "reviewable_candidate_digests": tuple(
                item.content_sha256 for item in self.reviewable_candidates
            ),
            "diagnostic_candidate_digests": tuple(
                item.content_sha256 for item in self.diagnostic_candidates
            ),
            "follow_up": self.follow_up,
            "message": self.message,
            "confidence": self.confidence,
            "resolution_strength": self.resolution_strength,
            "reviewable_candidate_reasons": dict(self.reviewable_candidate_reasons),
            "missing_gaps": self.missing_gaps,
            "questions": self.questions,
            "accounting_assignments": self.accounting_assignments,
            "reason_codes": self.reason_codes,
            "database_anchor_sha256": self.database_anchor_sha256,
            "registry_anchor_sha256": self.registry_anchor_sha256,
            "policy_anchor_sha256": self.policy_anchor_sha256,
        })


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    request_id: str
    candidate_id: str
    reviewer: str
    status: ApprovalStatus
    note: str = ""
    created_at: datetime = field(default_factory=_now)
    mode: ApprovalMode = ApprovalMode.STANDARD
    candidate_content_sha256: str | None = None
    recommendation_content_sha256: str | None = None
    recommendation_revision: int | None = None
    database_anchor_sha256: str | None = None
    registry_anchor_sha256: str | None = None
    policy_anchor_sha256: str | None = None
    trace_revision: int | None = None
    trace_chain_sha256: str | None = None
    reviewer_identity: str | None = None
    schema_version: str = DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.request_id.strip() or not self.candidate_id.strip() or not self.reviewer.strip():
            raise ValueError("approval requires request_id, candidate_id and reviewer")
        if self.reviewer_identity is not None and self.reviewer_identity != self.reviewer:
            raise PersistenceIntegrityError(
                "approval reviewer identity must match the verified reviewer"
            )
        if not isinstance(self.mode, ApprovalMode):
            try:
                object.__setattr__(self, "mode", ApprovalMode(str(self.mode)))
            except ValueError as exc:
                raise ValueError("approval mode is not supported") from exc

    @property
    def is_integrity_bound(self) -> bool:
        return all((
            self.candidate_content_sha256,
            self.recommendation_content_sha256,
            self.recommendation_revision is not None,
            self.database_anchor_sha256,
            self.registry_anchor_sha256,
            self.policy_anchor_sha256,
            self.trace_revision is not None,
            self.trace_chain_sha256,
            self.reviewer_identity,
        ))

    @property
    def content_sha256(self) -> str:
        return stable_sha256({
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "candidate_id": self.candidate_id,
            "reviewer": self.reviewer,
            "reviewer_identity": self.reviewer_identity,
            "status": self.status,
            "note": self.note,
            "mode": self.mode,
            "candidate_content_sha256": self.candidate_content_sha256,
            "recommendation_content_sha256": self.recommendation_content_sha256,
            "recommendation_revision": self.recommendation_revision,
            "database_anchor_sha256": self.database_anchor_sha256,
            "registry_anchor_sha256": self.registry_anchor_sha256,
            "policy_anchor_sha256": self.policy_anchor_sha256,
            "trace_revision": self.trace_revision,
            "trace_chain_sha256": self.trace_chain_sha256,
        })

    def matches_decision(
        self,
        *,
        status: ApprovalStatus,
        reviewer: str,
        note: str,
        mode: ApprovalMode,
    ) -> bool:
        """Compare the user-visible command fields, excluding commit-time bindings."""

        return (
            self.status == status
            and self.reviewer == reviewer
            and self.reviewer_identity == reviewer
            and self.note == note
            and self.mode == mode
        )


@dataclass(frozen=True, slots=True)
class LockedResolution:
    request_id: str
    candidate: Candidate
    reviewer: str
    approval: ApprovalRecord
    locked_at: datetime = field(default_factory=_now)
    evidence_snapshot: LockedResolutionEvidenceSnapshot | None = None
    candidate_content_sha256: str | None = None
    recommendation_content_sha256: str | None = None
    approval_content_sha256: str | None = None
    schema_version: str = LOCK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.request_id.strip() or not self.reviewer.strip():
            raise ValueError("locked resolution requires request_id and reviewer")
        if self.candidate.candidate_id != self.approval.candidate_id:
            raise ValueError("lock approval must reference the locked candidate")
        if self.request_id != self.approval.request_id:
            raise ValueError("lock approval must reference the locked request")
        if self.approval.status != ApprovalStatus.LOCKED:
            raise ValueError("locked resolution requires a locked approval")
        if self.evidence_snapshot is not None and self.evidence_snapshot.request_id != self.request_id:
            raise ValueError("locked evidence snapshot belongs to another request")

    @property
    def content_sha256(self) -> str:
        return stable_sha256({
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "candidate_content_sha256": self.candidate_content_sha256,
            "recommendation_content_sha256": self.recommendation_content_sha256,
            "approval_content_sha256": self.approval_content_sha256,
            "evidence_snapshot_sha256": (
                self.evidence_snapshot.snapshot_sha256 if self.evidence_snapshot else None
            ),
            "reviewer": self.reviewer,
        })


@dataclass(frozen=True, slots=True)
class AuditEvent:
    stage: str
    message: str
    at: datetime = field(default_factory=_now)
