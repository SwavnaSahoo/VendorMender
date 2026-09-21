"""FastAPI entry point for VendorMender."""

from __future__ import annotations

import os

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .ai_engine import analyze_vendor_text
from .catalog_parser import parse_uploaded_catalog
from .database import (
    create_marketplace,
    create_vendor,
    get_marketplaces,
    get_schema,
    get_vendors,
    init_db,
    save_schema,
)
from .demo import run_demo
from .readiness import evaluate_catalog
from .schemas import MARKETS, get_market_schema, normalize_category


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="VendorMender API",
    version="1.0.0",
    description="Adaptive marketplace vendor onboarding backend.",
)


# =========================================================
# CORS
# =========================================================

# Render environment variable example:
#
# FRONTEND_ORIGINS=https://your-lovable-site.lovable.app
#
# Multiple frontends can be comma-separated:
#
# FRONTEND_ORIGINS=https://site1.com,https://site2.com

default_origins = (
    "http://localhost:5173,"
    "http://localhost:3000"
)

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        default_origins,
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
def startup() -> None:
    init_db()


# =========================================================
# REQUEST MODELS
# =========================================================

class MessageAnalyzeRequest(BaseModel):
    category: str

    message: str = Field(
        min_length=1
    )

    marketplace_name: str = "LOCALSTYLE"

    marketplace_description: str | None = None

    required_fields: list[str] | None = None

    optional_fields: list[str] | None = None


class MarketplaceCreateRequest(BaseModel):
    name: str = Field(
        min_length=1
    )

    description: str | None = None


class SchemaSaveRequest(BaseModel):
    marketplace_id: int

    category: str

    required_fields: list[str]

    optional_fields: list[str] = []


class VendorCreateRequest(BaseModel):
    marketplace_id: int

    business_name: str = Field(
        min_length=1
    )

    location: str | None = None

    contact_information: str | None = None

    social_media: str | None = None

    business_description: str | None = None

    brand_story: str | None = None

    status: str = "Needs Information"


# =========================================================
# ROOT / HEALTH
# =========================================================

@app.get("/")
def root() -> dict:
    return {
        "name": "VendorMender API",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok"
    }


# =========================================================
# CATEGORIES
# =========================================================

@app.get("/api/categories")
def categories() -> dict:
    return MARKETS


# =========================================================
# DEFAULT CATEGORY SCHEMA
# =========================================================

@app.get("/api/schema/{category}")
def category_schema(
    category: str
) -> dict:

    try:
        normalized = normalize_category(
            category
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    return {
        "category": normalized,
        **get_market_schema(normalized),
    }


# =========================================================
# MARKETPLACES
# =========================================================

@app.post("/api/marketplaces")
def add_marketplace(
    payload: MarketplaceCreateRequest
) -> dict:

    marketplace_id = create_marketplace(
        payload.name,
        payload.description,
    )

    return {
        "marketplace_id": marketplace_id
    }


@app.get("/api/marketplaces")
def list_marketplaces() -> list[dict]:

    return get_marketplaces()


# =========================================================
# SAVED MARKETPLACE SCHEMAS
# =========================================================

@app.put("/api/schema")
def persist_schema(
    payload: SchemaSaveRequest
) -> dict:

    try:
        category = normalize_category(
            payload.category
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    if not payload.required_fields:
        raise HTTPException(
            status_code=400,
            detail=(
                "At least one required field is needed."
            ),
        )

    schema_id = save_schema(
        marketplace_id=payload.marketplace_id,
        category=category,
        required_fields=payload.required_fields,
        optional_fields=payload.optional_fields,
    )

    return {
        "schema_id": schema_id,
        "marketplace_id": payload.marketplace_id,
        "category": category,
        "required_fields": payload.required_fields,
        "optional_fields": payload.optional_fields,
    }


@app.get(
    "/api/schema/{marketplace_id}/{category}"
)
def saved_schema(
    marketplace_id: int,
    category: str,
) -> dict:

    schema = get_schema(
        marketplace_id,
        category,
    )

    if not schema:
        raise HTTPException(
            status_code=404,
            detail="Saved schema not found.",
        )

    return schema


# =========================================================
# VENDORS
# =========================================================

@app.post("/api/vendors")
def add_vendor(
    payload: VendorCreateRequest
) -> dict:

    vendor_id = create_vendor(
        **payload.model_dump()
    )

    return {
        "vendor_id": vendor_id
    }


@app.get("/api/vendors")
def list_vendors(
    marketplace_id: int | None = None
) -> list[dict]:

    return get_vendors(
        marketplace_id
    )


# =========================================================
# DEMO
# =========================================================

@app.get("/api/demo")
def demo() -> dict:

    result = run_demo()

    if not result["demo_integrity_ok"]:
        raise HTTPException(
            status_code=500,
            detail=(
                "Demo integrity check failed. "
                "The workbook no longer matches "
                "the expected fixture."
            ),
        )

    return result


# =========================================================
# MESSAGE ANALYSIS
# =========================================================

@app.post("/api/message/analyze")
def analyze_message(
    payload: MessageAnalyzeRequest
) -> dict:

    try:
        category = normalize_category(
            payload.category
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    default_schema = get_market_schema(
        category
    )

    required = (
        payload.required_fields
        or default_schema["required"]
    )

    optional = (
        payload.optional_fields
        if payload.optional_fields is not None
        else default_schema["optional"]
    )

    description = (
        payload.marketplace_description
        or default_schema["description"]
    )

    context = f"""
MARKETPLACE NAME:
{payload.marketplace_name}

MARKETPLACE DESCRIPTION:
{description}

CURRENT MARKETPLACE PRODUCT CATEGORY:
{category}

REQUIRED FIELDS:
{", ".join(required)}

OPTIONAL FIELDS:
{", ".join(optional)}

CRITICAL RULES:

The marketplace configuration above overrides
generic assumptions.

Use ONLY the explicitly listed REQUIRED FIELDS
when deciding required_gaps.

Do not convert optional fields into required fields.

Do not ask for information that has already
been supplied or that can be confidently mapped.

Ask the MINIMUM number of questions necessary
to resolve required gaps.

CATEGORY INTERPRETATION:

APPAREL:
Size = garment sizing.
Color = available garment colors.
Fabric = garment material.
Fit = garment fit.
Care Instructions = garment care.

TABLEWARE:
Material = item material.
Dimensions = physical measurements.
Set Quantity = number of pieces.
Dishwasher Safe = dishwasher compatibility.
Care Instructions = care requirements.

JEWELRY:
Material = jewelry base material.
Plating / Finish = plating or finish.
Dimensions = jewelry measurements.
Stone / Gemstone = gemstone information.

If the vendor explicitly says there is
no gemstone, Stone / Gemstone is answered.

Care Instructions = jewelry care.

FOOTWEAR:
Shoe Size = footwear sizes.
Color = available colors.
Upper Material = shoe upper material.
Sole Material = sole material.
Width = shoe width.

PRODUCT IMAGES:

Text alone does not prove product images
were actually supplied.

VENDOR ARRIVAL METHOD:
MESSAGE / EMAIL / DM / WHATSAPP / NOTES

VENDOR SUBMISSION:
------------------
{payload.message}
------------------
"""

    return analyze_vendor_text(
        context
    )


# =========================================================
# CATALOG ANALYSIS
# =========================================================

@app.post("/api/catalog/analyze")
async def analyze_catalog(
    category: str = Form(...),

    file: UploadFile = File(...),

    business_name: str | None = Form(
        default=None
    ),

    marketplace_id: int | None = Form(
        default=None
    ),
) -> dict:

    try:
        category = normalize_category(
            category
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    filename = (
        file.filename
        or "upload"
    )

    if not filename.lower().endswith(
        (
            ".csv",
            ".xlsx",
            ".xls",
        )
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Catalog upload currently "
                "supports CSV, XLS, and XLSX."
            ),
        )

    content = await file.read()

    try:
        products, mapping = (
            parse_uploaded_catalog(
                content,
                filename,
            )
        )

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Could not parse catalog: {exc}"
            ),
        ) from exc

    if marketplace_id is not None:
        saved = get_schema(
            marketplace_id,
            category,
        )

    else:
        saved = None

    if saved:
        required_fields = (
            saved["required_fields"]
        )

    else:
        required_fields = (
            get_market_schema(
                category
            )["required"]
        )

    vendor_context = {}

    if business_name:
        vendor_context[
            "Business Name"
        ] = business_name

    result = evaluate_catalog(
        products=products,
        required_fields=required_fields,
        vendor_context=vendor_context,
    )

    return {
        "file_name": filename,
        "category": category,
        "column_mapping": mapping,
        "recognized_columns": len(mapping),
        **result,
    }