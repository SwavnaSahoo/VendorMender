"""Built-in deterministic 20-SKU VendorMender demo."""

from __future__ import annotations

from pathlib import Path

from .catalog_parser import load_excel_catalog
from .readiness import evaluate_catalog
from .schemas import get_market_schema


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO_FILE = PROJECT_ROOT / "data" / "VendorMender_Demo_Catalog_20_SKUs.xlsx"

DEMO_VENDOR = {
    "Business Name": "Cherry Thread Demo Co.",
}

EXPECTED_DEMO_GAPS = {
    "VM-004": ["Care Instructions"],
    "VM-007": ["Product Images"],
    "VM-010": ["Fit"],
    "VM-012": ["Fabric"],
    "VM-015": ["Size"],
    "VM-018": ["Price"],
}


def run_demo() -> dict:
    products, mapping = load_excel_catalog(DEMO_FILE)
    schema = get_market_schema("APPAREL")
    result = evaluate_catalog(
        products=products,
        required_fields=schema["required"],
        vendor_context=DEMO_VENDOR,
    )

    actual_gaps = {
        row["SKU"]: row["Missing Fields"]
        for row in result["products"]
        if row["Missing Fields"]
    }

    return {
        "demo": True,
        "synthetic_data": True,
        "vendor": DEMO_VENDOR["Business Name"],
        "category": "APPAREL",
        "file_name": DEMO_FILE.name,
        "column_mapping": mapping,
        "process": [
            {"step": 1, "name": "INPUT", "description": "20 SKU rows detected"},
            {"step": 2, "name": "MAP", "description": "Catalog fields mapped to marketplace schema"},
            {"step": 3, "name": "MEND", "description": "Required attributes validated per SKU"},
            {"step": 4, "name": "OUTPUT", "description": "SKU readiness generated"},
        ],
        "expected_gaps": EXPECTED_DEMO_GAPS,
        "demo_integrity_ok": actual_gaps == EXPECTED_DEMO_GAPS,
        **result,
    }
