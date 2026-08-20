"""Versioned, entity-first material semantics used before factor retrieval.

The registry contains no emission-factor values. Only ACTIVE rules can affect
runtime identity. Text/LLM similarity can propose DRAFT rules, but cannot
admit a factor candidate or create a proxy relation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Protocol, Sequence

from .matching import normalize_text
from .models import (
    EntityType,
    IdentityOutcome,
    IdentityProofType,
    IdentityResolution,
    MaterialCategory,
    MaterialIdentity,
    MaterialMention,
    RegistryRuleStatus,
    RegistryRuleSuggestion,
    RetrievalIntent,
    SemanticRelationType,
    SemanticRole,
    SemanticSpan,
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


class MaterialSemanticRegistryPort(Protocol):
    version: str

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

    @staticmethod
    def _active(values: Sequence[object]) -> tuple[object, ...]:
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
        value: str, rules: Sequence[ProcessRule | FormRule]
    ) -> tuple[ProcessRule | FormRule, str, int, int] | None:
        matches: list[tuple[ProcessRule | FormRule, str, int, int]] = []
        for rule in rules:
            for raw_alias in rule.aliases:
                alias = _norm(raw_alias)
                occurrence = _first_occurrence(value, alias)
                if occurrence:
                    matches.append((rule, alias, occurrence[0], occurrence[1]))
        matches.sort(key=lambda item: (-(item[3] - item[2]), item[0].rule_id))
        return matches[0] if matches else None

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
            value, self._active(self.process_rules)  # type: ignore[arg-type]
        )
        process_input_match = None if process_match else self._best_rule_match(
            _norm(production_process), self._active(self.process_rules)  # type: ignore[arg-type]
        )
        form_match = self._best_rule_match(
            value, self._active(self.form_rules)  # type: ignore[arg-type]
        )
        form_input_match = None if form_match else self._best_rule_match(
            _norm(product_form), self._active(self.form_rules)  # type: ignore[arg-type]
        )

        selected_rules = tuple(dict.fromkeys(match[0] for match in material_matches))
        explicit_composite = next(
            (rule for rule in selected_rules if rule.entity_type == EntityType.COMPOSITE), None
        )
        composite = explicit_composite is not None or len(selected_rules) > 1
        material_rule = explicit_composite or (selected_rules[0] if len(selected_rules) == 1 else None)
        process_rule = (process_match or process_input_match)[0] if (process_match or process_input_match) else None
        form_rule = (form_match or form_input_match)[0] if (form_match or form_input_match) else None

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
            rule, alias, start, end = process_match
            spans.append(SemanticSpan(
                text=value[start:end], normalized_text=alias, role=SemanticRole.PROCESS,
                start=start, end=end, evidence_id=rule.rule_id,
            ))
        if form_match:
            rule, alias, start, end = form_match
            spans.append(SemanticSpan(
                text=value[start:end], normalized_text=alias, role=SemanticRole.PRODUCT_FORM,
                start=start, end=end, evidence_id=rule.rule_id,
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

        purity_match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*%", value)
        purity = float(purity_match.group(1)) if purity_match else None
        if purity_match:
            spans.append(SemanticSpan(
                text=purity_match.group(0), normalized_text=purity_match.group(0),
                role=SemanticRole.PURITY, start=purity_match.start(), end=purity_match.end(),
                evidence_id="purity.percent/v1",
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
            composition=_norm(composition) or None,
            manufacturing_route=tuple(filter(None, (resolved_process, route))),
            rationale=(
                f"entity-first semantic registry {self.version}: "
                f"materials={material_rule_ids or ('unmatched',)}, "
                f"process={process_rule.rule_id if process_rule else 'unmatched'}, "
                f"form={form_rule.rule_id if form_rule else 'unmatched'}"
            ),
            confidence=confidence,
        )
        identity = self._enrich_identity(identity, value, production_process)
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
        # Base-entity aliases must not erase request qualifiers. For example,
        # "莫来石" is not a full synonym for "电熔莫来石" when the source is
        # explicitly sintered. Product-entity aliases remain safe because they
        # preserve the reviewed route/product identity.
        intent_aliases = (
            aliases
            if product_entity_id or not (resolved_process or resolved_form or purity is not None)
            else ()
        )
        retrieval_intent = RetrievalIntent(
            canonical_name=value,
            base_entity_id=base_entity_id,
            product_entity_id=product_entity_id,
            product_family_id=product_family_id,
            allowed_base_entity_ids=(base_entity_id,) if base_entity_id else (),
            aliases=intent_aliases,
            process=resolved_process,
            route=route,
            product_form=resolved_form,
            grade=identity.grade,
            purity=purity,
            identity_outcome=identity_resolution.outcome,
            identity_proof_ids=identity_resolution.evidence_ids,
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
    version="material-semantic-registry/2.0.0",
    material_rules=(
        MaterialRule("material.zircon_mullite/v2", "zircon_mullite", "composite_materials", MaterialCategory.MANUFACTURED_MINERAL, ("锆莫来石", "zircon mullite"), entity_id="mat.composite.zircon_mullite", entity_type=EntityType.COMPOSITE, product_family_id="family.composite_materials", constituent_entity_ids=("mat.compound.zirconia", "mat.mineral.mullite")),
        MaterialRule("material.primary_aluminium/v2", "aluminium", "aluminium_products", MaterialCategory.METAL, ("原铝", "电解铝", "primary aluminium", "primary aluminum"), entity_id="mat.element.aluminium", entity_type=EntityType.ELEMENTAL_METAL, chemical_formula="Al", product_entity_id="mat.product.primary_aluminium", product_family_id="family.aluminium_products", route="primary"),
        MaterialRule("material.secondary_aluminium/v2", "aluminium", "aluminium_products", MaterialCategory.RECYCLED_MATERIAL, ("再生铝", "secondary aluminium", "secondary aluminum", "recycled aluminium", "recycled aluminum"), entity_id="mat.element.aluminium", entity_type=EntityType.ELEMENTAL_METAL, chemical_formula="Al", product_entity_id="mat.product.secondary_aluminium", product_family_id="family.aluminium_products", route="secondary_recycling"),
        MaterialRule("material.aluminium_ingot/v2", "aluminium", "aluminium_products", MaterialCategory.METAL, ("铝锭", "aluminium ingot", "aluminum ingot"), entity_id="mat.element.aluminium", entity_type=EntityType.ELEMENTAL_METAL, chemical_formula="Al", product_entity_id="mat.product.aluminium_ingot", product_family_id="family.aluminium_products"),
        MaterialRule("material.aluminium_alloy/v2", "aluminium", "aluminium_alloys", MaterialCategory.METAL, ("铝合金", "aluminium alloy", "aluminum alloy"), entity_id="mat.element.aluminium", entity_type=EntityType.ALLOY, chemical_formula="Al", product_entity_id="mat.alloy.aluminium", product_family_id="family.aluminium_alloys"),
        MaterialRule("material.alumina/v2", "alumina", "alumina_products", MaterialCategory.MANUFACTURED_MINERAL, ("氧化铝", "aluminium oxide", "aluminum oxide", "alumina", "al2o3", "fused alumina"), entity_id="mat.compound.alumina", entity_type=EntityType.OXIDE, chemical_formula="Al2O3", product_family_id="family.alumina_products"),
        MaterialRule("material.bauxite/v2", "bauxite", "bauxite_products", MaterialCategory.NATURAL_MINERAL, ("铝土矿", "铝矾土", "bauxite"), entity_id="mat.ore.bauxite", entity_type=EntityType.MINERAL, product_family_id="family.bauxite_products"),
        MaterialRule("material.aluminium/v2", "aluminium", "aluminium_products", MaterialCategory.METAL, ("铝", "aluminium", "aluminum", "al metal", "metal aluminium", "metal aluminum"), entity_id="mat.element.aluminium", entity_type=EntityType.ELEMENTAL_METAL, chemical_formula="Al", product_family_id="family.aluminium_products"),
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
)
