# Admin guide

How to set up the dump workflows in this repo and connect them to the AniList-Indexer.

> **Owners only.** AniList-Indexer is a private project, so only its owners (and people they give access to) can run it or see its database. The workflows here only read from the database the indexer fills, so nobody else can reproduce this setup. If you only want the data, use a [release](https://github.com/eiryui/AniList-DB-Dump/releases) and the public [setup guide](../SETUP.md) instead.

## How the pieces fit

```
AniList-Indexer (private)  --writes-->  Supabase Postgres  --read by-->  GitHub Actions (this repo)
                                                                              |
                                  Releases (dumps)  <--  Weekly / Manual  ----+
                                  Pages site + stats  <--  Status and site  --+
                                  sample/sample.sql  <--  Sample dump  -------+
```

- The **indexer** crawls AniList and keeps the Postgres tables up to date.
- The **workflows** in this repo never write to that database. They `pg_dump` it, export Parquet, SQLite and DuckDB files, publish a release, and update the status page.
- **AniServe** (public, separate repo) is a downstream consumer of the released files and has nothing to do with this setup.

Set things up in this order: database, indexer, secrets, Pages, first dump.

## 1. Database

You need a Supabase project (any PostgreSQL server that GitHub runners can reach also works). The workflows always dump the `public` schema and expect the indexer's tables there:

| Table | Role |
|---|---|
| `anilist_catalog` | The anime. Required. Needs an `id` and a `popularity` column (the status page and sample use them) |
| `anilist_detail_pages` | Paged characters and recommendations |
| `anilist_index_state` | Indexer bookkeeping, such as last refresh times |
| `anilist_missing_ids` | IDs the indexer could not fetch |

The table and column names are fixed in the workflows. If the indexer ever renames them, change them in `status.yml` and `sample-dump.yml`.

## 2. AniList-Indexer

Install and run the indexer by following the instructions in the indexer's own repo. This guide only covers what the dumps need from it:

1. **Point it at the same database** the workflows will dump (the same Supabase project).
2. **Run it at least once** so `anilist_catalog` has rows before the first dump. Check from any SQL client:

   ```sql
   select count(*), min(id), max(id) from public.anilist_catalog;
   ```

   The status page shows these same numbers, so an empty or tiny table here means an empty or tiny release.
3. **Keep it running** on whatever host or schedule you use for it, so each Saturday dump has fresh data. The workflows do not start or stop the indexer.
4. **Do not share its credentials.** The indexer needs write access. The workflows only need to read, and you can give them a separate read-only database role if you prefer (see [Secrets](#3-secrets)).

> Only the owners have the indexer's code, hosting and write credentials. If you are a new owner, ask an existing one for access to the private repo and its environment settings.

## 3. Secrets

In the repo go to **Settings > Secrets and variables > Actions** and add:

| Secret | Required | What |
|---|---|---|
| `DATABASE_URL` | yes | Session pooler connection string from Supabase (Connect), port 5432 |

The `DATABASE_URL` format:

```
postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

The direct connection is IPv6 only and GitHub runners cannot reach it. The transaction pooler (6543) does not work with `pg_dump`.

For least privilege, create a read-only role for the workflows and use its string as `DATABASE_URL`:

```sql
CREATE ROLE dumper LOGIN PASSWORD 'change-me';
GRANT USAGE ON SCHEMA public TO dumper;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dumper;
```

Check that your first dump succeeds with this role before relying on it.

## 4. Pages

**Settings > Pages > Source: GitHub Actions.** Then run **AniList-DB-Dump - Status and site** once from the Actions tab. The site is at `https://<owner>.github.io/<repo>/` and the public setup guide (`SETUP.md`) is rendered at `/setup/`.

## 5. First dump

Run **AniList-DB-Dump - Manual** from the Actions tab. After that the Saturday schedule takes over and does not depend on manual runs.

Afterwards, run **AniList-DB-Dump - Sample dump** once if it has not already run after the dump, so the landing page shows the real covers instead of the bundled fallback.

## Configuration

Variables (**Settings > Secrets and variables > Actions > Variables** tab, not Secrets):

| Name | Default | What |
|---|---|---|
| `KEEP_WEEKLY` | `0` (keep all) | Keep only the newest N weekly releases. Manual releases are never pruned |
| `PG_VERSION` | `18` | pg_dump client version. Must be equal to or newer than the server |
| `SAMPLE_SIZE` | `20` | Rows in `sample/sample.sql` |

All three are optional. Everything else is fixed in the workflows: the `public` schema, and the table `public.anilist_catalog` with its `id` and `popularity` columns (the sample shows the most popular rows first).

## Workflows

| Workflow | Trigger | Does |
|---|---|---|
| Weekly | cron, Saturday 00:00 UTC | Dump, then release `weekly-YYYY-MM-DD` |
| Manual | Run workflow button | Dump, then release `manual-YYYY-MM-DD-HHMM`. Separate from Weekly, so it never resets or skips the schedule. |
| `_dump.yml` | called by the two above | Shared logic. Dumps PostgreSQL (`.dump`), exports Parquet, SQLite and DuckDB, checks row counts, writes the release notes, creates the release, prunes |
| Status and site | every 6 h, after any dump, on push to `site/`, `SETUP.md` or `sample/` | Checks the database, writes `stats.json`, updates the README block, deploys Pages |
| Sample dump | after Weekly or Manual, or its own button | Commits `sample/sample.sql`: table definition plus the 20 most popular rows |

Weekly and Manual share a concurrency group, so overlapping runs queue instead of colliding. Each release notes file lists the creation time and the next scheduled Saturday.

### What a dump produces

Four formats, all plain uncompressed files. Nothing is zipped or encrypted.

| Format | File | How it is made |
|---|---|---|
| PostgreSQL | `anilist-db-dump-<tag>.dump` | `pg_dump --format=custom --compress=0`, schema `public`, `--no-owner` |
| SQLite | `anilist-db-dump-<tag>.sqlite` | `export-formats.py`, data only |
| DuckDB | `anilist-db-dump-<tag>.duckdb` | `export-formats.py`, data only, tables in the `public` schema |
| Parquet | `anilist-db-dump-<tag>.public.<table>.parquet` | `export-formats.py`, one file per table |

Plus `MANIFEST-<tag>.json` and `SHA256SUMS-<tag>.txt`. The Parquet file names keep the `public` part so existing scripts and queries that use that pattern keep working.

The Parquet, SQLite and DuckDB files are written in one read-only transaction, so they match each other exactly. The `.dump` is taken a moment earlier. The workflow then counts the rows in every file and writes `MANIFEST-<tag>.json`. If the Parquet, SQLite or DuckDB counts differ from Postgres, the workflow fails and nothing is released. A difference in the `.dump` only raises a warning and `all_match: false` (a running indexer can make this happen). The exports hold data only: no indexes or constraints. Each file must stay under GitHub's 2 GB release asset limit and the workflow warns if one does not.

The release notes are built from the same run: type, creation time, next scheduled dump, a file list with sizes, the row-count table, and a short "use it" snippet.

### Status page

A browser cannot reach Postgres, so the Status workflow does the check and publishes `stats.json`: online or offline, row count and min and max ID of `public.anilist_catalog`, database size, table count, latest release. The landing page reloads it every minute. If the database is offline it shows the last known values, labelled as such. If `stats.json` is older than 13 hours it says the status is out of date.

### Landing page covers

The two rows of covers are read from `sample/sample.sql`, which the Status workflow publishes as `sample.sql` next to the page. The browser pulls the JSON out of each `INSERT` line and shows rank, cover, title, format, year and score. Until the first Sample dump has run, the page falls back to `site/showcase-seed.json`.

## Private data

The default assumes the database only holds public data. If it also holds anything private (users, emails, tokens, auth tables), keep the repo private, and remember that the release files, `sample/sample.sql`, the README stats and the Pages site are public in a public repo. Pages on a private repo needs a paid GitHub plan and the site is still public. Everything in the `public` schema is dumped, so keep private tables in another schema.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Dump fails with "Network is unreachable" or a connection timeout | Direct (IPv6) connection string | Use the Session pooler string on port 5432 |
| `server version mismatch` from pg_dump | The client on PATH is older than the server (the runner ships PostgreSQL 16) | The workflows already put `/usr/lib/postgresql/$PG_VERSION/bin` first. If your server is newer than 18, raise the `PG_VERSION` variable |
| 403 "Resource not accessible by integration" | Org or enterprise sets workflow permissions to read-only | The workflows request their own permissions, so first try re-running. If it persists, an org owner sets Org settings > Actions > General > Workflow permissions to read and write |
| README or `sample/sample.sql` not updating, only a warning in the log | Branch protection or a ruleset blocks the bot push | Exempt `github-actions[bot]` or allow it to bypass |
| Pages deploy fails | Pages source is not "GitHub Actions", or Pages is disabled for the org | Fix in Settings > Pages |
| Landing page says "No stats.json found" | Status workflow has not run | Run it once |
| Landing page says "status out of date" | Scheduled runs stopped | Check the Actions tab; see the 60-day note under Gotchas |
| Status page shows "--" for anime counts | `public.anilist_catalog` is missing or has no `id` column | Check the table with the query in [step 2](#2-anilist-indexer) |
| Sample workflow fails | `public.anilist_catalog` has no `popularity` column, or the table is empty | Run the indexer first, or check the columns |
| Release has far fewer rows than the previous one | The indexer was reset, is mid-crawl, or points at a different database | Check the row count query in [step 2](#2-anilist-indexer) before publishing; delete the bad release and re-run Manual once the table is right |
| Release upload fails on a large file | Over the 2 GB asset limit | Drop the file that is too big (for example the `.duckdb`) from `_dump.yml` |

## Gotchas

- Scheduled runs can start several minutes late and run from the default branch only.
- GitHub pauses scheduled workflows after 60 days without repo activity in public repos. A commit, or re-enabling the workflows in the Actions tab, fixes it.
- A dump is not a full Supabase backup. Only the `public` schema is included: no storage files, Edge Functions, project settings or auth users.
- To change the Saturday schedule, edit the cron line in `weekly-dump.yml` and the next-Saturday logic in `_dump.yml` and `status.yml`.
- Editing this file does not redeploy the site. Only `site/`, `SETUP.md` and `sample/` do.

## Files

```
.github/
  ADMIN.md            This file
  workflows/
    weekly-dump.yml     Saturday cron
    manual-dump.yml     Manual button
    _dump.yml           Shared dump and release logic
    status.yml          Stats, README block, Pages deploy
    sample-dump.yml     Commits sample/sample.sql
  scripts/
    build-manifest.py   Row counts and MANIFEST
    export-formats.py   Parquet, SQLite and DuckDB exports
sample/sample.sql     Table definition and 20 rows (generated)
site/                 Landing page and setup page
SETUP.md              Public guide: using and deploying the dumps
```
