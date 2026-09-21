"""Small SQLite persistence layer for local VendorMender development."""

from __future__ import annotations

from pathlib import Path
import json
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "vendormender.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS marketplaces (
                marketplace_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS schemas (
                schema_id INTEGER PRIMARY KEY AUTOINCREMENT,
                marketplace_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                required_fields TEXT NOT NULL,
                optional_fields TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(marketplace_id, category),
                FOREIGN KEY(marketplace_id) REFERENCES marketplaces(marketplace_id)
            );

            CREATE TABLE IF NOT EXISTS vendors (
                vendor_id INTEGER PRIMARY KEY AUTOINCREMENT,
                marketplace_id INTEGER NOT NULL,
                business_name TEXT NOT NULL,
                location TEXT,
                contact_information TEXT,
                social_media TEXT,
                business_description TEXT,
                brand_story TEXT,
                status TEXT DEFAULT 'Needs Information',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(marketplace_id) REFERENCES marketplaces(marketplace_id)
            );
            """
        )


def create_marketplace(name: str, description: str | None = None) -> int:
    init_db()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO marketplaces(name, description) VALUES (?, ?)",
            (name.strip(), description),
        )
        if cursor.lastrowid:
            return int(cursor.lastrowid)
        row = conn.execute(
            "SELECT marketplace_id FROM marketplaces WHERE lower(name) = lower(?)",
            (name.strip(),),
        ).fetchone()
        return int(row["marketplace_id"])


def get_marketplaces() -> list[dict]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT marketplace_id, name, description, created_at FROM marketplaces ORDER BY name"
        ).fetchall()
    return [dict(row) for row in rows]


def save_schema(
    marketplace_id: int,
    category: str,
    required_fields: list[str],
    optional_fields: list[str],
) -> int:
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO schemas(marketplace_id, category, required_fields, optional_fields)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(marketplace_id, category) DO UPDATE SET
                required_fields = excluded.required_fields,
                optional_fields = excluded.optional_fields,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                marketplace_id,
                category.upper(),
                json.dumps(required_fields),
                json.dumps(optional_fields),
            ),
        )
        row = conn.execute(
            "SELECT schema_id FROM schemas WHERE marketplace_id = ? AND category = ?",
            (marketplace_id, category.upper()),
        ).fetchone()
        return int(row["schema_id"])


def get_schema(marketplace_id: int, category: str) -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT schema_id, marketplace_id, category, required_fields, optional_fields, updated_at
            FROM schemas
            WHERE marketplace_id = ? AND category = ?
            """,
            (marketplace_id, category.upper()),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["required_fields"] = json.loads(result["required_fields"])
    result["optional_fields"] = json.loads(result["optional_fields"])
    return result


def create_vendor(
    marketplace_id: int,
    business_name: str,
    location: str | None = None,
    contact_information: str | None = None,
    social_media: str | None = None,
    business_description: str | None = None,
    brand_story: str | None = None,
    status: str = "Needs Information",
) -> int:
    init_db()
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO vendors(
                marketplace_id,
                business_name,
                location,
                contact_information,
                social_media,
                business_description,
                brand_story,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                marketplace_id,
                business_name,
                location,
                contact_information,
                social_media,
                business_description,
                brand_story,
                status,
            ),
        )
        return int(cursor.lastrowid)


def get_vendors(marketplace_id: int | None = None) -> list[dict]:
    init_db()
    with _connect() as conn:
        if marketplace_id is None:
            rows = conn.execute(
                "SELECT * FROM vendors ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM vendors WHERE marketplace_id = ? ORDER BY created_at DESC",
                (marketplace_id,),
            ).fetchall()
    return [dict(row) for row in rows]
