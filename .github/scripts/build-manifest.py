#!/usr/bin/env python3
"""Count the rows of every table in every release file and write MANIFEST-<TAG>.json.

Needs: duckdb, pyarrow (the export venv has both).
Env:   BASENAME, TAG.
Reads: pg-counts.json (Postgres row counts from the export snapshot), dump-counts.tsv (rows per
       table inside the .dump), and the files themselves.

Checks
  Same snapshot as Postgres, so they must match exactly (the workflow fails if not):
      Parquet, SQLite, DuckDB
  Taken a moment later, so a difference only warns (the database may have changed in between):
      the .dump / SQL files, CSV, TSV, JSON Lines, JSON
"""
import csv
import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

csv.field_size_limit(sys.maxsize)

BASENAME = os.environ["BASENAME"]
TAG = os.environ["TAG"]
HARD = ("parquet", "sqlite", "duckdb")
SOFT = ("dump_sql", "csv", "tsv", "jsonl", "json")


def q(ident):
    return '"' + ident.replace('"', '""') + '"'


def file_rows(path, kind):
    """Rows in one plain per-table file. Returns None if the file is missing."""
    if not path.exists():
        return None
    if kind == "jsonl":
        with open(path, "rb") as raw:
            return sum(1 for line in raw if line.strip())
    if kind == "json":
        # A JSON array with one object per line: every line except the brackets is a row.
        with open(path, "rb") as raw:
            return sum(1 for line in raw if line.strip() not in (b"", b"[", b"]"))
    with open(path, encoding="utf-8", newline="") as text:
        reader = csv.reader(text, delimiter="\t" if kind == "tsv" else ",")
        n = sum(1 for _ in reader)
    return max(n - 1, 0)  # minus the header row


def main():
    pg = json.loads(Path("pg-counts.json").read_text())
    tables = pg["tables"]
    schemas = pg["schemas"]

    dump_counts = {}
    f = Path("dump-counts.tsv")
    if f.exists():
        for line in f.read_text().splitlines():
            name, _, n = line.rpartition("\t")
            dump_counts[name] = int(n)

    lite = sqlite3.connect(f"{BASENAME}.sqlite")
    duck = duckdb.connect(f"{BASENAME}.duckdb", read_only=True)

    report, hard_bad, soft_bad = {}, [], []
    for key, expected in sorted(tables.items()):
        schema, table = key.split(".", 1)
        row = {"postgres": expected}
        row["dump_sql"] = dump_counts.get(key)
        pf = Path(f"{BASENAME}.{key}.parquet")
        row["parquet"] = pq.ParquetFile(pf).metadata.num_rows if pf.exists() else None
        lname = table if len(schemas) == 1 else f"{schema}_{table}"
        try:
            row["sqlite"] = lite.execute(f"SELECT count(*) FROM {q(lname)}").fetchone()[0]
        except sqlite3.Error:
            row["sqlite"] = None
        try:
            row["duckdb"] = duck.execute(f"SELECT count(*) FROM {q(schema)}.{q(table)}").fetchone()[0]
        except duckdb.Error:
            row["duckdb"] = None
        for kind in ("csv", "tsv", "jsonl", "json"):
            row[kind] = file_rows(Path(f"{BASENAME}.{key}.{kind}"), kind)

        bad_hard = [k for k in HARD if row[k] != expected]
        bad_soft = [k for k in SOFT if row[k] != expected]
        row["match"] = not bad_hard and not bad_soft
        report[key] = row
        if bad_hard:
            hard_bad.append((key, {k: row[k] for k in bad_hard}, expected))
        if bad_soft:
            soft_bad.append((key, {k: row[k] for k in bad_soft}, expected))

    manifest = {
        "tag": TAG,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "postgres_snapshot_time": pg["snapshot_time"],
        "schemas": schemas,
        "total_rows": sum(tables.values()),
        "all_match": not hard_bad and not soft_bad,
        "notes": [
            "postgres, parquet, sqlite and duckdb come from one repeatable-read snapshot and must match exactly.",
            "dump_sql, csv, tsv, jsonl and json are taken a little later; a small difference means the database changed in between.",
            "null means the table was not found in that file.",
        ],
        "tables": report,
    }
    Path(f"MANIFEST-{TAG}.json").write_text(json.dumps(manifest, indent=2) + "\n")

    # Markdown summary, appended to the release notes by the workflow
    cols = [("postgres", "Postgres"), ("dump_sql", ".dump"), ("parquet", "Parquet"), ("sqlite", "SQLite"),
            ("duckdb", "DuckDB"), ("csv", "CSV"), ("tsv", "TSV"), ("jsonl", "JSONL"), ("json", "JSON")]

    def cell(row, k):
        v = row[k]
        if v is None:
            return "⚠️ missing"
        return f"{v:,}" if k == "postgres" or v == row["postgres"] else f"⚠️ {v:,}"

    lines = ["### Check", ""]
    if manifest["all_match"]:
        lines.append(f"✅ All files match Postgres: {manifest['total_rows']:,} rows across {len(tables)} table(s).")
    else:
        names = ", ".join(f"`{k}`" for k, r in report.items() if not r["match"])
        lines.append(f"⚠️ Differences found in {names}. Postgres, Parquet, SQLite and DuckDB are from one "
                     "snapshot and match. The other files are taken a little later, so a small difference "
                     "usually means the database changed in between.")
    lines += ["", "| Table | " + " | ".join(label for _, label in cols) + " |",
              "|---|" + "---:|" * len(cols)]
    for key, row in report.items():
        lines.append(f"| `{key}` | " + " | ".join(cell(row, k) for k, _ in cols) + " |")
    lines += ["", f"Row counts only. Details: `MANIFEST-{TAG}.json`.", ""]
    Path("manifest-summary.md").write_text("\n".join(lines))

    for key, bad, expected in soft_bad:
        print(f"::warning::{key}: expected {expected} rows from the snapshot, got {bad} "
              "(taken later, the database may have changed)")
    for key, bad, expected in hard_bad:
        print(f"::error::{key}: expected {expected} rows, got {bad}", file=sys.stderr)
    print(f"Manifest: {len(tables)} table(s), {manifest['total_rows']} rows, all_match={manifest['all_match']}")
    if hard_bad:
        sys.exit("Row counts differ from the Postgres snapshot. Not releasing.")


if __name__ == "__main__":
    main()
