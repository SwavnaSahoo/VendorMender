"""Vendor text/file extraction interface.

This is a clean local replacement for the deleted prototype module. It keeps
VendorMender functional without requiring an external model. Later, you can
replace the extraction internals with Gemini/OpenAI/etc. while keeping these
function signatures and the API unchanged.
"""

from __future__ import annotations

from io import BytesIO
import json
import re
from typing import Any

import pandas as pd

from .readiness import is_missing
from .schemas import ALL_FIELDS


FIELD_ALIASES = {
    "Business Name": ["business name", "brand", "company", "company name"],
    "Product Name": ["product name", "product", "item", "item name", "title"],
    "Category": ["category", "product category"],
    "Price": ["price", "retail", "retail price", "msrp"],
    "Size": ["size", "sizes", "sizes available"],
    "Shoe Size": ["shoe size", "shoe sizes", "sizes available"],
    "Color": ["color", "colour", "colors", "colours"],
    "Fabric": ["fabric", "fabrication", "material composition"],
    "Fit": ["fit"],
    "Care Instructions": ["care instructions", "care", "washing instructions"],
    "Material": ["material"],
    "Dimensions": ["dimensions", "measurements"],
    "Set Quantity": ["set quantity", "pieces", "piece count"],
    "Dishwasher Safe": ["dishwasher safe", "dishwasher"],
    "Plating / Finish": ["plating", "finish", "plating / finish"],
    "Stone / Gemstone": ["stone", "gemstone", "stone / gemstone"],
    "Upper Material": ["upper material", "upper"],
    "Sole Material": ["sole material", "sole"],
    "Width": ["width", "shoe width"],
    "Location": ["location", "based in", "city"],
    "Contact Information": ["contact", "email", "phone"],
    "Website": ["website", "site"],
    "Instagram / Social Media": ["instagram", "social media", "social"],
    "Business Description": ["business description", "about"],
    "Brand Story": ["brand story"],
    "Product Description": ["product description", "description"],
    "Shipping Information": ["shipping", "shipping information"],
    "Return Policy": ["return policy", "returns"],
}


def _extract_list_from_context(context: str, heading: str) -> list[str]:
    pattern = rf"{re.escape(heading)}:\s*\n([^\n]+)"
    match = re.search(pattern, context, flags=re.IGNORECASE)
    if not match:
        return []
    return [part.strip() for part in match.group(1).split(",") if part.strip()]


def _extract_category_from_context(context: str) -> str | None:
    match = re.search(
        r"CURRENT MARKETPLACE PRODUCT CATEGORY:\s*\n([^\n]+)",
        context,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip().upper() if match else None


def _extract_submission_text(context: str) -> str:
    patterns = [
        r"VENDOR SUBMISSION:\s*\n-+\s*\n(.*?)\n-+",
        r"VENDOR PROVIDED:\s*\n-+\s*\n(.*?)\n-+",
    ]
    for pattern in patterns:
        match = re.search(pattern, context, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return context


def _extract_key_value_fields(text: str) -> dict[str, Any]:
    extracted: dict[str, Any] = {}
    alias_lookup = {
        alias.lower(): field
        for field, aliases in FIELD_ALIASES.items()
        for alias in aliases + [field]
    }

    for raw_line in text.splitlines():
        line = raw_line.strip().strip("-*•")
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        canonical = alias_lookup.get(key.strip().lower())
        if canonical and value.strip():
            extracted[canonical] = value.strip()

    # Useful conservative patterns for unstructured messages.
    if "Price" not in extracted:
        price_match = re.search(r"(?:\$|USD\s*)(\d+(?:\.\d{1,2})?)", text, flags=re.I)
        if price_match:
            extracted["Price"] = float(price_match.group(1))

    if "Contact Information" not in extracted:
        email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
        if email_match:
            extracted["Contact Information"] = email_match.group(0)

    if "Instagram / Social Media" not in extracted:
        insta_match = re.search(r"(?<!\w)@[A-Za-z0-9._]{2,}", text)
        if insta_match:
            extracted["Instagram / Social Media"] = insta_match.group(0)

    if "Website" not in extracted:
        url_match = re.search(r"https?://\S+|www\.\S+", text, flags=re.I)
        if url_match:
            extracted["Website"] = url_match.group(0).rstrip(".,)")

    return extracted


def _question_for(field: str) -> str:
    prompts = {
        "Product Images": "Please upload at least one actual product image.",
        "Price": "What is the product price?",
        "Size": "What sizes are available?",
        "Shoe Size": "What shoe sizes are available?",
        "Color": "What colors are available?",
        "Fabric": "What fabric/material composition is used?",
        "Fit": "What is the product fit?",
        "Care Instructions": "What are the care instructions?",
    }
    return prompts.get(field, f"Please provide {field}.")


def _analysis_from_extracted(
    extracted: dict[str, Any],
    required_fields: list[str],
    optional_fields: list[str],
    category: str | None,
) -> dict:
    required_gaps = [
        field
        for field in required_fields
        if is_missing(extracted.get(field), field)
    ]
    optional_gaps = [
        field
        for field in optional_fields
        if is_missing(extracted.get(field), field)
    ]

    total = len(required_fields)
    readiness = round(((total - len(required_gaps)) / total) * 100) if total else 100

    return {
        "business_name": extracted.get("Business Name"),
        "category": category or extracted.get("Category"),
        "location": extracted.get("Location"),
        "contact": extracted.get("Contact Information"),
        "social_media": extracted.get("Instagram / Social Media"),
        "business_description": extracted.get("Business Description"),
        "brand_story": extracted.get("Brand Story"),
        "information_found": [
            f"{field}: {value}"
            for field, value in extracted.items()
            if not is_missing(value, field)
        ],
        "products_found": [extracted.get("Product Name")] if extracted.get("Product Name") else [],
        "required_gaps": required_gaps,
        "optional_gaps": optional_gaps,
        "follow_up_questions": [_question_for(field) for field in required_gaps],
        "readiness_score": readiness,
        "status": "Publish Ready" if not required_gaps else ("Almost Ready" if readiness >= 80 else "Needs Information"),
        "extracted_fields": extracted,
    }


def analyze_vendor_text(context: str) -> dict:
    """Analyze text using deterministic extraction and active schema context."""
    required_fields = _extract_list_from_context(context, "REQUIRED FIELDS")
    optional_fields = _extract_list_from_context(context, "OPTIONAL FIELDS")
    category = _extract_category_from_context(context)
    submission = _extract_submission_text(context)
    extracted = _extract_key_value_fields(submission)

    # Category is context, not something the vendor should have to repeat.
    if category and "Category" in required_fields and "Category" not in extracted:
        extracted["Category"] = category

    return _analysis_from_extracted(
        extracted=extracted,
        required_fields=required_fields,
        optional_fields=optional_fields,
        category=category,
    )


def analyze_vendor_files(uploaded_files, catalog_context: str) -> dict:
    """Compatibility function for the legacy Streamlit prototype.

    Reads CSV/XLSX/TXT files where possible and counts actual uploaded images
    as satisfying Product Images. PDF text extraction is intentionally not
    guessed here; the file is acknowledged but should later be routed through
    a dedicated parser/model service.
    """
    required_fields = _extract_list_from_context(catalog_context, "REQUIRED FIELDS")
    optional_fields = _extract_list_from_context(catalog_context, "OPTIONAL FIELDS")
    category = _extract_category_from_context(catalog_context)

    combined_text: list[str] = []
    actual_image_count = 0

    for uploaded in uploaded_files:
        name = uploaded.name.lower()
        content = uploaded.getvalue() if hasattr(uploaded, "getvalue") else uploaded.read()

        if name.endswith((".png", ".jpg", ".jpeg")):
            actual_image_count += 1
            continue

        if name.endswith(".txt"):
            combined_text.append(content.decode("utf-8", errors="ignore"))
            continue

        if name.endswith(".csv"):
            df = pd.read_csv(BytesIO(content))
            combined_text.append(df.to_csv(index=False))
            continue

        if name.endswith((".xlsx", ".xls")):
            excel = pd.ExcelFile(BytesIO(content))
            df = pd.read_excel(excel, sheet_name=excel.sheet_names[0])
            combined_text.append(df.head(50).to_csv(index=False))
            continue

        combined_text.append(f"Uploaded file: {uploaded.name}")

    extracted = _extract_key_value_fields("\n".join(combined_text))
    if category and "Category" in required_fields:
        extracted.setdefault("Category", category)
    if actual_image_count:
        extracted["Product Images"] = "Uploaded"

    return _analysis_from_extracted(
        extracted=extracted,
        required_fields=required_fields,
        optional_fields=optional_fields,
        category=category,
    )


def update_vendor_analysis(schema_context: str, answers: list[dict]) -> dict:
    """Apply follow-up answers and re-evaluate against the active schema."""
    original_match = re.search(
        r"ORIGINAL ANALYSIS CONTEXT:\s*(.*?)(?:\nIMPORTANT:|$)",
        schema_context,
        flags=re.IGNORECASE | re.DOTALL,
    )
    original_context = original_match.group(1).strip() if original_match else schema_context
    base = analyze_vendor_text(original_context)
    extracted = dict(base.get("extracted_fields", {}))

    required_fields = _extract_list_from_context(schema_context, "REQUIRED FIELDS") or base.get("required_gaps", [])
    optional_fields = _extract_list_from_context(schema_context, "OPTIONAL FIELDS")
    category = _extract_category_from_context(schema_context) or base.get("category")

    for item in answers:
        question = str(item.get("question", ""))
        answer = item.get("answer")
        if not answer or not str(answer).strip():
            continue

        matched_field = next(
            (field for field in required_fields + optional_fields if field.lower() in question.lower()),
            None,
        )
        if matched_field:
            extracted[matched_field] = str(answer).strip()

    return _analysis_from_extracted(
        extracted=extracted,
        required_fields=required_fields,
        optional_fields=optional_fields,
        category=category,
    )
