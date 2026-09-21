# VendorMender

VendorMender is an adaptive marketplace vendor-onboarding system. The new architecture separates the Python business logic/API from the future Lovable/React frontend.

## Folder structure

```text
VendorMender/
├── backend/
│   ├── __init__.py
│   ├── main.py
│   ├── schemas.py
│   ├── readiness.py
│   ├── catalog_parser.py
│   ├── demo.py
│   ├── ai_engine.py
│   ├── database.py
│   └── requirements.txt
├── data/
│   └── VendorMender_Demo_Catalog_20_SKUs.xlsx
├── assets/
│   ├── apparel.jpg
│   ├── tableware.jpg
│   ├── jewelry.jpg
│   └── footwear.jpg
├── legacy/
│   └── app.py
├── .env.example
├── .gitignore
└── README.md
```

`legacy/app.py` is the last Streamlit prototype and is kept only as a reference. The new backend entry point is `backend/main.py`.

## 1. Create a clean virtual environment

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

## 2. Run the API

Stay in the project root and run:

```bash
uvicorn backend.main:app --reload
```

Open:

- API: http://127.0.0.1:8000
- Interactive docs: http://127.0.0.1:8000/docs

## 3. Test the deterministic demo

In `/docs`, execute:

```text
GET /api/demo
```

Expected result:

- 20 SKUs processed
- 14 Publish Ready
- 6 Needs Attention
- average readiness 97%

Exact expected gaps:

- VM-004 → Care Instructions
- VM-007 → Product Images
- VM-010 → Fit
- VM-012 → Fabric
- VM-015 → Size
- VM-018 → Price

The response includes `demo_integrity_ok: true` when the workbook matches the expected fixture.

## 4. Important files

- `backend/main.py` — FastAPI routes; this is the new backend entry point.
- `backend/schemas.py` — category requirements and defaults.
- `backend/readiness.py` — authoritative deterministic gap/readiness logic.
- `backend/catalog_parser.py` — CSV/XLS/XLSX loading and column mapping.
- `backend/demo.py` — one-click 20-SKU demo.
- `backend/ai_engine.py` — text/file extraction interface. This rebuild uses a conservative deterministic extractor so the backend works without an external AI key. You can later replace the extraction internals with an LLM without changing the frontend API contract.
- `backend/database.py` — local SQLite persistence for development.
- `legacy/app.py` — preserved Streamlit prototype. Do not use it as the new backend entry point.

## 5. Frontend later

The Lovable/React frontend should call this backend using an environment variable such as:

```text
VITE_API_URL=http://127.0.0.1:8000
```

Typical flow:

```text
Lovable / React
      ↓ HTTPS JSON
FastAPI (backend/main.py)
      ↓
readiness / catalog parser / AI interface / database
```

Do not move authoritative readiness or publish-eligibility logic into browser-only code.
