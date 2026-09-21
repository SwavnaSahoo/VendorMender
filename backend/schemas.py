"""Marketplace/category schemas used by VendorMender."""

from __future__ import annotations

from copy import deepcopy

COMMON_OPTIONAL_FIELDS = [
    "Location",
    "Contact Information",
    "Website",
    "Instagram / Social Media",
    "Business Description",
    "Brand Story",
    "Product Description",
    "Shipping Information",
    "Return Policy",
]

MARKETS = {
    "APPAREL": {
        "description": "Independent clothing and fashion brands.",
        "required": [
            "Business Name",
            "Product Name",
            "Category",
            "Price",
            "Product Images",
            "Size",
            "Color",
            "Fabric",
            "Fit",
            "Care Instructions",
        ],
        "optional": COMMON_OPTIONAL_FIELDS.copy(),
    },
    "TABLEWARE": {
        "description": "Independent tableware, cutlery and homeware brands.",
        "required": [
            "Business Name",
            "Product Name",
            "Category",
            "Price",
            "Product Images",
            "Material",
            "Dimensions",
            "Set Quantity",
            "Dishwasher Safe",
            "Care Instructions",
        ],
        "optional": COMMON_OPTIONAL_FIELDS.copy(),
    },
    "JEWELRY": {
        "description": "Independent jewelry and accessories brands.",
        "required": [
            "Business Name",
            "Product Name",
            "Category",
            "Price",
            "Product Images",
            "Material",
            "Plating / Finish",
            "Dimensions",
            "Stone / Gemstone",
            "Care Instructions",
        ],
        "optional": COMMON_OPTIONAL_FIELDS.copy(),
    },
    "FOOTWEAR": {
        "description": "Independent footwear and shoe brands.",
        "required": [
            "Business Name",
            "Product Name",
            "Category",
            "Price",
            "Product Images",
            "Shoe Size",
            "Color",
            "Upper Material",
            "Sole Material",
            "Width",
        ],
        "optional": COMMON_OPTIONAL_FIELDS.copy(),
    },
}

ALL_FIELDS = sorted(
    {
        field
        for market in MARKETS.values()
        for field in market["required"] + market["optional"]
    }
)


def normalize_category(category: str) -> str:
    """Return a canonical category key or raise ValueError."""
    normalized = (category or "").strip().upper()
    if normalized not in MARKETS:
        raise ValueError(
            f"Unsupported category '{category}'. "
            f"Choose one of: {', '.join(MARKETS)}"
        )
    return normalized


def get_market_schema(category: str) -> dict:
    """Return a copy so callers cannot mutate global defaults."""
    return deepcopy(MARKETS[normalize_category(category)])
