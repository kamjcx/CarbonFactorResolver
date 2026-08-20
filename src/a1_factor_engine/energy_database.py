"""Version-anchored refractory energy evidence database and Process Router adapter."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

from .material_registry import DEFAULT_MATERIAL_REGISTRY, MaterialSemanticRegistryPort
from .models import (
    NormalizedActivity,
    ParameterEvidence,
    ParameterSourceType,
    SourceRecord,
)
from .ports import ProcessParameterRepositoryPort

ENERGY_DATABASE_SCHEMA_VERSION = "3"


def _norm(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class EnergyDatabaseAnchor:
    database_name: str
    dataset_version: str
    database_sha256: str
    locator: str
    schema_version: str = ENERGY_DATABASE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, str]:
        return {
            "database_name": self.database_name,
            "dataset_version": self.dataset_version,
            "database_sha256": self.database_sha256,
            "locator": self.locator,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class EnergyQuotaRecord:
    record_id: str
    product_name: str
    head_material: str
    production_process: str
    quota_level: int
    value_kgce_per_t: float
    standard_code: str
    table_number: str
    physical_page: int
    canonical_product: str = ""
    printed_page: int | None = None
    product_group: str = ""
    product_form: str = ""
    applicability: str = ""
    note_ids: tuple[str, ...] = ()
    source_locator: str = ""
    source_sha256: str = ""
    active: bool = True

    def __post_init__(self) -> None:
        if not self.record_id.strip() or not self.product_name.strip() or not self.head_material.strip():
            raise ValueError("energy quota record requires id, product name and head material")
        if self.quota_level not in {1, 2, 3}:
            raise ValueError("energy quota level must be 1, 2 or 3")
        if not isfinite(self.value_kgce_per_t) or self.value_kgce_per_t <= 0:
            raise ValueError("energy quota value must be positive")
        if self.physical_page < 1:
            raise ValueError("energy quota physical page must be positive")


@dataclass(frozen=True, slots=True)
class EnergyConversionRecord:
    conversion_id: str
    parameter_name: str
    energy_carrier: str
    value_min: float
    value_max: float
    unit: str
    basis: str
    source_type: ParameterSourceType
    provider: str
    locator: str
    citation: str = ""
    quality_note: str = ""
    standard_code: str = ""
    physical_page: int | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    active: bool = True

    def __post_init__(self) -> None:
        if not self.conversion_id.strip() or not self.parameter_name.strip() or not self.unit.strip():
            raise ValueError("energy conversion requires id, parameter name and unit")
        if (
            not isfinite(self.value_min)
            or not isfinite(self.value_max)
            or self.value_min <= 0
            or self.value_max < self.value_min
        ):
            raise ValueError("energy conversion bounds must be positive and ordered")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def is_exact(self) -> bool:
        return abs(self.value_max - self.value_min) <= 1e-12


@dataclass(frozen=True, slots=True)
class ScopedProcessParameterRecord:
    parameter_id: str
    name: str
    value: float
    unit: str
    source_type: ParameterSourceType
    provider: str
    locator: str
    reference_head_material: str
    reference_process: str
    target_head_material: str
    target_process: str
    reference_source_id: str = ""
    citation: str = ""
    quality_note: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)
    active: bool = True

    def __post_init__(self) -> None:
        required = (
            self.parameter_id,
            self.name,
            self.unit,
            self.provider,
            self.locator,
            self.reference_head_material,
            self.reference_process,
            self.target_head_material,
            self.target_process,
        )
        if any(not value.strip() for value in required):
            raise ValueError("scoped process parameter requires identity, provenance and route scope")
        if not isfinite(self.value):
            raise ValueError("scoped process parameter value must be finite")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class EnergyQuotaModifierRule:
    rule_id: str
    standard_code: str
    table_number: str
    note_id: str
    description: str
    adjustment_type: str
    adjustment_value: float | None = None
    adjustment_unit: str = ""
    applicability: str = ""
    physical_page: int | None = None


def create_energy_database(
    path: str | Path,
    *,
    database_name: str,
    dataset_version: str,
    source_standard_code: str,
    source_sha256: str,
    source_locator: str,
    quotas: Sequence[EnergyQuotaRecord],
    conversions: Sequence[EnergyConversionRecord] = (),
    process_parameters: Sequence[ScopedProcessParameterRecord] = (),
    modifier_rules: Sequence[EnergyQuotaModifierRule] = (),
    overwrite: bool = False,
) -> EnergyDatabaseAnchor:
    """Create one local SQLite database atomically; generated databases stay outside Git."""

    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        raise FileExistsError(f"energy database already exists: {target}")
    temp = target.with_name(f".{target.name}.building")
    if temp.exists():
        temp.unlink()
    metadata = {
        "database_name": database_name,
        "dataset_version": dataset_version,
        "schema_version": ENERGY_DATABASE_SCHEMA_VERSION,
        "source_standard_code": source_standard_code,
        "source_sha256": source_sha256.lower(),
        "source_locator": source_locator,
        "created_at": datetime.now(UTC).isoformat(),
        "runtime_quota_level": "1",
    }
    with sqlite3.connect(temp) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE energy_quota (
                record_id TEXT PRIMARY KEY,
                product_name TEXT NOT NULL,
                canonical_product TEXT NOT NULL,
                product_group TEXT NOT NULL,
                head_material TEXT NOT NULL,
                production_process TEXT NOT NULL,
                product_form TEXT NOT NULL,
                quota_level INTEGER NOT NULL CHECK (quota_level IN (1, 2, 3)),
                value_kgce_per_t REAL NOT NULL CHECK (value_kgce_per_t > 0),
                standard_code TEXT NOT NULL,
                table_number TEXT NOT NULL,
                physical_page INTEGER NOT NULL,
                printed_page INTEGER,
                applicability TEXT NOT NULL,
                note_ids_json TEXT NOT NULL,
                source_locator TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                active INTEGER NOT NULL CHECK (active IN (0, 1))
            );
            CREATE INDEX energy_quota_route_idx
                ON energy_quota(canonical_product, head_material, production_process, quota_level, active);
            CREATE TABLE energy_conversion (
                conversion_id TEXT PRIMARY KEY,
                parameter_name TEXT NOT NULL,
                energy_carrier TEXT NOT NULL,
                value_min REAL NOT NULL,
                value_max REAL NOT NULL,
                unit TEXT NOT NULL,
                basis TEXT NOT NULL,
                source_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                locator TEXT NOT NULL,
                citation TEXT NOT NULL,
                quality_note TEXT NOT NULL,
                standard_code TEXT NOT NULL,
                physical_page INTEGER,
                metadata_json TEXT NOT NULL,
                active INTEGER NOT NULL CHECK (active IN (0, 1))
            );
            CREATE TABLE process_parameter (
                parameter_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT NOT NULL,
                source_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                locator TEXT NOT NULL,
                reference_head_material TEXT NOT NULL,
                reference_process TEXT NOT NULL,
                target_head_material TEXT NOT NULL,
                target_process TEXT NOT NULL,
                reference_source_id TEXT NOT NULL,
                citation TEXT NOT NULL,
                quality_note TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                active INTEGER NOT NULL CHECK (active IN (0, 1))
            );
            CREATE INDEX process_parameter_scope_idx ON process_parameter(
                reference_head_material, reference_process,
                target_head_material, target_process, reference_source_id, active
            );
            CREATE TABLE quota_modifier_rule (
                rule_id TEXT PRIMARY KEY,
                standard_code TEXT NOT NULL,
                table_number TEXT NOT NULL,
                note_id TEXT NOT NULL,
                description TEXT NOT NULL,
                adjustment_type TEXT NOT NULL,
                adjustment_value REAL,
                adjustment_unit TEXT NOT NULL,
                applicability TEXT NOT NULL,
                physical_page INTEGER
            );
            """
        )
        connection.executemany("INSERT INTO metadata(key, value) VALUES (?, ?)", metadata.items())
        connection.executemany(
            """INSERT INTO energy_quota VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            (
                (
                    item.record_id,
                    item.product_name,
                    _norm(item.canonical_product or (
                        f"{item.production_process} {item.head_material}"
                        if item.production_process else item.product_name
                    )),
                    item.product_group,
                    _norm(item.head_material),
                    _norm(item.production_process),
                    _norm(item.product_form),
                    item.quota_level,
                    item.value_kgce_per_t,
                    item.standard_code,
                    item.table_number,
                    item.physical_page,
                    item.printed_page,
                    item.applicability,
                    json.dumps(item.note_ids, ensure_ascii=False),
                    item.source_locator,
                    item.source_sha256.lower(),
                    int(item.active),
                )
                for item in quotas
            ),
        )
        connection.executemany(
            "INSERT INTO energy_conversion VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    item.conversion_id,
                    item.parameter_name,
                    _norm(item.energy_carrier),
                    item.value_min,
                    item.value_max,
                    item.unit,
                    item.basis,
                    item.source_type.value,
                    item.provider,
                    item.locator,
                    item.citation,
                    item.quality_note,
                    item.standard_code,
                    item.physical_page,
                    json.dumps(dict(item.metadata), ensure_ascii=False, sort_keys=True),
                    int(item.active),
                )
                for item in conversions
            ),
        )
        connection.executemany(
            "INSERT INTO process_parameter VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    item.parameter_id,
                    item.name,
                    item.value,
                    item.unit,
                    item.source_type.value,
                    item.provider,
                    item.locator,
                    _norm(item.reference_head_material),
                    _norm(item.reference_process),
                    _norm(item.target_head_material),
                    _norm(item.target_process),
                    item.reference_source_id,
                    item.citation,
                    item.quality_note,
                    json.dumps(dict(item.metadata), ensure_ascii=False, sort_keys=True),
                    int(item.active),
                )
                for item in process_parameters
            ),
        )
        connection.executemany(
            "INSERT INTO quota_modifier_rule VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    item.rule_id,
                    item.standard_code,
                    item.table_number,
                    item.note_id,
                    item.description,
                    item.adjustment_type,
                    item.adjustment_value,
                    item.adjustment_unit,
                    item.applicability,
                    item.physical_page,
                )
                for item in modifier_rules
            ),
        )
        connection.commit()
    connection.close()
    temp.replace(target)
    return EnergyDatabaseAnchor(database_name, dataset_version, _sha256(target), str(target))


@dataclass(slots=True)
class SqliteEnergyProcessParameterRepository:
    """Read quota/process evidence from SQLite and scope it to one process-variant edge."""

    path: str | Path
    quota_level: int = 1
    expected_database_sha256: str | None = None
    registry: MaterialSemanticRegistryPort = DEFAULT_MATERIAL_REGISTRY

    def __post_init__(self) -> None:
        self.path = Path(self.path).resolve()
        if self.quota_level not in {1, 2, 3}:
            raise ValueError("quota_level must be 1, 2 or 3")

    def _connect(self) -> sqlite3.Connection:
        if not self.path.is_file():
            raise FileNotFoundError(f"energy database not found: {self.path}")
        connection = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def _metadata(self, connection: sqlite3.Connection) -> dict[str, str]:
        metadata = {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM metadata")}
        if metadata.get("schema_version") != ENERGY_DATABASE_SCHEMA_VERSION:
            raise ValueError("unsupported energy database schema version")
        observed = _sha256(self.path)
        expected = (self.expected_database_sha256 or "").strip().lower()
        if expected and observed != expected:
            raise ValueError("energy database SHA-256 does not match the expected version anchor")
        metadata["database_sha256"] = observed
        metadata["database_locator"] = str(self.path)
        return metadata

    @staticmethod
    def _identity(resolution: object, fallback_name: str, fallback_process: str | None) -> tuple[str, str]:
        identity = resolution.identity
        return (
            _norm(identity.head_material or fallback_name),
            _norm((identity.manufacturing_route or (fallback_process or "",))[0]),
        )

    def _quota(
        self,
        connection: sqlite3.Connection,
        head_material: str,
        process: str,
        product_keys: Sequence[str],
    ) -> sqlite3.Row | None:
        keys = tuple(dict.fromkeys(_norm(value) for value in product_keys if _norm(value)))
        if keys:
            placeholders = ",".join("?" for _ in keys)
            exact = tuple(connection.execute(
                f"""SELECT * FROM energy_quota
                    WHERE canonical_product IN ({placeholders})
                      AND quota_level = ? AND active = 1
                    ORDER BY record_id""",
                (*keys, self.quota_level),
            ))
            if len(exact) > 1:
                raise ValueError(
                    f"ambiguous Level-{self.quota_level} exact energy quota for {keys}"
                )
            if exact:
                return exact[0]
        rows = tuple(connection.execute(
            """SELECT * FROM energy_quota
               WHERE head_material = ? AND production_process = ?
                 AND quota_level = ? AND active = 1
               ORDER BY record_id""",
            (_norm(head_material), _norm(process), self.quota_level),
        ))
        if len(rows) > 1:
            raise ValueError(f"ambiguous Level-{self.quota_level} energy quota for {head_material}/{process}")
        return rows[0] if rows else None

    @staticmethod
    def _database_metadata(metadata: Mapping[str, str]) -> dict[str, str]:
        return {
            "evidence_database_name": metadata["database_name"],
            "evidence_database_version": metadata["dataset_version"],
            "evidence_database_sha256": metadata["database_sha256"],
            "evidence_database_locator": metadata["database_locator"],
            "evidence_database_schema_version": metadata["schema_version"],
        }

    @staticmethod
    def _scope_suffix(common_scope: Mapping[str, str]) -> str:
        return hashlib.sha1(
            common_scope["reference_source_id"].encode("utf-8")
        ).hexdigest()[:12]

    async def search(
        self, activity: NormalizedActivity, reference: SourceRecord
    ) -> Sequence[ParameterEvidence]:
        target_resolution = self.registry.resolve(
            activity.canonical_name,
            product_form=activity.product_form,
            composition=activity.composition,
            production_process=activity.production_process,
        )
        reference_resolution = self.registry.resolve(
            reference.material_name,
            product_form=reference.product_form,
            composition=reference.composition,
            production_process=reference.production_process,
        )
        target_head, target_process = self._identity(
            target_resolution, activity.canonical_name, activity.production_process
        )
        reference_head, reference_process = self._identity(
            reference_resolution, reference.material_name, reference.production_process
        )
        if not target_process or not reference_process or target_head != reference_head:
            return ()

        with self._connect() as connection:
            database = self._metadata(connection)
            reference_quota = self._quota(
                connection,
                reference_head,
                reference_process,
                (reference.material_name, f"{reference_process} {reference_head}"),
            )
            target_quota = self._quota(
                connection,
                target_head,
                target_process,
                (activity.canonical_name, f"{target_process} {target_head}"),
            )
            if reference_quota is None or target_quota is None:
                return ()
            common_scope = {
                "reference_source_id": reference.source_id,
                "reference_head_material": reference_head,
                "reference_process": reference_process,
                "target_material": activity.canonical_name,
                "target_material_id": target_head,
                "target_process": target_process,
                "quota_level": str(self.quota_level),
                "evidence_status": "STANDARD_QUOTA_PROXY",
                **self._database_metadata(database),
            }
            evidence = [
                self._quota_evidence(reference_quota, "reference_total_energy_kgce_per_t", common_scope),
                self._quota_evidence(target_quota, "target_total_energy_kgce_per_t", common_scope),
            ]
            exact_conversions = tuple(connection.execute(
                """SELECT * FROM energy_conversion
                   WHERE active = 1 AND ABS(value_max - value_min) <= 1e-12
                     AND parameter_name IN (
                         'electricity_kgce_per_kwh',
                         'natural_gas_kgce_per_nm3'
                     )
                   ORDER BY conversion_id"""
            ))
            evidence.extend(self._conversion_evidence(row, common_scope) for row in exact_conversions)
            scoped = tuple(connection.execute(
                """SELECT * FROM process_parameter
                   WHERE reference_head_material = ? AND reference_process = ?
                     AND target_head_material = ? AND target_process = ? AND active = 1
                     AND (reference_source_id = '' OR reference_source_id = ?)
                   ORDER BY parameter_id""",
                (reference_head, reference_process, target_head, target_process, reference.source_id),
            ))
            evidence.extend(self._scoped_evidence(row, common_scope) for row in scoped)
            return tuple(evidence)

    @staticmethod
    def _quota_evidence(
        row: sqlite3.Row, name: str, common_scope: Mapping[str, str]
    ) -> ParameterEvidence:
        metadata = {
            **common_scope,
            "energy_quota_record_id": row["record_id"],
            "canonical_product": row["canonical_product"],
            "standard_code": row["standard_code"],
            "table_number": row["table_number"],
            "physical_page": str(row["physical_page"]),
            "printed_page": str(row["printed_page"] or ""),
            "source_pdf_sha256": row["source_sha256"],
            "applicability": row["applicability"],
            "note_ids": row["note_ids_json"],
        }
        return ParameterEvidence(
            parameter_id=(
                f"energy-quota:{row['record_id']}:"
                f"scope:{SqliteEnergyProcessParameterRepository._scope_suffix(common_scope)}"
            ),
            name=name,
            value=row["value_kgce_per_t"],
            unit="kgce/t",
            source_type=ParameterSourceType.FORMAL_STANDARD,
            provider="河南省耐火材料行业协会",
            locator=row["source_locator"],
            citation=(
                f"{row['standard_code']} 表{row['table_number']}，"
                f"{row['product_name']}，{row['quota_level']}级"
            ),
            quality_note=(
                f"Level-{row['quota_level']} standard quota proxy; "
                "upper-limit benchmark, not measured plant energy."
            ),
            metadata=metadata,
        )

    @staticmethod
    def _conversion_evidence(
        row: sqlite3.Row, common_scope: Mapping[str, str]
    ) -> ParameterEvidence:
        metadata = {
            **json.loads(row["metadata_json"]),
            **common_scope,
            "energy_conversion_id": row["conversion_id"],
            "standard_code": row["standard_code"],
            "physical_page": str(row["physical_page"] or ""),
            "conversion_basis": row["basis"],
        }
        return ParameterEvidence(
            parameter_id=(
                f"energy-conversion:{row['conversion_id']}:"
                f"scope:{SqliteEnergyProcessParameterRepository._scope_suffix(common_scope)}"
            ),
            name=row["parameter_name"],
            value=row["value_min"],
            unit=row["unit"],
            source_type=ParameterSourceType(row["source_type"]),
            provider=row["provider"],
            locator=row["locator"],
            citation=row["citation"],
            quality_note=row["quality_note"],
            metadata=metadata,
        )

    @staticmethod
    def _scoped_evidence(
        row: sqlite3.Row, common_scope: Mapping[str, str]
    ) -> ParameterEvidence:
        metadata = {**json.loads(row["metadata_json"]), **common_scope}
        return ParameterEvidence(
            parameter_id=(
                f"{row['parameter_id']}:"
                f"scope:{SqliteEnergyProcessParameterRepository._scope_suffix(common_scope)}"
            ),
            name=row["name"],
            value=row["value"],
            unit=row["unit"],
            source_type=ParameterSourceType(row["source_type"]),
            provider=row["provider"],
            locator=row["locator"],
            citation=row["citation"],
            quality_note=row["quality_note"],
            metadata=metadata,
        )


@dataclass(slots=True)
class CompositeProcessParameterRepository:
    repositories: Sequence[ProcessParameterRepositoryPort]

    async def search(
        self, activity: NormalizedActivity, reference: SourceRecord
    ) -> Sequence[ParameterEvidence]:
        output: list[ParameterEvidence] = []
        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        for repository in self.repositories:
            for item in await repository.search(activity, reference):
                if item.parameter_id in seen_ids:
                    continue
                if item.name in seen_names:
                    raise ValueError(f"conflicting process parameter from composite repositories: {item.name}")
                seen_ids.add(item.parameter_id)
                seen_names.add(item.name)
                output.append(item)
        return tuple(output)
