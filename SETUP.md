# AniList-DB-Dump

Weekly and manual snapshots of AniList data, published as GitHub Releases. Download one, load it into the database you already use, and optionally serve it as a JSON API with AniServe.

## Quick start

| I want to... | Do this |
|---|---|
| Look at the data in a spreadsheet, pandas or a script | Download a [CSV, JSON, Parquet or SQLite file](#pick-a-file) |
| Run it in a database | [Deploy it](#deploy-it) to PostgreSQL, SQLite or DuckDB |
| Get a JSON API with a web UI on top | [Serve it with AniServe](#serve-it-as-a-json-api) |

Open the repo's **Releases** page. Weekly dumps are tagged `weekly-YYYY-MM-DD`, manual ones `manual-YYYY-MM-DD-HHMM`. The newest release is at the top, and its notes show when it was made and when the next scheduled dump is due. To look at the structure first, `sample/sample.sql` in the repo has the table definition and the 20 most popular rows.

## Pick a file

Every release has the same data in many formats. Pick by what you will load it into.

| File | Use it when |
|---|---|
| `*.dump` | You have PostgreSQL and want the fastest, most flexible restore (`pg_restore`). Pick this by default. Supports restoring single tables |
| `*.sql` | You want plain SQL for `psql` (`psql -d anilist -f FILE.sql`), or to read or process it with other tools |
| `*.sql.gz` | The same SQL, gzipped. Smaller download. `gunzip -c FILE.sql.gz \| psql anilist` |
| `*.tar` | You specifically need pg_dump's tar format. Same content as `.dump`, bigger |
| `*-schema.sql` | You only want the table structure, no data |
| `*.sqlite` | You want one file you can open directly (DB Browser for SQLite, Python `sqlite3`). Arrays and JSON are stored as JSON text, dates as ISO text. Data only |
| `*.duckdb` | Same idea as SQLite, for analytics. Open with the DuckDB CLI or Python. Keeps real types. Data only |
| `*.parquet` | You analyse the data in pandas, DuckDB, Spark or similar. One `<release>.schema.table.parquet` file per table, with real column types, uncompressed. JSON columns are stored as JSON text. Data only |
| `*.csv` | Spreadsheets, pandas, or any tool that reads CSV. One `<release>.schema.table.csv` file per table with a header row. Data only. Nested JSON columns are quoted JSON strings |
| `*.tsv` | Same as the CSV files but tab separated |
| `*.json` | JSON for scripts or apps. One `<release>.schema.table.json` file per table: a JSON array of row objects, one object per line, nested fields kept as real JSON. Data only |
| `*.jsonl` | The same rows as JSON Lines (one JSON object per line, no surrounding array). Easier to stream large tables. Data only |
| `MANIFEST-<tag>.json` | Check a file is complete. Row counts of every table in Postgres and in each file, from the same run, plus an overall `all_match` flag |
| `SHA256SUMS-<tag>.txt` | Verify a download: `sha256sum -c SHA256SUMS-<tag>.txt` |

## Deploy it

Pick the row that matches where you want the data to live. Each links to the recipe below.

| Where | Release file | Connection string for AniServe |
|---|---|---|
| [Local PostgreSQL or Docker](#postgresql-local-or-docker) | `.dump` (or `.sql`) | `postgresql://user:pass@localhost:5432/anilist` |
| [Hosted PostgreSQL](#hosted-postgresql) (Supabase, Neon, Railway, Render, ...) | `.dump` (or `.sql`) | the service's string plus `?sslmode=require` |
| [SQLite](#sqlite-no-server) | `.sqlite` | `sqlite:///data/anilist.sqlite` |
| [DuckDB](#duckdb-and-parquet) | `.duckdb` | `duckdb:///data/anilist.duckdb` |
| [Parquet](#duckdb-and-parquet) (files or object storage) | `.parquet` files | `parquet:///data/parquet` |
| [CSV, TSV, JSON](#csv-tsv-and-json) | the matching files | convert to SQLite or DuckDB first |

The default schema is `public`, so the tables land in `public`. The dump has four tables: `anilist_catalog` (the anime, and the only one you strictly need), `anilist_detail_pages`, `anilist_index_state` and `anilist_missing_ids`.

### Download and verify

```bash
TAG=<release tag>      # for example the newest one on the Releases page
gh release download "$TAG" -R eiryui/AniList-DB-Dump -p '*.sqlite' -p 'SHA256SUMS*' -p 'MANIFEST*'
sha256sum -c --ignore-missing SHA256SUMS-$TAG.txt
```

Swap `'*.sqlite'` for the pattern of the file you want (`'*.dump'`, `'*.parquet'`, `'*.json'`, ...). Without the GitHub CLI, download from the Releases page in the browser.

### PostgreSQL, local or Docker

Use PostgreSQL 18 client tools or newer. Older `pg_restore` versions can refuse a newer archive.

```bash
createdb anilist
pg_restore --no-owner --no-privileges -d anilist anilist-db-dump-<tag>.dump

# or plain SQL
psql -v ON_ERROR_STOP=1 -d anilist -f anilist-db-dump-<tag>.sql
# or the gzipped copy
gunzip -c anilist-db-dump-<tag>.sql.gz | psql -v ON_ERROR_STOP=1 -d anilist
```

No local Postgres? Run it in Docker:

```bash
docker run -d --name anilist -e POSTGRES_PASSWORD=pw -p 5432:5432 postgres:18
docker exec -i anilist createdb -U postgres anilist
pg_restore --no-owner --no-privileges -d "postgresql://postgres:pw@localhost:5432/anilist" anilist-db-dump-<tag>.dump
```

Restore into an empty database. The dump comes from Supabase, so it can contain grants to Supabase roles (`anon`, `authenticated`, `service_role`). `--no-privileges` avoids the "role does not exist" errors in `pg_restore`; with `psql` they are harmless.

### Hosted PostgreSQL

The same two steps work on any service that gives you a normal PostgreSQL connection string (Supabase, Neon, Railway, Render and similar):

1. Create an empty database in the service's dashboard and copy its connection string.
2. Restore into it from your own machine:

```bash
pg_restore --no-owner --no-privileges -d "postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require" anilist-db-dump-<tag>.dump
```

Things that differ between services:

- **Use a direct or session connection for the restore.** Transaction poolers (for example Supabase's port 6543, or Neon's `-pooler` host) are not meant for `pg_restore`.
- **IPv6.** Some services only offer IPv6 on the direct connection. If your network is IPv4 only, use the service's session pooler string instead.
- **Size limits.** Check your plan's storage limit against the size of the `.dump` in the release before you restore.
- **Read-only access for the API.** Create a login that can only `SELECT` (SQL below) and give AniServe that one.

```sql
CREATE ROLE aniserve LOGIN PASSWORD 'change-me';
GRANT CONNECT ON DATABASE anilist TO aniserve;
GRANT USAGE ON SCHEMA public TO aniserve;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO aniserve;
```

These hosted-service steps rely on standard PostgreSQL behaviour. AniServe's own guide marks every hosted service as untested, so if one needs a tweak, please open an issue.

### SQLite, no server

The simplest option. One file, no database server.

```bash
mkdir -p data && mv anilist-db-dump-*.sqlite data/anilist.sqlite
sqlite3 data/anilist.sqlite "select count(*) from anilist_catalog;"
```

### DuckDB and Parquet

```bash
# DuckDB: use the file as is
duckdb data/anilist.duckdb "select count(*) from anilist_catalog;"

# Parquet: query the files directly (or keep them on object storage)
mkdir -p data/parquet && mv anilist-db-dump-*.parquet data/parquet/
duckdb -c "select count(*) from 'data/parquet/*.public.anilist_catalog.parquet';"
```

### CSV, TSV and JSON

These have no schema or indexes. For a quick look, open them in a spreadsheet or load them with pandas. To query them, convert them to SQLite or DuckDB with AniServe's `load_dump.py`:

```bash
python load_dump.py anilist-db-dump-<tag>.public.anilist_catalog.csv --to sqlite --out data/anilist.sqlite
```

It accepts CSV, TSV and JSON files or a folder of them, and adds indexes.

## Serve it as a JSON API

[AniServe](https://github.com/eiryui/AniServe) is a small read-only JSON API with a browser UI for this dump. It never writes to the database and never calls AniList. It reads PostgreSQL, SQLite, DuckDB and Parquet, so anything in the [Deploy it](#deploy-it) table works.

Quick start with SQLite:

```bash
git clone https://github.com/eiryui/AniServe && cd AniServe
pip install -r requirements.txt
mkdir -p data && cp /path/to/anilist-db-dump-<tag>.sqlite data/anilist.sqlite
cp .env.example .env            # DATABASE_URL already points at data/anilist.sqlite
uvicorn app:app --port 8002
```

Then open:

- `http://localhost:8002/` for the web UI
- `http://localhost:8002/swagger` for the interactive API docs
- `http://localhost:8002/health` to confirm it is connected to the database

```bash
curl "localhost:8002/search?query=frieren"
curl "localhost:8002/trending?per_page=5"
curl "localhost:8002/info/<anilist id>"
```

Already loaded the dump into PostgreSQL, DuckDB or Parquet? Set `DATABASE_URL` in `.env` to the matching string from the [Deploy it](#deploy-it) table and start it the same way. To run it as a container, the repo has a `Dockerfile`:

```bash
docker build -t aniserve .
docker run -p 8002:8002 -v "$PWD/data:/app/data:ro" -e DATABASE_URL=sqlite:///data/anilist.sqlite aniserve
```

The same image works on any host that runs Docker images or Python apps. Set `DATABASE_URL` and `PORT` there. For a public API, also read the rate limit and CORS settings in `.env.example`.

**More:** the [AniServe repo](https://github.com/eiryui/AniServe) has the full endpoint list and configuration, and its [deployment guide](https://github.com/eiryui/AniServe/blob/main/docs/DEPLOY.md) covers each database, read-only roles and keeping the data fresh when a new release comes out.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `pg_restore` says the archive version is unsupported or `server version mismatch` | Local client is older than the dump | Use PostgreSQL 18 tools or newer, or restore the plain `.sql` instead |
| Restore prints `role ... does not exist` | Grants to Supabase roles | Harmless. Use `--no-privileges` to silence it |
| Restore fails on a hosted database through a pooler | Transaction poolers do not suit `pg_restore` | Use the direct or session connection string |
| "Network is unreachable" or a timeout to a hosted database | Direct connection is IPv6 only and your network is IPv4 | Use the service's session pooler string |
| AniServe `/health` says `degraded` | Its `problem` field says why: file not found, wrong URL scheme, missing table or missing driver | Fix `DATABASE_URL`, or install the driver it names |
| SQLite path not found | Slashes in the URL | Three slashes for a relative path, four for an absolute one (`sqlite:////srv/anilist.sqlite`) |

## Running your own dump workflow

The weekly dumps are produced by GitHub Actions from a private indexer's database. Setting that up is a maintainer task and only the repository owners can do it. The owner guide is [`.github/ADMIN.md`](https://github.com/eiryui/AniList-DB-Dump/blob/main/.github/ADMIN.md). You do not need any of it to use the dumps.

License: [WTFPL](http://www.wtfpl.net/)
