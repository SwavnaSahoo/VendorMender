"""Deterministic readiness and gap logic for VendorMender."""

from __future__ import annotations

from collections import Counter
from math import isnan
from typing import Any


IMAGE_PRESENT_VALUES = {
    "provided",
    "uploaded",
    "yes",
    "true",
    "available",
    "attached",
}


def is_missing(value: Any, field: str | None = None) -> bool:
    """Return True when a field should be treated as unresolved."""
    if value is None:
        return True

    if isinstance(value, float):
        try:
            if isnan(value):
                return True
        except TypeError:
            pass

    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return True

        # Product Images is special. In real flows, an uploaded asset is the
        # authoritative proof. The built-in demo uses "Provided" as a fixed
        # deterministic stand-in for a valid image.
        if field == "Product Images":
            return cleaned.lower() not in IMAGE_PRESENT_VALUES

    return False


def _resolve_value(
    product: dict,
    field: str,
    vendor_context: dict | None = None,
) -> Any:
    vendor_context = vendor_context or {}

    # Business-level data can satisfy product-level readiness without being
    # repeated in every spreadsheet row.
    if field in vendor_context and not is_missing(vendor_context.get(field), field):
        return vendor_context.get(field)

    return product.get(field)


def evaluate_product(
    product: dict,
    required_fields: list[str],
    vendor_context: dict | None = None,
) -> dict:
    """Evaluate one SKU against the active marketplace requirements."""
    missing_fields: list[str] = []

    for field in required_fields:
        value = _resolve_value(product, field, vendor_context)
        if is_missing(value, field):
            missing_fields.append(field)

    total_required = len(required_fields)
    satisfied = total_required - len(missing_fields)
    readiness_score = (
        round((satisfied / total_required) * 100)
        if total_required
        else 100
    )

    return {
        "SKU": product.get("SKU"),
        "Product Name": product.get("Product Name"),
        "Status": "Publish Ready" if not missing_fields else "Needs Attention",
        "Readiness %": readiness_score,
        "Missing Fields": missing_fields,
        "Price": product.get("Price"),
        "Inventory": product.get("Inventory"),
    }


def evaluate_catalog(
    products: list[dict],
    required_fields: list[str],
    vendor_context: dict | None = None,
) -> dict:
    """Evaluate every SKU and return aggregate readiness statistics."""
    results = [
        evaluate_product(
            product=product,
            required_fields=required_fields,
            vendor_context=vendor_context,
        )
        for product in products
    ]

    ready_count = sum(
        1 for result in results if result["Status"] == "Publish Ready"
    )
    needs_attention = len(results) - ready_count
    average_readiness = (
        round(sum(row["Readiness %"] for row in results) / len(results))
        if results
        else 0
    )

    gap_counter: Counter[str] = Counter()
    for result in results:
        gap_counter.update(result["Missing Fields"])

    return {
        "total_skus": len(results),
        "publish_ready": ready_count,
        "needs_attention": needs_attention,
        "average_readiness": average_readiness,
        "gap_counts": dict(gap_counter),
        "products": results,
    }
