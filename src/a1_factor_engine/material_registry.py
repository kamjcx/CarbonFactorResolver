"""Versioned deterministic material semantics used before factor retrieval.

The registry contains no emission-factor values.  Only ACTIVE rules can affect
runtime resolution; draft suggestions are separate review artifacts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Protocol, Sequence

from .matching import normalize_text
from .models import (
    MaterialCategory,
    MaterialIdentity,
    RegistryRuleStatus,
    RegistryRuleSuggestion,
    SemanticRelationType,
    SourceRecord,
)


def _norm(value: str | None) -> str:
    return normalize_text(value).value


def _contains(value: str, alias: str) -> bool:
    if not alias:
        return False
    if any("\u4e00" <= char <= "\u9fff" for char in alias):
        return alias in value
    return re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", value) is not None


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
class RegistryResolution:
    identity: MaterialIdentity
    registry_version: str
    material_rule_ids: tuple[str, ...] = ()
    process_rule_ids: tuple[str, ...] = ()
    form_rule_ids: tuple[str, ...] = ()
    relation_ids: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    suggestion: RegistryRuleSuggestion | None = None

    @property
    def sufficiently_identified(self) -> bool:
        return bool(self.identity.head_material and self.identity.category != MaterialCategory.UNKNOWN)


class MaterialSemanticRegistryPort(Protocol):
    version: str

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

    @staticmethod
    def _active(values: Sequence[object]) -> tuple[object, ...]:
        return tuple(
            value for value in values
            if getattr(value, "status", None) == RegistryRuleStatus.ACTIVE
        )

    def resolve(
        self,
        name: str,
        *,
        product_form: str | None = None,
        composition: str | None = None,
        production_process: str | None = None,
    ) -> RegistryResolution:
        value = _norm(name)
        material_matches = sorted(
            (
                (rule, alias)
                for rule in self._active(self.material_rules)
                for alias in (_norm(item) for item in rule.aliases)
                if _contains(value, alias)
            ),
            key=lambda item: (-len(item[1]), item[0].rule_id),
        )
        material_rule = material_matches[0][0] if material_matches else None

        process_value = " ".join(filter(None, (value, _norm(production_process))))
        process_matches = sorted(
            (
                (rule, alias)
                for rule in self._active(self.process_rules)
                for alias in (_norm(item) for item in rule.aliases)
                if _contains(process_value, alias)
            ),
            key=lambda item: (-len(item[1]), item[0].rule_id),
        )
        process_rule = process_matches[0][0] if process_matches else None

        form_value = " ".join(filter(None, (value, _norm(product_form))))
        form_matches = sorted(
            (
                (rule, alias)
                for rule in self._active(self.form_rules)
                for alias in (_norm(item) for item in rule.aliases)
                if _contains(form_value, alias)
            ),
            key=lambda item: (-len(item[1]), item[0].rule_id),
        )
        form_rule = form_matches[0][0] if form_matches else None

        material_rule_ids = (material_rule.rule_id,) if material_rule else ()
        process_rule_ids = (process_rule.rule_id,) if process_rule else ()
        form_rule_ids = (form_rule.rule_id,) if form_rule else ()
        relation_ids = tuple(
            relation.relation_id
            for relation in self._active(self.relations)
            if relation.source_rule_id in material_rule_ids
        )

        identity = MaterialIdentity(
            canonical_name=value,
            head_material=material_rule.head_material if material_rule else None,
            material_family=material_rule.material_family if material_rule else None,
            category=material_rule.category if material_rule else MaterialCategory.UNKNOWN,
            product_form=(form_rule.product_form if form_rule else _norm(product_form) or None),
            composition=_norm(composition) or None,
            manufacturing_route=tuple(filter(None, (
                process_rule.process if process_rule else _norm(production_process) or None,
            ))),
            rationale=(
                f"semantic registry {self.version}: "
                f"material={material_rule.rule_id if material_rule else 'unmatched'}, "
                f"process={process_rule.rule_id if process_rule else 'unmatched'}, "
                f"form={form_rule.rule_id if form_rule else 'unmatched'}"
            ),
            confidence=material_rule.confidence if material_rule else 0.4,
        )
        identity = self._enrich_identity(identity, value, production_process)
        aliases = tuple(
            dict.fromkeys(
                _norm(alias)
                for rule in (material_rule,) if rule is not None
                for alias in rule.aliases
                if _norm(alias) and _norm(alias) != value
            )
        )
        return RegistryResolution(
            identity=identity,
            registry_version=self.version,
            material_rule_ids=material_rule_ids,
            process_rule_ids=process_rule_ids,
            form_rule_ids=form_rule_ids,
            relation_ids=relation_ids,
            aliases=aliases,
        )

    @staticmethod
    def _enrich_identity(
        identity: MaterialIdentity, value: str, production_process: str | None
    ) -> MaterialIdentity:
        if identity.head_material != "steel":
            return identity
        is_fiber = identity.product_form == "fiber"
        grade = "AISI 446 / UNS S44600" if any(token in value for token in ("446", "s44600")) else None
        family = (
            "ferritic_stainless_steel"
            if grade or "耐热不锈钢" in value
            else identity.material_family
        )
        coating = (
            "copper"
            if any(token in value for token in ("copper plated", "copper plating", "镀铜"))
            else "none"
            if any(token in value for token in ("uncoated", "without copper", "未镀铜"))
            else None
        )
        if is_fiber and grade is None:
            unresolved = () if coating is not None else (
                "steel_fiber_type", "steel_grade_or_family", "surface_coating", "application"
            )
        elif is_fiber and grade is not None and not (production_process or identity.manufacturing_route):
            unresolved = ("manufacturing_route",)
        else:
            unresolved = ()
        return replace(
            identity,
            material_family=family,
            grade=grade,
            surface_coating=coating,
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
            "material_rule_ids": ",".join(resolved.material_rule_ids),
            "process_rule_ids": ",".join(resolved.process_rule_ids),
            "form_rule_ids": ",".join(resolved.form_rule_ids),
            "relation_ids": ",".join(resolved.relation_ids),
            "material_category": identity.category.value,
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
    version="material-semantic-registry/1.0.0",
    material_rules=(
        MaterialRule("material.mullite/v1", "mullite", "mullite_products", MaterialCategory.MANUFACTURED_MINERAL, ("莫来石", "mullite")),
        MaterialRule("material.spinel/v1", "spinel", "spinel_products", MaterialCategory.MANUFACTURED_MINERAL, ("尖晶石", "spinel")),
        MaterialRule("material.aluminosilicate/v1", "aluminosilicate", "aluminosilicate_refractory", MaterialCategory.MANUFACTURED_MINERAL, ("硅酸铝", "aluminosilicate", "ceramic fiber", "陶瓷纤维")),
        MaterialRule("material.alumina/v1", "alumina", "alumina_products", MaterialCategory.MANUFACTURED_MINERAL, ("氧化铝", "alumina", "fused alumina")),
        MaterialRule("material.corundum/v1", "corundum", "corundum_products", MaterialCategory.MANUFACTURED_MINERAL, ("刚玉", "corundum")),
        MaterialRule("material.magnesia/v1", "magnesia", "magnesia_products", MaterialCategory.MANUFACTURED_MINERAL, ("镁砂", "氧化镁", "magnesia")),
        MaterialRule("material.steel/v1", "steel", "steel_products", MaterialCategory.METAL, ("不锈钢", "合金钢", "steel", "stainless", "钢")),
    ),
    process_rules=(
        ProcessRule("process.electrofused/v1", "electrofused", ("电熔", "electrofused", "electric fusion", "fused")),
        ProcessRule("process.sintered/v1", "sintered", ("烧结", "sintered")),
        ProcessRule("process.calcined/v1", "calcined", ("煅烧", "calcined")),
        ProcessRule("process.eaf/v1", "electric arc furnace", ("electric arc furnace", "eaf", "电弧炉")),
        ProcessRule("process.bof/v1", "basic oxygen furnace", ("basic oxygen furnace", "bof", "转炉")),
    ),
    form_rules=(
        FormRule("form.fiber/v1", "fiber", ("钢纤维", "陶瓷纤维", "纤维", "fiber", "fibre")),
        FormRule("form.coil/v1", "coil", ("钢卷", "卷材", "coil")),
        FormRule("form.brick/v1", "brick", ("砖", "brick")),
        FormRule("form.powder/v1", "powder", ("粉", "粉末", "powder")),
    ),
    relations=(
        TypedRelation("relation.mullite-is-aluminosilicate/v1", "material.mullite/v1", SemanticRelationType.IS_A, "aluminosilicate_mineral"),
        TypedRelation("relation.spinel-is-engineered-oxide/v1", "material.spinel/v1", SemanticRelationType.IS_A, "engineered_mixed_oxide"),
        TypedRelation("relation.corundum-is-alumina/v1", "material.corundum/v1", SemanticRelationType.IS_A, "alumina_products"),
    ),
)
