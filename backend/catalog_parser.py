"""Spreadsheet ingestion and column mapping for VendorMender."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
from typing import BinaryIO

import pandas as pd


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


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower())


def infer_column_mapping(columns: list[str]) -> dict[str, str]:
    """Map incoming headers to canonical VendorMender fields."""
    aliases = {
        _normalize_header(alias): canonical
        for canonical, values in COLUMN_ALIASES.items()
        for alias in values + [canonical]
    }

    mapping: dict[str, str] = {}
    for column in columns:
        normalized = _normalize_header(column)
        if normalized in aliases:
            mapping[column] = aliases[normalized]
    return mapping


def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(col).strip() for col in df.columns]
    # Replace NaN/NaT with None so JSON responses are clean.
    return df.astype(object).where(pd.notnull(df), None)


def _select_catalog_sheet(excel: pd.ExcelFile) -> str:
    if "Catalog" in excel.sheet_names:
        return "Catalog"
    return excel.sheet_names[0]


def load_excel_catalog(file_path: str | Path) -> tuple[list[dict], dict[str, str]]:
    """Load an Excel catalog from disk and map recognized columns."""
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
    """Parse an uploaded CSV/XLS/XLSX file from bytes."""
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

    df = _clean_dataframe(df)
    mapping = infer_column_mapping(df.columns.tolist())
    mapped = df.rename(columns=mapping)
    return mapped.to_dict(orient="records"), mapping
