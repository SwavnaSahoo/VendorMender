"""VendorMender AI helpers.

This module keeps the existing deterministic text-extraction behavior and adds
an optional Gemini-powered semantic column mapper for messy vendor catalogs.

Design principle:
- deterministic rules handle obvious matches cheaply and predictably
- Gemini is used only for unresolved/ambiguous columns
- Gemini can suggest mappings, but it cannot change marketplace requirements
- readiness remains deterministic in readiness.py
"""

from __future__ import annotations

import json
import os
import re
from io import BytesIO
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from .readiness import is_missing


# =========================================================
# EXISTING TEXT EXTRACTION
# =========================================================

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
        "status": "Publish Ready"
        if not required_gaps
        else ("Almost Ready" if readiness >= 80 else "Needs Information"),
        "extracted_fields": extracted,
    }


def analyze_vendor_text(context: str) -> dict:
    """Analyze text using deterministic extraction and active schema context."""
    required_fields = _extract_list_from_context(context, "REQUIRED FIELDS")
    optional_fields = _extract_list_from_context(context, "OPTIONAL FIELDS")
    category = _extract_category_from_context(context)
    submission = _extract_submission_text(context)
    extracted = _extract_key_value_fields(submission)

    if category and "Category" in required_fields and "Category" not in extracted:
        extracted["Category"] = category

    return _analysis_from_extracted(
        extracted=extracted,
        required_fields=required_fields,
        optional_fields=optional_fields,
        category=category,
    )


def analyze_vendor_files(uploaded_files, catalog_context: str) -> dict:
    """Compatibility function for the legacy Streamlit prototype."""
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

    required_fields = (
        _extract_list_from_context(schema_context, "REQUIRED FIELDS")
        or base.get("required_gaps", [])
    )
    optional_fields = _extract_list_from_context(schema_context, "OPTIONAL FIELDS")
    category = _extract_category_from_context(schema_context) or base.get("category")

    for item in answers:
        question = str(item.get("question", ""))
        answer = item.get("answer")
        if not answer or not str(answer).strip():
            continue

        matched_field = next(
            (
                field
                for field in required_fields + optional_fields
                if field.lower() in question.lower()
            ),
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


# =========================================================
# GEMINI SEMANTIC COLUMN MAPPER
# =========================================================

class SemanticColumnDecision(BaseModel):
    source_column: str
    target_field: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class SemanticMappingResponse(BaseModel):
    decisions: list[SemanticColumnDecision]


def _get_gemini_client():
    """Return a Gemini client, or None when no API key is configured."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        from google import genai
    except ImportError:
        return None

    return genai.Client(api_key=api_key)


def semantic_map_columns(
    *,
    category: str,
    allowed_fields: list[str],
    unresolved_columns: list[dict[str, Any]],
    already_mapped_fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Use Gemini to map unresolved vendor columns to marketplace fields.

    Each unresolved column is shaped like:
        {
            "name": "Mat.",
            "samples": ["ceramic", "stoneware", "porcelain"]
        }

    The model may choose only one of ``allowed_fields`` or ``PRESERVE``.
    Failures degrade safely to PRESERVE instead of breaking catalog upload.
    """

    if not unresolved_columns:
        return []

    client = _get_gemini_client()
    if client is None:
        return [
            {
                "source_column": item["name"],
                "target_field": "PRESERVE",
                "confidence": 0.0,
                "reason": "AI mapper unavailable; preserved for manual review.",
            }
            for item in unresolved_columns
        ]

    already_mapped_fields = already_mapped_fields or []
    candidate_fields = [
        field for field in allowed_fields if field not in set(already_mapped_fields)
    ]

    prompt_payload = {
        "category": category,
        "allowed_target_fields": candidate_fields,
        "already_mapped_fields": already_mapped_fields,
        "incoming_columns": unresolved_columns,
    }

    prompt = f"""
You are VendorMender's semantic catalog-column mapper.

Your job is ONLY to map messy vendor spreadsheet columns to the marketplace's
allowed canonical fields.

IMPORTANT RULES:
1. For each incoming column, choose exactly ONE target_field from
   allowed_target_fields, OR choose the literal string PRESERVE.
2. Never invent a marketplace field.
3. Never map a column to a field that is already listed in already_mapped_fields.
4. Use BOTH the column name and its sample cell values.
5. Abbreviations, shorthand, spelling variation, and vendor jargon are allowed.
6. If the semantic meaning is ambiguous, use PRESERVE rather than guessing.
7. Confidence must be a number from 0.0 to 1.0.
8. Return one decision for every incoming column.
9. Do not decide whether a product is publish-ready. You only map columns.
10. Product requirements are controlled elsewhere; do not add or remove them.

Examples of semantic reasoning:
- "Mat." with values like ceramic/stoneware can mean Material.
- "Qty Set" with values like 4 bowls/6 pieces can mean Set Quantity.
- "DW Safe?" with values Y/No/Yes can mean Dishwasher Safe.
- "Measurements" with values like 8 in diameter can mean Dimensions.
- "Cost" with currency-like numeric values can mean Price.
- If a column has no allowed semantic equivalent, return PRESERVE.

INPUT:
{json.dumps(prompt_payload, ensure_ascii=False, indent=2, default=str)}
""".strip()

    try:
        from google.genai import types

        model_name = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SemanticMappingResponse,
                temperature=0,
            ),
        )

        parsed = json.loads(response.text or "{}")
        payload = SemanticMappingResponse.model_validate(parsed)
        decisions = payload.decisions

    except Exception as exc:
        return [
            {
                "source_column": item["name"],
                "target_field": "PRESERVE",
                "confidence": 0.0,
                "reason": f"AI mapper failed safely: {type(exc).__name__}",
            }
            for item in unresolved_columns
        ]

    unresolved_names = {item["name"] for item in unresolved_columns}
    valid_targets = set(candidate_fields) | {"PRESERVE"}
    normalized: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    seen_targets: set[str] = set(already_mapped_fields)

    for decision in decisions:
        source = decision.source_column
        target = decision.target_field

        if source not in unresolved_names or source in seen_sources:
            continue

        if target not in valid_targets:
            target = "PRESERVE"

        if target != "PRESERVE" and target in seen_targets:
            target = "PRESERVE"

        if target != "PRESERVE":
            seen_targets.add(target)

        seen_sources.add(source)
        normalized.append(
            {
                "source_column": source,
                "target_field": target,
                "confidence": round(float(decision.confidence), 4),
                "reason": decision.reason.strip(),
            }
        )

    # Guarantee a safe decision for every unresolved source column.
    returned_sources = {item["source_column"] for item in normalized}
    for item in unresolved_columns:
        if item["name"] not in returned_sources:
            normalized.append(
                {
                    "source_column": item["name"],
                    "target_field": "PRESERVE",
                    "confidence": 0.0,
                    "reason": "No valid semantic mapping was returned; preserved for review.",
                }
            )

    return normalized
