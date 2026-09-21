"""FastAPI entry point for VendorMender."""

from __future__ import annotations

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


app = FastAPI(
    title="VendorMender API",
    version="1.0.0",
    description="Adaptive marketplace vendor onboarding backend.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()


class MessageAnalyzeRequest(BaseModel):
    category: str
    message: str = Field(min_length=1)
    marketplace_name: str = "LOCALSTYLE"
    marketplace_description: str | None = None
    required_fields: list[str] | None = None
    optional_fields: list[str] | None = None


class MarketplaceCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None


class SchemaSaveRequest(BaseModel):
    marketplace_id: int
    category: str
    required_fields: list[str]
    optional_fields: list[str] = []


class VendorCreateRequest(BaseModel):
    marketplace_id: int
    business_name: str = Field(min_length=1)
    location: str | None = None
    contact_information: str | None = None
    social_media: str | None = None
    business_description: str | None = None
    brand_story: str | None = None
    status: str = "Needs Information"


@app.get("/")
def root() -> dict:
    return {
        "name": "VendorMender API",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/categories")
def categories() -> dict:
    return MARKETS


@app.get("/api/schema/{category}")
def category_schema(category: str) -> dict:
    try:
        normalized = normalize_category(category)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"category": normalized, **get_market_schema(normalized)}


@app.post("/api/marketplaces")
def add_marketplace(payload: MarketplaceCreateRequest) -> dict:
    marketplace_id = create_marketplace(payload.name, payload.description)
    return {"marketplace_id": marketplace_id}


@app.get("/api/marketplaces")
def list_marketplaces() -> list[dict]:
    return get_marketplaces()


@app.put("/api/schema")
def persist_schema(payload: SchemaSaveRequest) -> dict:
    try:
        category = normalize_category(payload.category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not payload.required_fields:
        raise HTTPException(status_code=400, detail="At least one required field is needed.")

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


@app.get("/api/schema/{marketplace_id}/{category}")
def saved_schema(marketplace_id: int, category: str) -> dict:
    schema = get_schema(marketplace_id, category)
    if not schema:
        raise HTTPException(status_code=404, detail="Saved schema not found.")
    return schema


@app.post("/api/vendors")
def add_vendor(payload: VendorCreateRequest) -> dict:
    vendor_id = create_vendor(**payload.model_dump())
    return {"vendor_id": vendor_id}


@app.get("/api/vendors")
def list_vendors(marketplace_id: int | None = None) -> list[dict]:
    return get_vendors(marketplace_id)


@app.get("/api/demo")
def demo() -> dict:
    result = run_demo()
    if not result["demo_integrity_ok"]:
        raise HTTPException(
            status_code=500,
            detail="Demo integrity check failed. The workbook no longer matches the expected fixture.",
        )
    return result


@app.post("/api/message/analyze")
def analyze_message(payload: MessageAnalyzeRequest) -> dict:
    try:
        category = normalize_category(payload.category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    default_schema = get_market_schema(category)
    required = payload.required_fields or default_schema["required"]
    optional = payload.optional_fields if payload.optional_fields is not None else default_schema["optional"]
    description = payload.marketplace_description or default_schema["description"]

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

VENDOR ARRIVAL METHOD:
MESSAGE / EMAIL / DM / WHATSAPP / NOTES

VENDOR SUBMISSION:
------------------
{payload.message}
------------------
"""
    return analyze_vendor_text(context)


@app.post("/api/catalog/analyze")
async def analyze_catalog(
    category: str = Form(...),
    file: UploadFile = File(...),
    business_name: str | None = Form(default=None),
    marketplace_id: int | None = Form(default=None),
) -> dict:
    try:
        category = normalize_category(category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    filename = file.filename or "upload"
    if not filename.lower().endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(
            status_code=400,
            detail="Catalog upload currently supports CSV, XLS, and XLSX.",
        )

    content = await file.read()
    try:
        products, mapping = parse_uploaded_catalog(content, filename)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse catalog: {exc}") from exc

    if marketplace_id is not None:
        saved = get_schema(marketplace_id, category)
    else:
        saved = None

    required_fields = (
        saved["required_fields"]
        if saved
        else get_market_schema(category)["required"]
    )

    vendor_context = {"Business Name": business_name} if business_name else {}
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
