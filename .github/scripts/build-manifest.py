#!/usr/bin/env python3
"""Count the rows of every table in every release file and write MANIFEST-<TAG>.json.

Needs: duckdb, pyarrow (the export venv has both).
Env:   BASENAME, TAG.
Reads: pg-counts.json (Postgres row counts from the export snapshot), dump-counts.tsv (rows per
       table inside the .dump), and the files themselves.
Writes: MANIFEST-<TAG>.json and manifest-summary.md (appended to the release notes).

Checks
  Same snapshot as Postgres, so they must match exactly (the workflow fails if not):
      Parquet, SQLite, DuckDB
  Taken a moment earlier, so a difference only warns (the database may have changed in between):
      the .dump
"""
import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

BASENAME = os.environ["BASENAME"]
TAG = os.environ["TAG"]
SCHEMA = "public"
HARD = ("parquet", "sqlite", "duckdb")
SOFT = ("dump",)


def q(ident):
    return '"' + ident.replace('"', '""') + '"'


def main():
    pg = json.loads(Path("pg-counts.json").read_text())
    tables = pg["tables"]

    dump_counts = {}
    f = Path("dump-counts.tsv")
    if f.exists():
        for line in f.read_text().splitlines():
            name, _, n = line.rpartition("\t")
            dump_counts[name] = int(n)

    lite = sqlite3.connect(f"{BASENAME}.sqlite")
    duck = duckdb.connect(f"{BASENAME}.duckdb", read_only=True)

    report, hard_bad, soft_bad = {}, [], []
    for table, expected in sorted(tables.items()):
        row = {"postgres": expected}
        row["dump"] = dump_counts.get(f"{SCHEMA}.{table}")
        pf = Path(f"{BASENAME}.{SCHEMA}.{table}.parquet")
        row["parquet"] = pq.ParquetFile(pf).metadata.num_rows if pf.exists() else None
        try:
            row["sqlite"] = lite.execute(f"SELECT count(*) FROM {q(table)}").fetchone()[0]
        except sqlite3.Error:
            row["sqlite"] = None
        try:
            row["duckdb"] = duck.execute(f"SELECT count(*) FROM {q(SCHEMA)}.{q(table)}").fetchone()[0]
        except duckdb.Error:
            row["duckdb"] = None

        bad_hard = [k for k in HARD if row[k] != expected]
        bad_soft = [k for k in SOFT if row[k] != expected]
        row["match"] = not bad_hard and not bad_soft
        report[table] = row
        if bad_hard:
            hard_bad.append((table, {k: row[k] for k in bad_hard}, expected))
        if bad_soft:
            soft_bad.append((table, {k: row[k] for k in bad_soft}, expected))

    manifest = {
        "tag": TAG,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "postgres_snapshot_time": pg["snapshot_time"],
        "schema": SCHEMA,
        "total_rows": sum(tables.values()),
        "all_match": not hard_bad and not soft_bad,
        "notes": [
            "postgres, parquet, sqlite and duckdb come from one repeatable-read snapshot and must match exactly.",
            "dump is taken a little earlier; a small difference means the database changed in between.",
            "null means the table was not found in that file.",
        ],
        "tables": report,
    }
    Path(f"MANIFEST-{TAG}.json").write_text(json.dumps(manifest, indent=2) + "\n")

    # Markdown summary, appended to the release notes by the workflow
    cols = [("postgres", "Postgres"), ("dump", ".dump"), ("parquet", "Parquet"),
            ("sqlite", "SQLite"), ("duckdb", "DuckDB")]

    def cell(row, k):
        v = row[k]
        if v is None:
            return "⚠️ missing"
        return f"{v:,}" if k == "postgres" or v == row["postgres"] else f"⚠️ {v:,}"

    lines = ["### Row counts", ""]
    if manifest["all_match"]:
        lines.append(f"✅ Every file matches Postgres: {manifest['total_rows']:,} rows across {len(tables)} tables.")
    else:
        names = ", ".join(f"`{k}`" for k, r in report.items() if not r["match"])
        lines.append(f"⚠️ Differences in {names}. Parquet, SQLite and DuckDB come from one snapshot and match "
                     "Postgres. The `.dump` is taken a little earlier, so a small difference usually means "
                     "the database changed in between.")
    lines += ["", "| Table | " + " | ".join(label for _, label in cols) + " |",
              "|---|" + "---:|" * len(cols)]
    for table, row in report.items():
        lines.append(f"| `{table}` | " + " | ".join(cell(row, k) for k, _ in cols) + " |")
    lines += ["", f"Details: `MANIFEST-{TAG}.json`.", ""]
    Path("manifest-summary.md").write_text("\n".join(lines))

    for table, bad, expected in soft_bad:
        print(f"::warning::{table}: expected {expected} rows from the snapshot, got {bad} "
              "(taken earlier, the database may have changed)")
    for table, bad, expected in hard_bad:
        print(f"::error::{table}: expected {expected} rows, got {bad}", file=sys.stderr)
    print(f"Manifest: {len(tables)} table(s), {manifest['total_rows']} rows, all_match={manifest['all_match']}")
    if hard_bad:
        sys.exit("Row counts differ from the Postgres snapshot. Not releasing.")


if __name__ == "__main__":
    main()
