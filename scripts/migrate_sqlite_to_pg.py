#!/usr/bin/env python3
"""One-time migration script: SQLite (ProfitLens v2) → PostgreSQL (ProfitLens v3).

Usage:
    python scripts/migrate_sqlite_to_pg.py \
        --sqlite-path /path/to/profitlens.db \
        --pg-url "postgresql://profitlens:password@localhost:5432/profitlens"

This script reads all tables from the SQLite database and inserts them into
the PostgreSQL database. It preserves all data including encrypted fields
(enc:v1: prefix is kept as-is).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import psycopg2
import psycopg2.extras


# Table migration order (respects foreign key dependencies)
MIGRATION_ORDER = [
    "users",
    "license_keys",
    "app_config",
    "store_bindings",
    "bid_engine_state",
    "bid_products",
    "bid_log",
    "auto_price_products",
    "product_annotations",
    "cnexpress_accounts",
    "cnexpress_fba_orders",
    "cnexpress_wallet_entries",
    "extension_auth_tokens",
    "extension_actions",
    "takealot_webhook_configs",
    "takealot_webhook_deliveries",
    "crawl_jobs",
    "site_notifications",
    "library_products",
    "library_products_quarantine",
    "auto_selection_products",
    "temp_scrape_products",
    "selection_memory",
    "category_learning_rules",
    "listing_jobs",
    "dropship_jobs",
]


def get_sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    """Get all table names from SQLite database."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return [row[0] for row in cursor.fetchall()]


def get_table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Get column names for a table."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cursor.fetchall()]


def migrate_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn,
    table: str,
    batch_size: int = 1000,
) -> int:
    """Migrate a single table from SQLite to PostgreSQL. Returns row count."""
    columns = get_table_columns(sqlite_conn, table)
    if not columns:
        print(f"  [SKIP] {table}: no columns found")
        return 0

    # Check if table exists in PostgreSQL
    pg_cursor = pg_conn.cursor()
    pg_cursor.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
        (table,),
    )
    if not pg_cursor.fetchone()[0]:
        print(f"  [SKIP] {table}: not found in PostgreSQL (run Alembic migrations first)")
        return 0

    # Get PG columns to find intersection
    pg_cursor.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table,),
    )
    pg_columns = {row[0] for row in pg_cursor.fetchall()}
    common_columns = [c for c in columns if c in pg_columns]

    if not common_columns:
        print(f"  [SKIP] {table}: no common columns between SQLite and PostgreSQL")
        return 0

    # Read from SQLite
    col_list = ", ".join(common_columns)
    sqlite_cursor = sqlite_conn.execute(f"SELECT {col_list} FROM {table}")
    rows = sqlite_cursor.fetchall()

    if not rows:
        print(f"  [OK]   {table}: 0 rows (empty)")
        return 0

    # Insert into PostgreSQL in batches
    placeholders = ", ".join(["%s"] * len(common_columns))
    insert_sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        pg_cursor.executemany(insert_sql, batch)
        total += len(batch)

    pg_conn.commit()

    # Reset sequence for tables with auto-increment
    if "id" in common_columns:
        try:
            pg_cursor.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)"
            )
            pg_conn.commit()
        except Exception:
            pg_conn.rollback()

    print(f"  [OK]   {table}: {total} rows migrated ({len(common_columns)} columns)")
    return total


def migrate_additional_sqlite(
    sqlite_path: str,
    pg_conn,
    label: str,
) -> None:
    """Migrate tables from additional SQLite databases (e.g., product_library.db)."""
    path = Path(sqlite_path)
    if not path.exists():
        print(f"\n[SKIP] {label}: file not found at {sqlite_path}")
        return

    print(f"\n--- Migrating {label}: {path.name} ---")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    tables = get_sqlite_tables(conn)
    for table in tables:
        try:
            migrate_table(conn, pg_conn, table)
        except Exception as e:
            print(f"  [ERR]  {table}: {e}")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Migrate ProfitLens SQLite to PostgreSQL")
    parser.add_argument("--sqlite-path", required=True, help="Path to profitlens.db")
    parser.add_argument("--pg-url", required=True, help="PostgreSQL connection URL")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch size for inserts")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.exists():
        print(f"Error: SQLite file not found: {sqlite_path}")
        sys.exit(1)

    print(f"SQLite source: {sqlite_path} ({sqlite_path.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"PostgreSQL target: {args.pg_url.split('@')[1] if '@' in args.pg_url else args.pg_url}")
    print()

    # Connect to SQLite
    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row

    # Connect to PostgreSQL
    pg_conn = psycopg2.connect(args.pg_url)

    start = time.time()
    total_rows = 0
    errors = []

    print("--- Migrating main database ---")
    available_tables = set(get_sqlite_tables(sqlite_conn))

    for table in MIGRATION_ORDER:
        if table not in available_tables:
            print(f"  [SKIP] {table}: not in SQLite")
            continue
        try:
            count = migrate_table(sqlite_conn, pg_conn, table, args.batch_size)
            total_rows += count
        except Exception as e:
            errors.append((table, str(e)))
            print(f"  [ERR]  {table}: {e}")
            pg_conn.rollback()

    # Migrate any tables not in our explicit order
    remaining = available_tables - set(MIGRATION_ORDER) - {"sqlite_sequence"}
    if remaining:
        print("\n--- Migrating additional tables ---")
        for table in sorted(remaining):
            try:
                count = migrate_table(sqlite_conn, pg_conn, table, args.batch_size)
                total_rows += count
            except Exception as e:
                errors.append((table, str(e)))
                print(f"  [ERR]  {table}: {e}")
                pg_conn.rollback()

    sqlite_conn.close()

    # Try to migrate product_library.db if it exists alongside
    data_dir = sqlite_path.parent
    for extra_db in ["product_library.db", "amazon_products.db"]:
        extra_path = data_dir / extra_db
        if extra_path.exists():
            migrate_additional_sqlite(str(extra_path), pg_conn, extra_db)

    pg_conn.close()

    elapsed = time.time() - start
    print(f"\n{'='*50}")
    print(f"Migration complete in {elapsed:.1f}s")
    print(f"Total rows migrated: {total_rows}")
    if errors:
        print(f"Errors: {len(errors)}")
        for table, err in errors:
            print(f"  - {table}: {err}")
    else:
        print("No errors!")


if __name__ == "__main__":
    main()
