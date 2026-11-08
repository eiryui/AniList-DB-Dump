#!/usr/bin/env python3
"""Export the dumped schemas to Parquet, SQLite and DuckDB.

Needs: psycopg[binary], pyarrow, duckdb.
Env:   DATABASE_URL, DUMP_SCHEMAS (comma separated, default "public"), BASENAME.
Writes: <BASENAME>.sqlite, <BASENAME>.duckdb, <BASENAME>.<schema>.<table>.parquet (one per table,
        uncompressed, no zip), pg-counts.json

All tables are read in ONE repeatable-read, read-only transaction, so every file
is a consistent snapshot of the same moment. Column types are mapped from
Postgres to Arrow. Anything without a clean mapping (json, jsonb, uuid, time,
interval, enums, ranges ...) is exported as its Postgres text form.
"""
import datetime
import decimal
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import duckdb
import psycopg
import pyarrow as pa
import pyarrow.parquet as pq

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
NAME = re.compile(r"^[A-Za-z0-9_]+$")
BATCH = 50_000

SIMPLE = {
    "int2": pa.int16(), "int4": pa.int32(), "int8": pa.int64(),
    "float4": pa.float32(), "float8": pa.float64(), "bool": pa.bool_(),
    "text": pa.string(), "varchar": pa.string(), "bpchar": pa.string(), "name": pa.string(),
    "date": pa.date32(), "timestamp": pa.timestamp("us"),
    "timestamptz": pa.timestamp("us", tz="UTC"), "bytea": pa.binary(),
}


def q(ident):
    return '"' + ident.replace('"', '""') + '"'


def column_plan(cols, force_text=False):
    """cols: rows of (name, udt_name, precision, scale). Returns (select_list, arrow_fields)."""
    exprs, fields = [], []
    for name, udt, prec, scale in cols:
        col = q(name)
        typ = None
        expr = f"{col}::text"
        if not force_text:
            if udt in SIMPLE:
                typ, expr = SIMPLE[udt], col
            elif udt == "numeric" and prec and prec <= 38:
                typ, expr = pa.decimal128(prec, scale or 0), col
            elif udt.startswith("_") and udt[1:] in SIMPLE and udt[1:] not in ("bytea",):
                typ, expr = pa.list_(SIMPLE[udt[1:]]), col
        if typ is None:
            typ = pa.string()
        exprs.append(f"{expr} AS {col}")
        fields.append(pa.field(name, typ))
    return ", ".join(exprs), fields


def read_table(conn, schema, table, cols):
    """Return a pyarrow Table. Retries with every column as text if a type does not convert."""
    for force_text in (False, True):
        select_list, fields = column_plan(cols, force_text)
        schema_arrow = pa.schema(fields)
        try:
            batches = []
            with conn.cursor(name=f"c_{os.getpid()}_{force_text}") as cur:
                cur.itersize = BATCH
                cur.execute(f"SELECT {select_list} FROM {q(schema)}.{q(table)}")
                while True:
                    rows = cur.fetchmany(BATCH)
                    if not rows:
                        break
                    arrays = [pa.array([r[i] for r in rows], type=f.type) for i, f in enumerate(fields)]
                    batches.append(pa.RecordBatch.from_arrays(arrays, schema=schema_arrow))
            return pa.Table.from_batches(batches, schema=schema_arrow)
        except Exception as exc:  # noqa: BLE001
            if force_text:
                raise
            print(f"::warning::{schema}.{table}: typed export failed ({exc}); retrying all columns as text")
    raise RuntimeError("unreachable")


def sqlite_value(v):
    if v is None or isinstance(v, (int, float, str, bytes)):
        return v
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    return json.dumps(v, default=str)


def sqlite_type(t):
    if pa.types.is_boolean(t) or pa.types.is_integer(t):
        return "INTEGER"
    if pa.types.is_floating(t):
        return "REAL"
    if pa.types.is_binary(t):
        return "BLOB"
    return "TEXT"


def main():
    url = os.environ["DATABASE_URL"]
    schemas = [s.strip() for s in os.environ.get("DUMP_SCHEMAS", "public").split(",") if s.strip()]
    base = os.environ["BASENAME"]
    for s in schemas:
        if not IDENT.match(s):
            sys.exit(f"::error::Invalid schema name: {s}")

    out = Path(".")
    sqlite_path, duck_path = out / f"{base}.sqlite", out / f"{base}.duckdb"
    for p in (sqlite_path, duck_path):
        p.unlink(missing_ok=True)

    lite = sqlite3.connect(sqlite_path)
    duck = duckdb.connect(str(duck_path))
    conn = psycopg.connect(url, autocommit=False)
    conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")

    snapshot_time = conn.execute("SELECT now()::text").fetchone()[0]
    pg_counts = {}
    count = 0
    for schema in schemas:
        duck.execute(f"CREATE SCHEMA IF NOT EXISTS {q(schema)}")
        tables = [r[0] for r in conn.execute(
            "SELECT table_name::text FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY 1", (schema,))]
        for table in tables:
            if not NAME.match(table):
                print(f"::warning::Skipping {schema}.{table} (unsupported characters in table name)")
                continue
            cols = conn.execute(
                "SELECT column_name::text, udt_name::text, numeric_precision::int, numeric_scale::int "
                "FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
                "ORDER BY ordinal_position", (schema, table)).fetchall()
            # Row count inside the same repeatable-read snapshot, for MANIFEST.json
            pg_counts[f"{schema}.{table}"] = conn.execute(
                f"SELECT count(*) FROM {q(schema)}.{q(table)}").fetchone()[0]
            tbl = read_table(conn, schema, table, cols)

            # Parquet: plain file, no compression
            pq.write_table(tbl, out / f"{base}.{schema}.{table}.parquet", compression="none")

            # DuckDB (keeps real schemas)
            duck.register("src", tbl)
            duck.execute(f"CREATE TABLE {q(schema)}.{q(table)} AS SELECT * FROM src")
            duck.unregister("src")

            # SQLite (no schemas: plain table name, or schema_table when several schemas)
            lname = table if len(schemas) == 1 else f"{schema}_{table}"
            ddl = ", ".join(f"{q(f.name)} {sqlite_type(f.type)}" for f in tbl.schema)
            lite.execute(f"DROP TABLE IF EXISTS {q(lname)}")
            lite.execute(f"CREATE TABLE {q(lname)} ({ddl})")
            marks = ", ".join("?" for _ in tbl.schema)
            for batch in tbl.to_batches(BATCH):
                cols_py = [c.to_pylist() for c in batch.columns]
                lite.executemany(
                    f"INSERT INTO {q(lname)} VALUES ({marks})",
                    ([sqlite_value(v) for v in row] for row in zip(*cols_py)))
            lite.commit()

            count += 1
            print(f"{schema}.{table}: {tbl.num_rows} rows")

    conn.rollback()
    conn.close()
    lite.close()
    duck.close()
    if count == 0:
        sys.exit("::error::No tables found for Parquet/SQLite/DuckDB export.")

    (out / "pg-counts.json").write_text(json.dumps(
        {"snapshot_time": snapshot_time, "schemas": schemas, "tables": pg_counts}, indent=2))
    print(f"Exported {count} table(s).")


if __name__ == "__main__":
    main()
