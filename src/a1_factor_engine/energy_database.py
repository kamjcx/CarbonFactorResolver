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

ENERGY_DATABASE_SCHEMA_VERSION = "5"
DATABASE_PRIORITY_POLICY_ID = "process.database-priority-energy-replacement/v1"
GENERIC_ENERGY_PARAMETER_NAMES = frozenset({
    "natural_gas_kgce_per_nm3",
    "electricity_ef_kgco2e_per_kwh",
    "natural_gas_ef_kgco2e_per_nm3",
})


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
class EnterpriseEnergyProfileRecord:
    """One workbook product and quota-level energy/allocation observation."""

    profile_id: str
    sequence_id: str
    product_name: str
    product_group: str
    head_material: str
    production_process: str
    quota_level: int
    total_energy_kgce_per_t: float
    electricity_share: float
    remainder_carrier: str
    remainder_share: float
    source_type: ParameterSourceType
    provider: str
    locator: str
    worksheet_name: str
    worksheet_row: int
    energy_cell: str
    electricity_share_cell: str
    formula_cell: str
    canonical_product: str = ""
    product_form: str = ""
    citation: str = ""
    quality_note: str = ""
    allocation_status: str = ""
    source_sha256: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)
    runtime_eligible: bool = True
    active: bool = True

    def __post_init__(self) -> None:
        required = (
            self.profile_id,
            self.sequence_id,
            self.product_name,
            self.head_material,
            self.provider,
            self.locator,
            self.worksheet_name,
            self.energy_cell,
            self.electricity_share_cell,
        )
        if any(not value.strip() for value in required):
            raise ValueError("enterprise energy profile requires identity, scope and provenance")
        if self.quota_level not in {1, 2, 3}:
            raise ValueError("enterprise energy profile level must be 1, 2 or 3")
        if self.worksheet_row < 1:
            raise ValueError("enterprise energy profile worksheet row must be positive")
        if not isfinite(self.total_energy_kgce_per_t) or self.total_energy_kgce_per_t <= 0:
            raise ValueError("enterprise total energy must be finite and positive")
        if not isfinite(self.electricity_share) or not 0 <= self.electricity_share <= 1:
            raise ValueError("enterprise electricity share must be between zero and one")
        if not isfinite(self.remainder_share) or not 0 <= self.remainder_share <= 1:
            raise ValueError("enterprise remainder share must be between zero and one")
        if abs(self.electricity_share + self.remainder_share - 1.0) > 1e-6:
            raise ValueError("enterprise energy shares must close to one")
        if self.remainder_share > 0 and not self.remainder_carrier.strip():
            raise ValueError("nonzero enterprise remainder share requires a carrier")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class EnterpriseProcessEmissionRecord:
    """One level-specific non-energy process-emission observation from the workbook."""

    emission_id: str
    sequence_id: str
    product_name: str
    head_material: str
    production_process: str
    quota_level: int
    emission_name: str
    value_kgco2e_per_t: float
    source_type: ParameterSourceType
    provider: str
    locator: str
    worksheet_name: str
    worksheet_row: int
    emission_cell: str
    formula: str
    canonical_product: str = ""
    citation: str = ""
    quality_note: str = ""
    source_sha256: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)
    runtime_eligible: bool = True
    active: bool = True

    def __post_init__(self) -> None:
        required = (
            self.emission_id,
            self.sequence_id,
            self.product_name,
            self.head_material,
            self.production_process,
            self.emission_name,
            self.provider,
            self.locator,
            self.worksheet_name,
            self.emission_cell,
        )
        if any(not value.strip() for value in required):
            raise ValueError("enterprise process emission requires identity, scope and provenance")
        if self.quota_level not in {1, 2, 3}:
            raise ValueError("enterprise process-emission level must be 1, 2 or 3")
        if self.worksheet_row < 1:
            raise ValueError("enterprise process-emission worksheet row must be positive")
        if not isfinite(self.value_kgco2e_per_t) or self.value_kgco2e_per_t < 0:
            raise ValueError("enterprise process emission must be finite and non-negative")
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
    enterprise_profiles: Sequence[EnterpriseEnergyProfileRecord] = (),
    enterprise_process_emissions: Sequence[EnterpriseProcessEmissionRecord] = (),
    modifier_rules: Sequence[EnergyQuotaModifierRule] = (),
    additional_metadata: Mapping[str, str] = MappingProxyType({}),
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
    metadata.update({str(key): str(value) for key, value in additional_metadata.items()})
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
            CREATE TABLE enterprise_energy_profile (
                profile_id TEXT PRIMARY KEY,
                sequence_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                canonical_product TEXT NOT NULL,
                product_group TEXT NOT NULL,
                head_material TEXT NOT NULL,
                production_process TEXT NOT NULL,
                product_form TEXT NOT NULL,
                quota_level INTEGER NOT NULL CHECK (quota_level IN (1, 2, 3)),
                total_energy_kgce_per_t REAL NOT NULL CHECK (total_energy_kgce_per_t > 0),
                electricity_share REAL NOT NULL CHECK (electricity_share BETWEEN 0 AND 1),
                remainder_carrier TEXT NOT NULL,
                remainder_share REAL NOT NULL CHECK (remainder_share BETWEEN 0 AND 1),
                source_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                locator TEXT NOT NULL,
                citation TEXT NOT NULL,
                quality_note TEXT NOT NULL,
                allocation_status TEXT NOT NULL,
                worksheet_name TEXT NOT NULL,
                worksheet_row INTEGER NOT NULL,
                energy_cell TEXT NOT NULL,
                electricity_share_cell TEXT NOT NULL,
                formula_cell TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                runtime_eligible INTEGER NOT NULL CHECK (runtime_eligible IN (0, 1)),
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                CHECK (ABS(electricity_share + remainder_share - 1.0) <= 0.000001)
            );
            CREATE INDEX enterprise_energy_profile_product_idx ON enterprise_energy_profile(
                canonical_product, quota_level, runtime_eligible, active
            );
            CREATE TABLE enterprise_process_emission (
                emission_id TEXT PRIMARY KEY,
                sequence_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                canonical_product TEXT NOT NULL,
                head_material TEXT NOT NULL,
                production_process TEXT NOT NULL,
                quota_level INTEGER NOT NULL CHECK (quota_level IN (1, 2, 3)),
                emission_name TEXT NOT NULL,
                value_kgco2e_per_t REAL NOT NULL CHECK (value_kgco2e_per_t >= 0),
                source_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                locator TEXT NOT NULL,
                citation TEXT NOT NULL,
                quality_note TEXT NOT NULL,
                worksheet_name TEXT NOT NULL,
                worksheet_row INTEGER NOT NULL,
                emission_cell TEXT NOT NULL,
                formula TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                runtime_eligible INTEGER NOT NULL CHECK (runtime_eligible IN (0, 1)),
                active INTEGER NOT NULL CHECK (active IN (0, 1))
            );
            CREATE INDEX enterprise_process_emission_product_idx
                ON enterprise_process_emission(
                    canonical_product, quota_level, emission_name, runtime_eligible, active
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
            """INSERT INTO enterprise_energy_profile VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            (
                (
                    item.profile_id,
                    item.sequence_id,
                    item.product_name,
                    _norm(item.canonical_product or item.product_name),
                    item.product_group,
                    _norm(item.head_material),
                    _norm(item.production_process),
                    _norm(item.product_form),
                    item.quota_level,
                    item.total_energy_kgce_per_t,
                    item.electricity_share,
                    _norm(item.remainder_carrier),
                    item.remainder_share,
                    item.source_type.value,
                    item.provider,
                    item.locator,
                    item.citation,
                    item.quality_note,
                    item.allocation_status,
                    item.worksheet_name,
                    item.worksheet_row,
                    item.energy_cell,
                    item.electricity_share_cell,
                    item.formula_cell,
                    item.source_sha256.lower(),
                    json.dumps(dict(item.metadata), ensure_ascii=False, sort_keys=True),
                    int(item.runtime_eligible),
                    int(item.active),
                )
                for item in enterprise_profiles
            ),
        )
        connection.executemany(
            """INSERT INTO enterprise_process_emission VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            (
                (
                    item.emission_id,
                    item.sequence_id,
                    item.product_name,
                    _norm(item.canonical_product or item.product_name),
                    _norm(item.head_material),
                    _norm(item.production_process),
                    item.quota_level,
                    item.emission_name,
                    item.value_kgco2e_per_t,
                    item.source_type.value,
                    item.provider,
                    item.locator,
                    item.citation,
                    item.quality_note,
                    item.worksheet_name,
                    item.worksheet_row,
                    item.emission_cell,
                    item.formula,
                    item.source_sha256.lower(),
                    json.dumps(dict(item.metadata), ensure_ascii=False, sort_keys=True),
                    int(item.runtime_eligible),
                    int(item.active),
                )
                for item in enterprise_process_emissions
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
    allow_review_profiles: bool = True
    allow_generic_energy_parameters: bool = True
    assume_lifecycle_process_inclusion: bool = True

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

    def _enterprise_profile(
        self,
        connection: sqlite3.Connection,
        product_keys: Sequence[str],
    ) -> sqlite3.Row | None:
        keys = tuple(dict.fromkeys(_norm(value) for value in product_keys if _norm(value)))
        if not keys:
            return None
        placeholders = ",".join("?" for _ in keys)
        eligibility_clause = "" if self.allow_review_profiles else "AND runtime_eligible = 1"
        rows = tuple(connection.execute(
            f"""SELECT * FROM enterprise_energy_profile
                WHERE canonical_product IN ({placeholders})
                  AND quota_level = ? AND active = 1
                  AND allocation_status NOT LIKE '%AMBIGUOUS_DUPLICATE%'
                  {eligibility_clause}
                ORDER BY profile_id""",
            (*keys, self.quota_level),
        ))
        if len(rows) > 1:
            raise ValueError(
                f"ambiguous Level-{self.quota_level} enterprise energy profile for {keys}"
            )
        return rows[0] if rows else None

    def _enterprise_process_emissions(
        self,
        connection: sqlite3.Connection,
        product_keys: Sequence[str],
    ) -> tuple[sqlite3.Row, ...]:
        keys = tuple(dict.fromkeys(_norm(value) for value in product_keys if _norm(value)))
        if not keys:
            return ()
        placeholders = ",".join("?" for _ in keys)
        eligibility_clause = "" if self.allow_review_profiles else "AND runtime_eligible = 1"
        rows = tuple(connection.execute(
            f"""SELECT * FROM enterprise_process_emission
                WHERE canonical_product IN ({placeholders})
                  AND quota_level = ? AND active = 1
                  {eligibility_clause}
                ORDER BY emission_name, emission_id""",
            (*keys, self.quota_level),
        ))
        canonical_products = {row["canonical_product"] for row in rows}
        if len(canonical_products) > 1:
            raise ValueError(
                f"ambiguous Level-{self.quota_level} enterprise process emission for {keys}"
            )
        return rows

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
            reference_profile = self._enterprise_profile(
                connection,
                (reference.material_name, f"{reference_process} {reference_head}"),
            )
            target_profile = self._enterprise_profile(
                connection,
                (activity.canonical_name, f"{target_process} {target_head}"),
            )
            reference_process_emissions = self._enterprise_process_emissions(
                connection,
                (reference.material_name, f"{reference_process} {reference_head}"),
            )
            target_process_emissions = self._enterprise_process_emissions(
                connection,
                (activity.canonical_name, f"{target_process} {target_head}"),
            )
            if (
                reference_quota is None and reference_profile is None
            ) or (
                target_quota is None and target_profile is None
            ):
                return ()
            common_scope = {
                "reference_source_id": reference.source_id,
                "reference_head_material": reference_head,
                "reference_process": reference_process,
                "target_material": activity.canonical_name,
                "target_material_id": target_head,
                "target_process": target_process,
                "quota_level": str(self.quota_level),
                "evidence_status": "DATABASE_PRIORITY_ENERGY_REPLACEMENT",
                "energy_selection_policy_id": DATABASE_PRIORITY_POLICY_ID,
                **self._database_metadata(database),
            }
            evidence = [
                (
                    self._profile_evidence(
                        reference_profile,
                        "reference_total_energy_kgce_per_t",
                        reference_profile["total_energy_kgce_per_t"],
                        "kgce/t",
                        common_scope,
                    )
                    if reference_profile is not None
                    else self._quota_evidence(
                        reference_quota, "reference_total_energy_kgce_per_t", common_scope
                    )
                ),
                (
                    self._profile_evidence(
                        target_profile,
                        "target_total_energy_kgce_per_t",
                        target_profile["total_energy_kgce_per_t"],
                        "kgce/t",
                        common_scope,
                    )
                    if target_profile is not None
                    else self._quota_evidence(
                        target_quota, "target_total_energy_kgce_per_t", common_scope
                    )
                ),
            ]
            if (
                reference_profile is not None
                and target_profile is not None
                and reference_profile["remainder_carrier"] in {"natural_gas", "none"}
                and target_profile["remainder_carrier"] in {"natural_gas", "none"}
            ):
                for prefix, profile in (
                    ("reference", reference_profile),
                    ("target", target_profile),
                ):
                    evidence.extend((
                        self._profile_evidence(
                            profile,
                            f"{prefix}_electricity_share",
                            profile["electricity_share"],
                            "fraction",
                            common_scope,
                        ),
                        self._profile_evidence(
                            profile,
                            f"{prefix}_natural_gas_share",
                            profile["remainder_share"],
                            "fraction",
                            common_scope,
                        ),
                    ))
            if any(
                row["value_kgco2e_per_t"] > 0
                for row in (*reference_process_emissions, *target_process_emissions)
            ):
                if reference_process_emissions:
                    evidence.append(self._process_emission_evidence(
                        reference_process_emissions,
                        "reference_additional_process_emission_kgco2e_per_kg",
                        common_scope,
                    ))
                if target_process_emissions:
                    evidence.append(self._process_emission_evidence(
                        target_process_emissions,
                        "target_additional_process_emission_kgco2e_per_kg",
                        common_scope,
                    ))
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
            if self.allow_generic_energy_parameters:
                generic = tuple(connection.execute(
                    """SELECT * FROM process_parameter
                       WHERE active = 1 AND name IN (?, ?, ?)
                       ORDER BY name, parameter_id""",
                    tuple(sorted(GENERIC_ENERGY_PARAMETER_NAMES)),
                ))
                grouped: dict[str, list[sqlite3.Row]] = {}
                for row in generic:
                    grouped.setdefault(row["name"], []).append(row)
                for name, rows in grouped.items():
                    distinct = {(row["value"], _norm(row["unit"])) for row in rows}
                    if len(distinct) == 1:
                        evidence.append(self._generic_energy_evidence(
                            rows[0], common_scope, tuple(row["parameter_id"] for row in rows)
                        ))
            scoped = tuple(connection.execute(
                """SELECT * FROM process_parameter
                   WHERE reference_head_material = ? AND reference_process = ?
                     AND target_head_material = ? AND target_process = ? AND active = 1
                     AND (reference_source_id = '' OR reference_source_id = ?)
                   ORDER BY parameter_id""",
                (reference_head, reference_process, target_head, target_process, reference.source_id),
            ))
            evidence.extend(self._scoped_evidence(row, common_scope) for row in scoped)
            inclusion_witness = next((
                row for row in scoped
                if str(json.loads(row["metadata_json"]).get(
                    "reference_includes_process", ""
                )).lower() == "true"
            ), None)
            if inclusion_witness is not None:
                evidence.append(self._process_inclusion_evidence(
                    inclusion_witness, common_scope
                ))
            elif (
                self.assume_lifecycle_process_inclusion
                and reference_profile is not None
                and target_profile is not None
                and reference.factor_kind.value == "lifecycle_factor"
                and not any(
                    marker in _norm(reference.material_name)
                    for marker in ("代理", "proxy")
                )
            ):
                evidence.append(self._policy_inclusion_evidence(common_scope))
            # A current exact enterprise profile supersedes older share/total
            # parameters with the same name. Edge-scoped evidence still supplies
            # conversion factors, emission factors and process-inclusion proof.
            by_name: dict[str, ParameterEvidence] = {}
            for item in evidence:
                existing = by_name.get(item.name)
                if (
                    existing is not None
                    and existing.parameter_id.startswith((
                        "enterprise-energy:",
                        "enterprise-process-emission:",
                    ))
                ):
                    continue
                by_name[item.name] = item
            return tuple(by_name.values())

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
    def _profile_evidence(
        row: sqlite3.Row,
        name: str,
        value: float,
        unit: str,
        common_scope: Mapping[str, str],
    ) -> ParameterEvidence:
        metadata = {
            **json.loads(row["metadata_json"]),
            **common_scope,
            "enterprise_energy_profile_id": row["profile_id"],
            "sequence_id": row["sequence_id"],
            "canonical_product": row["canonical_product"],
            "quota_level": str(row["quota_level"]),
            "allocation_status": row["allocation_status"],
            "remainder_carrier": row["remainder_carrier"],
            "worksheet_name": row["worksheet_name"],
            "worksheet_row": str(row["worksheet_row"]),
            "energy_cell": row["energy_cell"],
            "electricity_share_cell": row["electricity_share_cell"],
            "formula_cell": row["formula_cell"],
            "source_workbook_sha256": row["source_sha256"],
            "runtime_eligible": str(bool(row["runtime_eligible"])).lower(),
            "energy_selection_policy_id": DATABASE_PRIORITY_POLICY_ID,
            "calculation_with_assumption": str(not bool(row["runtime_eligible"])).lower(),
            "selection_priority": "exact_enterprise_profile",
        }
        return ParameterEvidence(
            parameter_id=(
                f"enterprise-energy:{row['profile_id']}:{name}:"
                f"scope:{SqliteEnergyProcessParameterRepository._scope_suffix(common_scope)}"
            ),
            name=name,
            value=value,
            unit=unit,
            source_type=ParameterSourceType(row["source_type"]),
            provider=row["provider"],
            locator=row["locator"],
            citation=row["citation"],
            quality_note=row["quality_note"],
            metadata=metadata,
        )

    @staticmethod
    def _process_emission_evidence(
        rows: Sequence[sqlite3.Row],
        name: str,
        common_scope: Mapping[str, str],
    ) -> ParameterEvidence:
        first = rows[0]
        emission_ids = tuple(row["emission_id"] for row in rows)
        raw_value = sum(row["value_kgco2e_per_t"] for row in rows)
        runtime_eligible = all(bool(row["runtime_eligible"]) for row in rows)
        metadata = {
            **common_scope,
            "enterprise_process_emission_ids": json.dumps(emission_ids, ensure_ascii=False),
            "sequence_id": first["sequence_id"],
            "canonical_product": first["canonical_product"],
            "quota_level": str(first["quota_level"]),
            "emission_names": json.dumps(
                tuple(row["emission_name"] for row in rows), ensure_ascii=False
            ),
            "raw_value_kgco2e_per_t": f"{raw_value:g}",
            "worksheet_name": first["worksheet_name"],
            "worksheet_row": str(first["worksheet_row"]),
            "emission_cells": json.dumps(
                tuple(row["emission_cell"] for row in rows), ensure_ascii=False
            ),
            "formulas": json.dumps(tuple(row["formula"] for row in rows), ensure_ascii=False),
            "source_workbook_sha256": first["source_sha256"],
            "runtime_eligible": str(runtime_eligible).lower(),
            "calculation_with_assumption": str(not runtime_eligible).lower(),
            "selection_priority": "exact_enterprise_process_emission",
            "energy_selection_policy_id": DATABASE_PRIORITY_POLICY_ID,
        }
        for row in rows:
            metadata.update({
                f"record_metadata:{row['emission_id']}": row["metadata_json"],
            })
        return ParameterEvidence(
            parameter_id=(
                f"enterprise-process-emission:{'+'.join(emission_ids)}:{name}:"
                f"scope:{SqliteEnergyProcessParameterRepository._scope_suffix(common_scope)}"
            ),
            name=name,
            value=raw_value / 1000.0,
            unit="kgCO2e/kg",
            source_type=ParameterSourceType(first["source_type"]),
            provider=first["provider"],
            locator=first["locator"],
            citation=" | ".join(row["citation"] for row in rows),
            quality_note=" | ".join(row["quality_note"] for row in rows),
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

    @staticmethod
    def _generic_energy_evidence(
        row: sqlite3.Row,
        common_scope: Mapping[str, str],
        origin_parameter_ids: tuple[str, ...],
    ) -> ParameterEvidence:
        metadata = {
            **json.loads(row["metadata_json"]),
            **common_scope,
            "energy_selection_policy_id": DATABASE_PRIORITY_POLICY_ID,
            "parameter_scope": "unique_generic_energy_carrier_fallback",
            "generic_origin_parameter_ids": json.dumps(origin_parameter_ids),
            "calculation_with_assumption": "true",
        }
        return ParameterEvidence(
            parameter_id=(
                f"generic-energy:{row['parameter_id']}:"
                f"scope:{SqliteEnergyProcessParameterRepository._scope_suffix(common_scope)}"
            ),
            name=row["name"],
            value=row["value"],
            unit=row["unit"],
            source_type=ParameterSourceType(row["source_type"]),
            provider=row["provider"],
            locator=row["locator"],
            citation=row["citation"],
            quality_note=(
                f"{row['quality_note']} | reused as the unique database carrier parameter "
                f"under {DATABASE_PRIORITY_POLICY_ID}"
            ),
            metadata=metadata,
        )

    @staticmethod
    def _policy_inclusion_evidence(
        common_scope: Mapping[str, str],
    ) -> ParameterEvidence:
        return ParameterEvidence(
            parameter_id=(
                f"policy:{DATABASE_PRIORITY_POLICY_ID}:reference-process-inclusion:"
                f"scope:{SqliteEnergyProcessParameterRepository._scope_suffix(common_scope)}"
            ),
            name="reference_process_inclusion",
            value=1.0,
            unit="boolean",
            source_type=ParameterSourceType.USER_CONFIRMED_ENGINEERING_DATA,
            provider="OFR deterministic policy",
            locator=f"policy:{DATABASE_PRIORITY_POLICY_ID}",
            citation="User-approved database-priority route-energy replacement policy",
            quality_note=(
                "Policy assumption: the lifecycle reference includes the route energy "
                "removed by the deterministic replacement formula."
            ),
            metadata={
                **common_scope,
                "reference_includes_process": "true",
                "process_inclusion_basis": "policy_assumption",
                "energy_selection_policy_id": DATABASE_PRIORITY_POLICY_ID,
                "calculation_with_assumption": "true",
            },
        )

    @staticmethod
    def _process_inclusion_evidence(
        row: sqlite3.Row, common_scope: Mapping[str, str]
    ) -> ParameterEvidence:
        """Preserve a scoped inclusion assertion independently of numeric values.

        Enterprise profiles may supersede an older scoped share, but the scoped
        source can still be the reviewed proof that the reference factor includes
        the process being removed. Keeping this as a non-numeric witness prevents
        provenance loss without allowing the older share to affect calculations.
        """
        metadata = {**json.loads(row["metadata_json"]), **common_scope}
        return ParameterEvidence(
            parameter_id=(
                f"{row['parameter_id']}:reference-process-inclusion:"
                f"scope:{SqliteEnergyProcessParameterRepository._scope_suffix(common_scope)}"
            ),
            name="reference_process_inclusion",
            value=1.0,
            unit="boolean",
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
