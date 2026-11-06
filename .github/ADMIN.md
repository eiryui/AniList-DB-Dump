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
- The **workflows** in this repo never write to that database. They `pg_dump` it, export extra formats, publish a release, and update the status page.
- **AniServe** (public, separate repo) is a downstream consumer of the released files and has nothing to do with this setup.

Set things up in this order: database, indexer, secrets, Pages, first dump.

## 1. Database

You need a Supabase project (any PostgreSQL server that GitHub runners can reach also works). The workflows expect the indexer's tables in the `public` schema:

| Table | Role |
|---|---|
| `anilist_catalog` | The anime. Required. Has an `id` and a `popularity` column |
| `anilist_detail_pages` | Paged characters and recommendations |
| `anilist_index_state` | Indexer bookkeeping, such as last refresh times |
| `anilist_missing_ids` | IDs the indexer could not fetch |

If your anime table has a different name, set the `STATS_TABLE` variable (see [Configuration](#configuration)).

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
| `DUMP_ENCRYPTION_PASSPHRASE` | no | Encrypts every dump file with gpg AES256 (adds `.gpg`). Skip it for public data |
| `SOURCE_DB_URL` | no | Copy workflow only. Falls back to `DATABASE_URL` |
| `TARGET_DB_URL` | no | Copy workflow only. The database to write into |

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

Grant `SELECT` on any other schema you list in `DUMP_SCHEMAS` as well. Check that your first dump succeeds with this role before relying on it.

## 4. Pages

**Settings > Pages > Source: GitHub Actions.** Then run **AniList-DB-Dump - Status and site** once from the Actions tab. The site is at `https://<owner>.github.io/<repo>/` and the public setup guide (`SETUP.md`) is rendered at `/setup/`.

## 5. First dump

Run **AniList-DB-Dump - Manual** from the Actions tab. After that the Saturday schedule takes over and does not depend on manual runs.

The workflows default to the table `public.anilist_catalog` with an `id` column, so no further setup is needed if that is yours. If not, set `STATS_TABLE` and `STATS_ID_COLUMN` before running the Status and Sample workflows.

Afterwards, run **AniList-DB-Dump - Sample dump** once if it has not already run after the dump, so the landing page shows the real covers instead of the bundled fallback.

## Configuration

Variables (**Settings > Secrets and variables > Actions > Variables** tab, not Secrets):

| Name | Default | What |
|---|---|---|
| `DUMP_SCHEMAS` | `public` | Comma separated, for example `public,auth,storage` |
| `KEEP_WEEKLY` | `0` (keep all) | Keep only the newest N weekly releases. Manual releases are never pruned |
| `PG_VERSION` | `17` | pg_dump client version. Must be equal to or newer than the server |
| `STATS_TABLE` | `public.anilist_catalog` | Table counted on the status page and sampled. `schema.table` works. If unset and `public.anilist_catalog` does not exist, the workflows use the one table that has both the ID and popularity columns. If that is ambiguous, the log lists your tables |
| `STATS_ID_COLUMN` | `id` | ID column for lowest and highest ID, and as the sample tie-break |
| `SAMPLE_SIZE` | `20` | Rows in `sample/sample.sql` |
| `SAMPLE_ORDER_COLUMN` | `popularity` | Column the sample is sorted by, highest first. If it does not exist, the sample falls back to the lowest IDs |

## Workflows

| Workflow | Trigger | Does |
|---|---|---|
| Weekly | cron, Saturday 00:00 UTC | Dump, then release `weekly-YYYY-MM-DD` |
| Manual | Run workflow button | Dump, then release `manual-YYYY-MM-DD-HHMM`. Separate from Weekly, so it never resets or skips the schedule |
| `_dump.yml` | called by the two above | Shared logic. Dumps in five formats plus CSV, TSV, JSON, Parquet, SQLite and DuckDB exports, optionally encrypts, writes notes, creates the release, prunes |
| Status and site | every 6 h, after any dump, on push to `site/`, `SETUP.md` or `sample/` | Checks the database, writes `stats.json`, updates the README block, deploys Pages |
| Sample dump | after Weekly or Manual, or its own button | Commits `sample/sample.sql`: table definition plus the 20 most popular rows |
| Copy database | button | Copies live source or a release into `TARGET_DB_URL`. Optional |

Weekly and Manual share a concurrency group, so overlapping runs queue instead of colliding. Each release notes file lists the creation time and the next scheduled Saturday.

### What a dump produces

One `pg_dump --format=custom` (`.dump`), one `--format=tar` (`.tar`), and the `.sql.gz`, `.sql.zip`, `.sql.zst` and `-schema.sql` files converted from the `.dump` with `pg_restore`, so those five match exactly. The `.tar` is a second `pg_dump` a moment later. The CSV, TSV and JSON zips are exported table by table right after, so they can differ slightly from the `.dump` if the database changes while the workflow runs (a running indexer makes this likely).

The Parquet, SQLite and DuckDB files are written by `.github/scripts/export-formats.py` in one read-only transaction, so they match each other exactly. The workflow then counts the rows in every file and writes `MANIFEST-<tag>.json`. If the Parquet, SQLite or DuckDB counts differ from Postgres, the workflow fails and nothing is released. A difference in the `.dump`, CSV, TSV or JSON files only raises a warning and `all_match: false`. All of these hold data only: no indexes or constraints. Each file must stay under GitHub's 2 GB release asset limit; the workflow warns if one does not.

### Status page

A browser cannot reach Postgres, so the Status workflow does the check and publishes `stats.json`: online or offline, row count and min and max ID of `STATS_TABLE`, database size, table count, latest release. The landing page reloads it every minute. If the database is offline it shows the last known values, labelled as such. If `stats.json` is older than 13 hours it says the status is out of date.

### Landing page covers

The two rows of covers are read from `sample/sample.sql`, which the Status workflow publishes as `sample.sql` next to the page. The browser pulls the JSON out of each `INSERT` line and shows rank, cover, title, format, year and score. Until the first Sample dump has run, the page falls back to `site/showcase-seed.json`.

### Copy a database

Set `TARGET_DB_URL` (and optionally `SOURCE_DB_URL`), then run **Copy database**. Inputs: `source` (`live` or `release`), `release_tag`, `wipe_target` (drops and recreates the dumped schemas first), and `confirm` (type `COPY`). It refuses to run when source and target match. psql errors are listed at the end; "already exists" noise on Supabase managed objects is normal.

## Private data

The default assumes the database only holds public data. If it also holds anything private (users, emails, tokens, auth tables), keep the repo private, or set `DUMP_ENCRYPTION_PASSPHRASE`, and remember that `sample/sample.sql`, the README stats and the Pages site are public in a public repo. Pages on a private repo needs a paid GitHub plan and the site is still public. Do not add the indexer's own tables or credentials to `DUMP_SCHEMAS` unless you mean to publish them.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Dump fails with "Network is unreachable" or a connection timeout | Direct (IPv6) connection string | Use the Session pooler string on port 5432 |
| `server version mismatch` from pg_dump | The client on PATH is older than the server (the runner ships PostgreSQL 16) | The workflows already put `/usr/lib/postgresql/$PG_VERSION/bin` first. If your server is newer than 17, raise `PG_VERSION` |
| 403 "Resource not accessible by integration" | Org or enterprise sets workflow permissions to read-only | The workflows request their own permissions, so first try re-running. If it persists, an org owner sets Org settings > Actions > General > Workflow permissions to read and write |
| README or `sample/sample.sql` not updating, only a warning in the log | Branch protection or a ruleset blocks the bot push | Exempt `github-actions[bot]` or allow it to bypass |
| Pages deploy fails | Pages source is not "GitHub Actions", or Pages is disabled for the org | Fix in Settings > Pages |
| Landing page says "No stats.json found" | Status workflow has not run | Run it once |
| Landing page says "status out of date" | Scheduled runs stopped | Check the Actions tab; see the 60-day note under Gotchas |
| Log warning: `Table public.anilist_catalog not found. Using <table> ...` | `public.anilist_catalog` does not exist, so the workflow guessed your table | Add `STATS_TABLE` as a repository **Variable** with your table name, then re-run **Status and site** and **Sample dump** |
| `relation "public.anilist_catalog" does not exist` (Sample dump or Status log) | Your table has another name | Set `STATS_TABLE` to it. The log prints the tables it found. Use the exact case, for example `Anime` |
| Status page shows "--" for anime counts | `STATS_TABLE` or `STATS_ID_COLUMN` is wrong | Set the variables to match your table |
| Sample workflow fails with "No rows sampled" | Same, or the table is empty | Same fix, or run the indexer first |
| Release has far fewer rows than the previous one | The indexer was reset, is mid-crawl, or points at a different database | Check the row count query in [step 2](#2-anilist-indexer) before publishing; delete the bad release and re-run Manual once the table is right |
| Release upload fails on a large file | Over the 2 GB asset limit | Narrow `DUMP_SCHEMAS`, or drop the `.tar` (or one of the export steps) from `_dump.yml` |
| Copy workflow says it is refusing | Source equals target, or `confirm` is not `COPY` | Fix the inputs |

## Gotchas

- Scheduled runs can start several minutes late and run from the default branch only.
- GitHub pauses scheduled workflows after 60 days without repo activity in public repos. A commit, or re-enabling the workflows in the Actions tab, fixes it.
- A dump is not a full Supabase backup. Storage files, Edge Functions and project settings are not included, and auth users only if `auth` is in `DUMP_SCHEMAS`.
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
    copy-database.yml   Optional copy to another database
  scripts/
    build-manifest.py   Row counts and MANIFEST
    export-formats.py   Parquet, SQLite and DuckDB exports
    resolve-table.sh    Finds the table to count and sample
sample/sample.sql     Table definition and 20 rows (generated)
site/                 Landing page and setup page
SETUP.md              Public guide: using and deploying the dumps
```
