# AniList-DB-Dump setup

Weekly and manual SQL dumps of a Supabase Postgres database, stored as GitHub Releases, plus a small status page.

## What you get

- A release every Saturday at 00:00 UTC, tagged `weekly-YYYY-MM-DD`.
- A manual dump button, tagged `manual-YYYY-MM-DD-HHMM`. It is a separate workflow and never resets or skips the Saturday dump.
- Every dump comes in four SQL formats: `.dump` (pg_dump custom), `.tar` (pg_dump tar), `.sql.gz` (plain SQL) and `-schema.sql` (schema only), plus a `SHA256SUMS` file.
- A small `sample/sample.sql` committed to the repo: the table definition and 20 rows with their IDs listed.
- Release notes with creation time, next scheduled update, schemas, Postgres version, size and checksum.
- A landing page that shows whether the database is online, how many anime it holds, the highest anime ID and more.
- This page, rendered at `/setup/` with share buttons.

## 1. Create the repo

Push these files to a new GitHub repo. Keep it **private** unless you set an encryption passphrase (step 3): anyone who can read the repo can download the dumps.

Scheduled workflows and Pages publish from the default branch.

## 2. Add the database secret

Add `SUPABASE_DB_URL` under Settings > Secrets and variables > Actions > Secrets.

Use the **Session pooler** string from the Supabase dashboard (Connect):

```
postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

The direct connection is IPv6 only and GitHub runners cannot reach it. Use port 5432, not the transaction pooler on 6543.

## 3. Optional settings

Secrets:

| Name | What |
|---|---|
| `DUMP_ENCRYPTION_PASSPHRASE` | Encrypts dumps with gpg AES256 (`.sql.gz.gpg`) |
| `SOURCE_DB_URL` | Copy workflow only. Falls back to `SUPABASE_DB_URL` |
| `TARGET_DB_URL` | Copy workflow only. The database to write into |

Variables:

| Name | Default | What |
|---|---|---|
| `DUMP_SCHEMAS` | `public` | Comma separated, for example `public,auth,storage` |
| `KEEP_WEEKLY` | `0` (keep all) | Keep only the newest N weekly releases. Manual ones are never deleted |
| `PG_VERSION` | `17` | pg_dump client version. Must be equal to or newer than the server |
| `STATS_TABLE` | `anime` | Table counted for the landing page. `schema.table` works |
| `STATS_ID_COLUMN` | `id` | ID column used for the highest and lowest anime ID |
| `SAMPLE_SIZE` | `20` | Rows included in `sample/sample.sql` |

## 4. Turn on the status page

1. Settings > Pages > Source: **GitHub Actions**.
2. Settings > Actions > General > Workflow permissions: **Read and write**.
3. Actions tab > **AniList-DB-Dump - Status and site** > Run workflow.

The site then lives at `https://<owner>.github.io/<repo>/`, and the setup page at `/setup/`.

Pages on a private repo needs a paid GitHub plan, and the site is public even if the repo is not. It only exposes counts, sizes and the release link (the release itself stays private). On the free plan the repo must be public, so encrypt your dumps.

## 5. First dump

Actions tab > **AniList-DB-Dump - Manual** > Run workflow. The status page and README refresh by themselves afterwards.

## How the status page works

The browser cannot talk to Postgres, so a workflow does it. Every 6 hours, after every dump, and whenever `site/` or `setup.md` changes, the **Status and site** workflow:

1. connects to the database and records online or offline,
2. counts rows in `STATS_TABLE`, finds the min and max `STATS_ID_COLUMN`, database size and table count,
3. looks up the latest release,
4. writes `stats.json`, updates the stats block in `README.md`, and deploys the site.

The landing page cycles through the numbers every few seconds and reloads `stats.json` every minute. If the database is offline it shows the last known values, labelled as such. If the data is older than 13 hours it says the status is out of date.

## Dump formats

| File | Format | Restore with |
|---|---|---|
| `*.dump` | pg_dump custom, compressed | `pg_restore` |
| `*.tar` | pg_dump tar | `pg_restore` |
| `*.sql.gz` | plain SQL, gzipped | `psql` |
| `*-schema.sql` | plain SQL, no data | `psql` |
| `SHA256SUMS-<tag>.txt` | checksums | `sha256sum -c` |

The `.dump` is taken from the database once. The `.sql.gz` and schema file are converted from it, so they match. The `.tar` is a second pg_dump moments later. Each file must stay under GitHub's 2 GB release asset limit; the workflow warns if one does not.

## Sample dump

The **Sample dump** workflow writes `sample/sample.sql` and commits it. It contains the `CREATE TABLE` for `STATS_TABLE`, then the first 20 rows by ID as `INSERT` statements, with the 20 IDs listed in a comment at the top. SQL only.

It runs after the weekly update, after a manual dump, and from its own Run workflow button. It does not run on the 6-hour status check.

## Restore

```bash
# custom or tar
pg_restore --no-owner -d "$TARGET_DB_URL" anilist-db-dump-weekly-2026-11-07.dump

# plain SQL
gunzip -c anilist-db-dump-weekly-2026-11-07.sql.gz | psql "$TARGET_DB_URL"

# encrypted: decrypt first
gpg --decrypt FILE.gpg > FILE
```

Restore into an empty database or schema. The dumps have no `DROP` statements.

## Copy a database to another target

Add `TARGET_DB_URL` (and optionally `SOURCE_DB_URL`), then run **AniList-DB-Dump - Copy database** from the Actions tab.

- `source = live`: dump `SOURCE_DB_URL` straight into `TARGET_DB_URL`.
- `source = release`: restore the release named in `release_tag`.
- `wipe_target`: drop and recreate the listed schemas on the target first. Careful.
- `confirm`: type `COPY`.

It refuses to run when source and target are the same. psql errors are printed at the end; "already exists" noise on Supabase managed objects is normal.

## Files

```
.github/workflows/
  weekly-dump.yml     Saturday cron
  manual-dump.yml     Manual button
  _dump.yml           Shared dump and release logic
  status.yml          Stats, README block, Pages deploy
  sample-dump.yml     Commits sample/sample.sql
  copy-database.yml   Optional copy to another database
sample/sample.sql      Sample: table + 20 rows (generated)
site/index.html       Landing page
site/setup/index.html Renders this file with share buttons
setup.md              This file
```

## Gotchas

- Scheduled runs can start several minutes late.
- GitHub pauses scheduled workflows after 60 days without repo activity in public repos. A commit or re-enabling it in the Actions tab fixes it.
- Release assets are limited to 2 GB each.
- A dump is not a full Supabase backup. Storage files, Edge Functions and project settings are not included, and auth users only if you add `auth` to `DUMP_SCHEMAS`.
- To change the Saturday schedule, edit the cron line in `weekly-dump.yml` and the next-Saturday logic in `_dump.yml` and `status.yml`.

License: WTFPL.
