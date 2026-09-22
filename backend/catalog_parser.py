"""Spreadsheet ingestion and hybrid deterministic + AI column mapping."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
import re
from typing import Any

import pandas as pd

from .ai_engine import semantic_map_columns


# These fields are useful catalog metadata but do not block marketplace
# publishing unless a marketplace explicitly adds them to its schema.
NON_BLOCKING_CATALOG_FIELDS = [
    "SKU",
    "Description",
    "Inventory",
    "Vendor Notes",
]


COLUMN_ALIASES = {
    "SKU": ["sku", "item sku", "product sku", "style code", "item code"],
    "Product Name": ["product name", "product", "item", "item name", "name", "title"],
    "Description": ["description", "product description", "details"],
    "Category": ["category", "product category", "type"],
    "Price": ["price", "retail", "retail price", "msrp", "selling price"],
    "Product Images": ["product images", "images", "image", "photos", "photo"],
    "Size": ["size", "sizes", "sizes available", "available sizes"],
    "Shoe Size": ["shoe size", "shoe sizes", "footwear size", "sizes available"],
    "Color": ["color", "colour", "colors", "colours"],
    "Fabric": ["fabric", "fabrication", "material composition", "composition"],
    "Fit": ["fit", "silhouette"],
    "Care Instructions": ["care instructions", "care", "washing instructions"],
    "Material": ["material", "materials"],
    "Dimensions": ["dimensions", "dimension", "measurements", "measurement"],
    "Set Quantity": ["set quantity", "set qty", "pieces", "piece count", "quantity in set"],
    "Dishwasher Safe": ["dishwasher safe", "dishwasher", "dishwasher compatibility"],
    "Plating / Finish": ["plating / finish", "plating", "finish"],
    "Stone / Gemstone": ["stone / gemstone", "stone", "gemstone", "gem"],
    "Upper Material": ["upper material", "upper"],
    "Sole Material": ["sole material", "sole"],
    "Width": ["width", "shoe width"],
    "Inventory": ["inventory", "stock", "units", "qty", "quantity"],
    "Vendor Notes": ["vendor notes", "notes", "comments"],
}


AUTO_MAP_THRESHOLD = 0.90
CONFIRM_THRESHOLD = 0.70


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower())


def infer_column_mapping(columns: list[str]) -> dict[str, str]:
    """Cheap deterministic pass for exact/known aliases."""
    aliases = {
        _normalize_header(alias): canonical
        for canonical, values in COLUMN_ALIASES.items()
        for alias in values + [canonical]
    }

    mapping: dict[str, str] = {}
    used_targets: set[str] = set()

    for column in columns:
        normalized = _normalize_header(column)
        target = aliases.get(normalized)
        if target and target not in used_targets:
            mapping[column] = target
            used_targets.add(target)

    return mapping


def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(col).strip() for col in df.columns]
    return df.astype(object).where(pd.notnull(df), None)


def _select_catalog_sheet(excel: pd.ExcelFile) -> str:
    if "Catalog" in excel.sheet_names:
        return "Catalog"
    return excel.sheet_names[0]


def _read_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    lower_name = filename.lower()
    buffer = BytesIO(content)

    if lower_name.endswith(".csv"):
        df = pd.read_csv(buffer)
    elif lower_name.endswith((".xlsx", ".xls")):
        excel = pd.ExcelFile(buffer)
        sheet = _select_catalog_sheet(excel)
        df = pd.read_excel(excel, sheet_name=sheet)
    else:
        raise ValueError("Supported catalog types are CSV, XLS, and XLSX.")

    return _clean_dataframe(df)


def _sample_values(df: pd.DataFrame, column: str, limit: int = 5) -> list[str]:
    values: list[str] = []

    for value in df[column].tolist():
        if value is None:
            continue

        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null"}:
            continue

        if text not in values:
            values.append(text)

        if len(values) >= limit:
            break

    return values


def _allowed_targets(schema_fields: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for field in schema_fields + NON_BLOCKING_CATALOG_FIELDS:
        if field not in seen:
            seen.add(field)
            result.append(field)

    return result


def build_smart_mapping(
    df: pd.DataFrame,
    *,
    category: str,
    schema_fields: list[str],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Build mapping using deterministic aliases first, Gemini second.

    Returns:
      mapping:
        Only mappings that are safe to apply automatically.

      mapping_details:
        One UI-friendly record per incoming column. AI suggestions in the
        70-89% band are returned as CONFIRM and are NOT applied until the
        frontend sends them back as an explicit override.
    """

    columns = df.columns.tolist()
    deterministic = infer_column_mapping(columns)
    mapping: dict[str, str] = dict(deterministic)

    details: list[dict[str, Any]] = []

    for source, target in deterministic.items():
        details.append(
            {
                "source_column": source,
                "target_field": target,
                "suggested_target": target,
                "confidence": 1.0,
                "state": "AUTO_MAPPED",
                "source": "rule",
                "applied": True,
                "reason": "Exact or known alias match.",
                "samples": _sample_values(df, source),
            }
        )

    unresolved = [column for column in columns if column not in deterministic]

    if unresolved:
        unresolved_payload = [
            {
                "name": column,
                "samples": _sample_values(df, column),
            }
            for column in unresolved
        ]

        allowed_fields = _allowed_targets(schema_fields)

        ai_decisions = semantic_map_columns(
            category=category,
            allowed_fields=allowed_fields,
            unresolved_columns=unresolved_payload,
            already_mapped_fields=list(deterministic.values()),
        )

        decisions_by_source = {
            decision["source_column"]: decision
            for decision in ai_decisions
        }

        used_targets = set(mapping.values())

        for column in unresolved:
            decision = decisions_by_source.get(
                column,
                {
                    "source_column": column,
                    "target_field": "PRESERVE",
                    "confidence": 0.0,
                    "reason": "No semantic decision returned.",
                },
            )

            target = decision["target_field"]
            confidence = float(decision["confidence"])
            reason = decision["reason"]

            if target == "PRESERVE":
                state = "PRESERVED"
                applied = False
                suggested_target = None

            elif confidence >= AUTO_MAP_THRESHOLD and target not in used_targets:
                state = "AUTO_MAPPED"
                applied = True
                suggested_target = target
                mapping[column] = target
                used_targets.add(target)

            elif confidence >= CONFIRM_THRESHOLD:
                state = "CONFIRM"
                applied = False
                suggested_target = target

            else:
                state = "PRESERVED"
                applied = False
                suggested_target = target if target != "PRESERVE" else None

            details.append(
                {
                    "source_column": column,
                    "target_field": target if applied else None,
                    "suggested_target": suggested_target,
                    "confidence": round(confidence, 4),
                    "state": state,
                    "source": "ai",
                    "applied": applied,
                    "reason": reason,
                    "samples": _sample_values(df, column),
                }
            )

    # Preserve spreadsheet order in the UI.
    order = {column: index for index, column in enumerate(columns)}
    details.sort(key=lambda item: order[item["source_column"]])

    return mapping, details


def _validate_overrides(
    overrides: dict[str, str],
    *,
    columns: list[str],
    allowed_fields: list[str],
) -> dict[str, str]:
    valid_sources = set(columns)
    valid_targets = set(_allowed_targets(allowed_fields)) | {"PRESERVE"}

    cleaned: dict[str, str] = {}
    used_targets: set[str] = set()

    for source, target in overrides.items():
        if source not in valid_sources:
            raise ValueError(f"Unknown source column in mapping override: {source}")

        if target not in valid_targets:
            raise ValueError(f"Invalid mapping target '{target}' for column '{source}'.")

        if target != "PRESERVE":
            if target in used_targets:
                raise ValueError(f"Multiple source columns cannot map to '{target}'.")
            used_targets.add(target)

        cleaned[source] = target

    return cleaned


def apply_mapping_overrides(
    *,
    base_mapping: dict[str, str],
    mapping_details: list[dict[str, Any]],
    overrides: dict[str, str],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Apply explicit user-confirmed mappings from the frontend."""

    mapping = dict(base_mapping)
    detail_by_source = {item["source_column"]: dict(item) for item in mapping_details}

    # Overrides are authoritative. Remove any current mapping for each source.
    for source in overrides:
        mapping.pop(source, None)

    # Also remove existing mappings that target a field now claimed elsewhere.
    override_targets = {
        target for target in overrides.values() if target != "PRESERVE"
    }
    mapping = {
        source: target
        for source, target in mapping.items()
        if target not in override_targets
    }

    for source, target in overrides.items():
        detail = detail_by_source[source]

        if target == "PRESERVE":
            detail.update(
                {
                    "target_field": None,
                    "suggested_target": None,
                    "state": "PRESERVED",
                    "source": "user",
                    "applied": False,
                    "confidence": 1.0,
                    "reason": "Preserved by user confirmation.",
                }
            )
        else:
            mapping[source] = target
            detail.update(
                {
                    "target_field": target,
                    "suggested_target": target,
                    "state": "CONFIRMED",
                    "source": "user",
                    "applied": True,
                    "confidence": 1.0,
                    "reason": "Confirmed by user.",
                }
            )

        detail_by_source[source] = detail

    updated_details = [detail_by_source[item["source_column"]] for item in mapping_details]
    return mapping, updated_details


def preview_uploaded_catalog_mapping(
    content: bytes,
    filename: str,
    *,
    category: str,
    schema_fields: list[str],
) -> dict[str, Any]:
    """Return semantic mapping suggestions before readiness validation."""

    df = _read_dataframe(content, filename)
    mapping, details = build_smart_mapping(
        df,
        category=category,
        schema_fields=schema_fields,
    )

    preview_df = df.head(8)

    return {
        "file_name": filename,
        "row_count": len(df),
        "columns": df.columns.tolist(),
        "preview_rows": preview_df.to_dict(orient="records"),
        "column_mapping": mapping,
        "mapping_details": details,
        "auto_mapped_count": sum(1 for item in details if item["state"] == "AUTO_MAPPED"),
        "confirm_count": sum(1 for item in details if item["state"] == "CONFIRM"),
        "preserved_count": sum(1 for item in details if item["state"] == "PRESERVED"),
    }


def parse_uploaded_catalog_smart(
    content: bytes,
    filename: str,
    *,
    category: str,
    schema_fields: list[str],
    mapping_overrides: dict[str, str] | None = None,
) -> tuple[list[dict], dict[str, str], list[dict[str, Any]]]:
    """Parse, semantically map, optionally confirm, then return canonical rows."""

    df = _read_dataframe(content, filename)
    mapping, details = build_smart_mapping(
        df,
        category=category,
        schema_fields=schema_fields,
    )

    if mapping_overrides:
        cleaned_overrides = _validate_overrides(
            mapping_overrides,
            columns=df.columns.tolist(),
            allowed_fields=schema_fields,
        )
        mapping, details = apply_mapping_overrides(
            base_mapping=mapping,
            mapping_details=details,
            overrides=cleaned_overrides,
        )

    mapped = df.rename(columns=mapping)
    return mapped.to_dict(orient="records"), mapping, details


# =========================================================
# BACKWARD-COMPATIBLE HELPERS USED BY THE DEMO
# =========================================================

def load_excel_catalog(file_path: str | Path) -> tuple[list[dict], dict[str, str]]:
    """Load the built-in demo workbook deterministically."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Catalog file not found: {path}")

    excel = pd.ExcelFile(path)
    sheet = _select_catalog_sheet(excel)
    df = _clean_dataframe(pd.read_excel(excel, sheet_name=sheet))
    mapping = infer_column_mapping(df.columns.tolist())
    mapped = df.rename(columns=mapping)
    return mapped.to_dict(orient="records"), mapping


def parse_uploaded_catalog(
    content: bytes,
    filename: str,
) -> tuple[list[dict], dict[str, str]]:
    """Legacy deterministic parser retained for compatibility."""
    df = _read_dataframe(content, filename)
    mapping = infer_column_mapping(df.columns.tolist())
    mapped = df.rename(columns=mapping)
    return mapped.to_dict(orient="records"), mapping


def parse_mapping_overrides_json(raw: str | None) -> dict[str, str] | None:
    if raw is None or not raw.strip():
        return None

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("mapping_overrides must be valid JSON.") from exc

    if not isinstance(value, dict):
        raise ValueError("mapping_overrides must be a JSON object.")

    return {str(key): str(target) for key, target in value.items()}
