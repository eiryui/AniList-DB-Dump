# AniList-DB-Dump

Weekly and manual `pg_dump` snapshots of a Supabase Postgres database holding AniList data, published as GitHub Releases, plus a status page.

Two audiences:

- **Just want the data?** Read [Using the dumps](#using-the-dumps).
- **Running your own copy?** Read [Run your own](#run-your-own).

## Using the dumps

Open the repo's **Releases** page. Weekly dumps are tagged `weekly-YYYY-MM-DD`, manual ones `manual-YYYY-MM-DD-HHMM`. The newest release is at the top, and its notes show when it was made and when the next scheduled dump is due.

### Which file?

| File | Use it when |
|---|---|
| `*.dump` | You have PostgreSQL and want the fastest, most flexible restore (`pg_restore`). Pick this by default. Supports restoring single tables |
| `*.sql.gz` | You want plain SQL for `psql`, or to read or process it with other tools |
| `*.tar` | You specifically need pg_dump's tar format. Same content as `.dump`, bigger |
| `*-schema.sql` | You only want the table structure, no data |
| `*-csv.zip` | You want spreadsheets, pandas, or any tool that reads CSV. One `schema.table.csv` per table with a header row. Data only. Nested JSON columns are quoted JSON strings |
| `*-json.zip` | You want JSON for scripts or apps. One `schema.table.jsonl` per table, one JSON object per line (JSON Lines), with nested fields kept as real JSON. Data only |
| `SHA256SUMS-<tag>.txt` | You want to verify a download: `sha256sum -c SHA256SUMS-<tag>.txt` |
| `sample/sample.sql` (in the repo) | You want to look at the structure and the 20 most popular rows before downloading anything big |

### Restore

Use PostgreSQL 17 client tools or newer. Older `pg_restore` versions can refuse a newer archive.

```bash
createdb anilist
pg_restore --no-owner --no-privileges -d anilist anilist-db-dump-<tag>.dump

# or plain SQL
gunzip -c anilist-db-dump-<tag>.sql.gz | psql anilist
```

No local Postgres? Use Docker:

```bash
docker run -d --name anilist -e POSTGRES_PASSWORD=pw -p 5432:5432 postgres:17
docker exec -i anilist createdb -U postgres anilist
pg_restore --no-owner --no-privileges -d "postgresql://postgres:pw@localhost:5432/anilist" anilist-db-dump-<tag>.dump
```

Notes:

- The default schema is `public`, so the tables land in `public`. Restore into an empty database.
- The dump comes from Supabase, so it can contain grants to Supabase roles (`anon`, `authenticated`, `service_role`). On a normal Postgres server `psql` prints harmless "role does not exist" errors. `--no-privileges` avoids them for `pg_restore`.
- Files ending in `.gpg` are encrypted. Only the repo owner has the passphrase, so ask them. Decrypt with `gpg --decrypt FILE.gpg > FILE`.

### Something not working?

See [Troubleshooting](#troubleshooting).

## Run your own

You need a Supabase project and a GitHub repo (a personal repo or an organization both work). A public repo is the normal setup for public AniList data. See [Private data](#private-data) if yours is not.

### 1. Secret

Add `SUPABASE_DB_URL` as an Actions secret. Use the **Session pooler** string from Supabase (Connect), port 5432:

```
postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

The direct connection is IPv6 only and GitHub runners cannot reach it. The transaction pooler (6543) does not work with pg_dump.

### 2. Pages

Settings > Pages > Source: **GitHub Actions**. Then run **AniList-DB-Dump - Status and site** once from the Actions tab. The site is at `https://<owner>.github.io/<repo>/` and this file is rendered at `/setup/`.

### 3. First dump

Run **AniList-DB-Dump - Manual**. After that the Saturday schedule takes over and does not depend on the manual runs.

The workflows default to the table `public.anilist_catalog` with an `id` column, so no setup is needed if that is yours. If your table is named differently, set `STATS_TABLE` and `STATS_ID_COLUMN` (below) before running the status and sample workflows.

### Configuration

Secrets:

| Name | Required | What |
|---|---|---|
| `SUPABASE_DB_URL` | yes | Session pooler connection string |
| `DUMP_ENCRYPTION_PASSPHRASE` | no | Encrypts every dump file with gpg AES256 (adds `.gpg`). Skip it for public data |
| `SOURCE_DB_URL` | no | Copy workflow only. Falls back to `SUPABASE_DB_URL` |
| `TARGET_DB_URL` | no | Copy workflow only. The database to write into |

Variables:

| Name | Default | What |
|---|---|---|
| `DUMP_SCHEMAS` | `public` | Comma separated, for example `public,auth,storage` |
| `KEEP_WEEKLY` | `0` (keep all) | Keep only the newest N weekly releases. Manual releases are never pruned |
| `PG_VERSION` | `17` | pg_dump client version. Must be equal to or newer than the server |
| `STATS_TABLE` | `public.anilist_catalog` | Table counted on the status page and sampled. `schema.table` works. If the variable is unset and `public.anilist_catalog` does not exist, the workflows use the one table that has both the ID and popularity columns. If that is ambiguous, the log lists your tables |
| `STATS_ID_COLUMN` | `id` | ID column for lowest and highest ID, and as the sample tie-break |
| `SAMPLE_SIZE` | `20` | Rows in `sample/sample.sql` |
| `SAMPLE_ORDER_COLUMN` | `popularity` | Column the sample is sorted by, highest first. If the column does not exist the sample falls back to the lowest IDs |

### Workflows

| Workflow | Trigger | Does |
|---|---|---|
| Weekly | cron, Saturday 00:00 UTC | Dump, then release `weekly-YYYY-MM-DD` |
| Manual | Run workflow button | Dump, then release `manual-YYYY-MM-DD-HHMM`. Separate from Weekly, so it never resets or skips the schedule |
| `_dump.yml` | called by the two above | The shared logic. Dumps in four formats plus CSV and JSON exports, optionally encrypts, writes notes, creates the release, prunes |
| Status and site | every 6 h, after any dump, on push to `site/` or `SETUP.md` | Checks the database, writes `stats.json`, updates the README block, deploys Pages |
| Sample dump | after Weekly or Manual, or its own button | Commits `sample/sample.sql`: table definition plus the 20 most popular rows, with the IDs listed in a header comment |
| Copy database | button | Copies live source or a release into `TARGET_DB_URL`. Optional |

Weekly and Manual share a concurrency group, so overlapping runs queue instead of colliding. Each release notes file lists the creation time and the next scheduled Saturday.

Dump formats: one `pg_dump --format=custom` (`.dump`), one `--format=tar` (`.tar`), and the `.sql.gz` and `-schema.sql` files converted from the `.dump` with `pg_restore`, so those three match exactly. The `.tar` is a second pg_dump a moment later. The CSV and JSON zips are exported table by table right after, so they can differ slightly from the `.dump` if the database changes while the workflow runs. They hold data only: no indexes, constraints or types. Each file must stay under GitHub's 2 GB release asset limit; the workflow warns if one does not.

### Status page

A browser cannot reach Postgres, so the Status workflow does the check and publishes `stats.json`: online or offline, row count and min and max ID of `STATS_TABLE`, database size, table count, latest release. The landing page cycles through these and reloads every minute. If the database is offline it shows the last known values, labelled as such. If `stats.json` is older than 13 hours it says the status is out of date.

### Landing page covers

The two rows of covers (top row scrolling left to right, bottom row right to left) are read from `sample/sample.sql`, which the Status workflow publishes as `sample.sql` next to the page. The browser pulls the JSON out of each `INSERT` line and shows rank, cover, title, format, year and score. It looks for AniList-style fields (`title.english`, `coverImage.extraLarge`, `format`, `seasonYear`, `averageScore`) and also accepts flat snake_case columns. Until the first Sample dump has run, the page falls back to `site/showcase-seed.json`, a bundled copy of the 20 most popular anime.

### Copy a database

Set `TARGET_DB_URL` (and optionally `SOURCE_DB_URL`), then run **Copy database**. Inputs: `source` (`live` or `release`), `release_tag`, `wipe_target` (drops and recreates the dumped schemas first), and `confirm` (type `COPY`). It refuses to run when source and target match. psql errors are listed at the end; "already exists" noise on Supabase managed objects is normal.

### Private data

The default assumes the database only holds public data. If it also holds anything private (users, emails, tokens, auth tables), keep the repo private, or set `DUMP_ENCRYPTION_PASSPHRASE`, and remember that `sample/sample.sql`, the README stats and the Pages site are public in a public repo. Pages on a private repo needs a paid GitHub plan and the site is still public.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Dump fails with "Network is unreachable" or a connection timeout | Direct (IPv6) connection string | Use the Session pooler string on port 5432 |
| `server version mismatch` from pg_dump | The client on PATH is older than the server (the runner ships PostgreSQL 16) | The workflows already put `/usr/lib/postgresql/$PG_VERSION/bin` first. If your server is newer than 17, raise `PG_VERSION` |
| 403 "Resource not accessible by integration" | Org or enterprise sets workflow permissions to read-only | The workflows request their own permissions, so first try re-running. If it persists, an org owner sets Org settings > Actions > General > Workflow permissions to read and write |
| README or `sample/sample.sql` not updating, only a warning in the log | Branch protection or a ruleset blocks the bot push | Exempt `github-actions[bot]` or allow it to bypass |
| Pages deploy fails | Pages source is not "GitHub Actions", or Pages is disabled for the org | Fix in Settings > Pages |
| Landing page says "No stats.json found" | Status workflow has not run | Run it once |
| Landing page says "status out of date" | Scheduled runs stopped | Check the Actions tab; see the 60-day note below |
| Log warning: `Table public.anilist_catalog not found. Using <table> (the only table with the id and popularity columns). Set the STATS_TABLE variable to silence this.` | `public.anilist_catalog` does not exist in your database, so the workflow guessed your table | Add `STATS_TABLE` as a repository **Variable** (Settings > Secrets and variables > Actions > Variables tab, not Secrets) with your table name, then re-run **Status and site** and **Sample dump** |
| `relation "public.anilist_catalog" does not exist` (Sample dump or Status log) | Your table has another name | Set `STATS_TABLE` to it. The log prints the tables it found. Use the exact case, for example `Anime` |
| Status page shows "--" for anime counts | `STATS_TABLE` or `STATS_ID_COLUMN` is wrong | Set the variables to match your table |
| Sample workflow fails with "No rows sampled" | Same, or the table is empty | Same fix |
| `pg_restore` says the archive version is unsupported | Local client too old | Use PostgreSQL 17 tools or newer, or use the `.sql.gz` |
| Restore prints "role ... does not exist" | Grants to Supabase roles | Harmless. Use `--no-privileges` to silence it |
| Release upload fails on a large file | Over the 2 GB asset limit | Narrow `DUMP_SCHEMAS`, or drop the `.tar` (or the CSV/JSON export) from `_dump.yml` |
| Copy workflow says it is refusing | Source equals target, or `confirm` is not `COPY` | Fix the inputs |

## Gotchas

- Scheduled runs can start several minutes late and run from the default branch only.
- GitHub pauses scheduled workflows after 60 days without repo activity in public repos. A commit, or re-enabling the workflows in the Actions tab, fixes it.
- A dump is not a full Supabase backup. Storage files, Edge Functions and project settings are not included, and auth users only if `auth` is in `DUMP_SCHEMAS`.
- To change the Saturday schedule, edit the cron line in `weekly-dump.yml` and the next-Saturday logic in `_dump.yml` and `status.yml`.

## Files

```
.github/workflows/
  weekly-dump.yml     Saturday cron
  manual-dump.yml     Manual button
  _dump.yml           Shared dump and release logic
  status.yml          Stats, README block, Pages deploy
  sample-dump.yml     Commits sample/sample.sql
  copy-database.yml   Optional copy to another database
sample/sample.sql     Table definition and 20 rows (generated)
site/index.html       Landing page
site/showcase-seed.json  Fallback covers until sample.sql exists
site/setup/index.html Renders this file with share buttons
SETUP.md              This file
```

License: [WTFPL](http://www.wtfpl.net/)
