"""Import reviewed T/CHNRISC energy-quota tables into a local SQLite database.

The PDF and generated database are intentionally ignored by Git. This importer
contains parsing logic and provenance checks, not a bundled copy of the source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError as exc:  # pragma: no cover - operator environment guard
    raise SystemExit("pdfplumber is required to import the standard PDF") from exc

from a1_factor_engine import (
    EnergyConversionRecord,
    EnergyQuotaModifierRule,
    EnergyQuotaRecord,
    ParameterSourceType,
    ScopedProcessParameterRecord,
    create_energy_database,
)
from a1_factor_engine.material_registry import DEFAULT_MATERIAL_REGISTRY

STANDARD_CODE = "T/CHNRISC 0008-2025"
PUBLISHER = "河南省耐火材料行业协会"
WATERMARK_PARTS = frozenset("平台信息标准团体全国")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_cell(value: object) -> str:
    lines = [line.strip() for line in str(value or "").replace("\r", "\n").split("\n")]
    return " ".join(line for line in lines if line and line not in WATERMARK_PARTS).strip()


def numeric(value: object) -> float | None:
    observed = clean_cell(value).replace(" ", "")
    return float(observed) if re.fullmatch(r"\d+(?:\.\d+)?", observed) else None


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized or hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def canonical_product_key(product_name: str) -> str:
    return {
        "电熔莫来石": "electrofused mullite",
        "烧结莫来石": "sintered mullite",
        "烧结矾土基莫来石": "sintered bauxite-based mullite",
        "电熔锆莫来石": "electrofused zircon mullite",
        "电熔镁铝尖晶石": "electrofused spinel",
        "烧结镁铝尖晶石": "sintered spinel",
    }.get(product_name, product_name)


def extract_quotas(pdf: pdfplumber.PDF, source_sha: str) -> list[EnergyQuotaRecord]:
    specs = (
        (5, 0, "1"),
        (6, 0, "1"),
        (6, 1, "2"),
        (7, 0, "2"),
        (8, 1, "3"),
    )
    output: list[EnergyQuotaRecord] = []
    contexts: dict[str, list[str]] = {}
    row_numbers: dict[str, int] = {"1": 0, "2": 0, "3": 0}
    for page_index, table_index, table_number in specs:
        tables = pdf.pages[page_index].extract_tables()
        if table_index >= len(tables):
            raise ValueError(f"table {table_number} not found on physical page {page_index + 1}")
        context = contexts.setdefault(table_number, [])
        for raw in tables[table_index]:
            if len(raw) < 4:
                continue
            levels = tuple(numeric(value) for value in raw[-3:])
            labels = [clean_cell(value) for value in raw[:-3]]
            if any("注：" in label for label in labels) or levels == (None, None, None):
                continue
            if any(value is None for value in levels):
                continue
            while len(context) < len(labels):
                context.append("")
            for index, label in enumerate(labels):
                if label:
                    context[index] = label
                    for deeper in range(index + 1, len(context)):
                        context[deeper] = ""
            path = [value for value in context if value]
            if not path:
                raise ValueError(f"quota row has no product label on physical page {page_index + 1}")
            row_numbers[table_number] += 1
            row_number = row_numbers[table_number]
            product_name = path[-1]
            product_path = " / ".join(path)
            resolved = DEFAULT_MATERIAL_REGISTRY.resolve(product_path)
            identity = resolved.identity
            head_material = identity.head_material or product_name
            process = identity.manufacturing_route[0] if identity.manufacturing_route else ""
            locator = f"standard:{STANDARD_CODE.replace(' ', '-')}#table-{table_number}"
            for level, value in enumerate(levels, 1):
                output.append(EnergyQuotaRecord(
                    record_id=(
                        f"t-chnrisc-0008-2025:t{table_number}:"
                        f"r{row_number:03d}:{_slug(product_name)}:l{level}"
                    ),
                    product_name=product_name,
                    product_group=path[0] if len(path) > 1 else "",
                    head_material=head_material,
                    production_process=process,
                    product_form=identity.product_form or "",
                    quota_level=level,
                    value_kgce_per_t=value,
                    standard_code=STANDARD_CODE,
                    table_number=table_number,
                    physical_page=page_index + 1,
                    printed_page=page_index - 3,
                    canonical_product=canonical_product_key(product_name),
                    applicability=product_path,
                    source_locator=locator,
                    source_sha256=source_sha,
                ))
    return output


def _coefficient_values(value: str) -> tuple[float, float] | None:
    compact = re.sub(r"(?<=\d)\s+(?=\d)", "", clean_cell(value))
    observed = [float(item) for item in re.findall(r"(\d+(?:\.\d+)?)\s*kgce", compact)]
    if not observed:
        return None
    return min(observed), max(observed)


def _coefficient_unit(value: str) -> str:
    observed = clean_cell(value).casefold().replace(" ", "")
    if "kw" in observed:
        return "kgce/kWh"
    if "/m3" in observed or "/m³" in observed:
        return "kgce/m3"
    if "/kg" in observed:
        return "kgce/kg"
    if "/mj" in observed:
        return "kgce/MJ"
    if "/t" in observed:
        return "kgce/t"
    raise ValueError(f"unsupported standard-coal conversion unit: {value}")


def extract_conversions(pdf: pdfplumber.PDF) -> list[EnergyConversionRecord]:
    output: list[EnergyConversionRecord] = []
    for page_index, table_number in ((11, "A.1"), (12, "B.1")):
        for table in pdf.pages[page_index].extract_tables():
            for raw in table:
                if len(raw) < 3:
                    continue
                name_parts = [clean_cell(item) for item in raw[:-2] if clean_cell(item)]
                coefficient = clean_cell(raw[-1])
                values = _coefficient_values(coefficient)
                if not name_parts or values is None:
                    continue
                carrier = name_parts[-1]
                if carrier in {"能源名称", "品 种"}:
                    continue
                parameter_name = {
                    "电力（当量值）": "electricity_kgce_per_kwh",
                    "天然气": "natural_gas_kgce_per_nm3",
                }.get(carrier, f"standard_coal_conversion_{_slug(carrier)}")
                source_locator = f"standard:{STANDARD_CODE.replace(' ', '-')}#table-{table_number}"
                output.append(EnergyConversionRecord(
                    conversion_id=f"t-chnrisc-0008-2025:{table_number}:{_slug(carrier)}",
                    parameter_name=parameter_name,
                    energy_carrier=carrier,
                    value_min=values[0],
                    value_max=values[1],
                    unit=_coefficient_unit(coefficient),
                    basis="equivalent_value" if "当量值" in carrier else "reference_standard_coal_coefficient",
                    source_type=ParameterSourceType.FORMAL_STANDARD,
                    provider=PUBLISHER,
                    locator=source_locator,
                    citation=f"{STANDARD_CODE} 表{table_number}，{carrier}",
                    quality_note=(
                        "exact published coefficient" if values[0] == values[1]
                        else "published range; runtime derivation requires an independently selected exact value"
                    ),
                    standard_code=STANDARD_CODE,
                    physical_page=page_index + 1,
                    metadata={"raw_coefficient": coefficient},
                ))
    return output


def extract_modifier_rules(pdf: pdfplumber.PDF) -> list[EnergyQuotaModifierRule]:
    output: list[EnergyQuotaModifierRule] = []
    sources = ((6, 0, "1"), (8, 0, "2"), (8, 1, "3"))
    for page_index, table_index, table_number in sources:
        tables = pdf.pages[page_index].extract_tables()
        note_cells = [
            str(cell)
            for row in tables[table_index]
            for cell in row
            if cell and "注：" in str(cell)
        ]
        note_block = note_cells[0].split("注：", 1)[1] if note_cells else ""
        parsed: list[tuple[str, str]] = []
        current_id = ""
        current_lines: list[str] = []
        last_number = 0
        for line in note_block.splitlines():
            observed = line.strip()
            match = re.match(r"^(\d+)\s*(.*)$", observed)
            number = int(match.group(1)) if match else 0
            description = match.group(2).strip() if match else ""
            starts_note = bool(
                match and 1 <= number <= 9 and number == last_number + 1
                and any(not char.isdigit() for char in description)
            )
            if starts_note:
                if current_id:
                    parsed.append((current_id, " ".join(current_lines)))
                current_id = str(number)
                current_lines = [description]
                last_number = number
            elif current_id and observed:
                current_lines.append(observed)
        if current_id:
            parsed.append((current_id, " ".join(current_lines)))
        for note_id, description in parsed:
            cleaned = " ".join(description.split())
            if table_number == "3" and note_id == "4":
                cleaned = cleaned.removesuffix(" 2 3").replace("Al0 含量", "Al2O3 含量")
            if not cleaned:
                continue
            output.append(EnergyQuotaModifierRule(
                rule_id=f"t-chnrisc-0008-2025:t{table_number}:note-{note_id}",
                standard_code=STANDARD_CODE,
                table_number=table_number,
                note_id=note_id,
                description=cleaned,
                adjustment_type="conditional_text",
                applicability="requires explicit user/process evidence before application",
                physical_page=page_index + 1,
            ))
    return output


def load_process_parameters(path: Path | None) -> list[ScopedProcessParameterRecord]:
    if path is None:
        return []
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list):
        raise ValueError("process-parameter JSON must be a list")
    return [ScopedProcessParameterRecord(
        parameter_id=item["parameter_id"],
        name=item["name"],
        value=float(item["value"]),
        unit=item["unit"],
        source_type=ParameterSourceType(item["source_type"]),
        provider=item["provider"],
        locator=item["locator"],
        reference_head_material=item["reference_head_material"],
        reference_process=item["reference_process"],
        target_head_material=item["target_head_material"],
        target_process=item["target_process"],
        reference_source_id=item.get("reference_source_id", ""),
        citation=item.get("citation", ""),
        quality_note=item.get("quality_note", ""),
        metadata=item.get("metadata", {}),
    ) for item in values]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("database", type=Path)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--dataset-version", default="t-chnrisc-0008-2025/v1")
    parser.add_argument("--process-parameters-json", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    observed_sha = sha256(args.pdf)
    if observed_sha != args.expected_source_sha256.casefold():
        raise SystemExit(
            f"source PDF SHA-256 mismatch: expected {args.expected_source_sha256}, observed {observed_sha}"
        )
    with pdfplumber.open(args.pdf) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages[:5])
        if "T/CHNRISC 0008" not in text or "2025" not in text:
            raise SystemExit("source PDF is not the expected T/CHNRISC 0008-2025 standard")
        quotas = extract_quotas(pdf, observed_sha)
        conversions = extract_conversions(pdf)
        modifier_rules = extract_modifier_rules(pdf)
    anchor = create_energy_database(
        args.database,
        database_name="refractory-energy-parameters.db",
        dataset_version=args.dataset_version,
        source_standard_code=STANDARD_CODE,
        source_sha256=observed_sha,
        source_locator=f"standard:{STANDARD_CODE.replace(' ', '-')}",
        quotas=quotas,
        conversions=conversions,
        process_parameters=load_process_parameters(args.process_parameters_json),
        modifier_rules=modifier_rules,
        overwrite=args.overwrite,
    )
    print(json.dumps({
        "anchor": anchor.to_dict(),
        "quota_records": len(quotas),
        "conversion_records": len(conversions),
        "modifier_rules": len(modifier_rules),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
