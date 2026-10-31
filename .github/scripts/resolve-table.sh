# Sourced by the Status and Sample dump workflows. Needs SUPABASE_DB_URL, STATS_TABLE, STATS_ID_COLUMN.
# Optional: STATS_TABLE_VAR (the raw repo variable, empty when unset), SAMPLE_ORDER_COLUMN,
#           RESOLVE_SOFT=1 (warn instead of exiting when no table is found).
# Sets: id (identifier regex), schema, tbl, STATS_TABLE.

id='[A-Za-z_][A-Za-z0-9_]*'
[[ "$STATS_TABLE" =~ ^$id(\.$id)?$ && "$STATS_ID_COLUMN" =~ ^$id$ ]] \
  || { echo "::error::Invalid STATS_TABLE or STATS_ID_COLUMN"; exit 1; }
schema=public; tbl=$STATS_TABLE
[[ "$STATS_TABLE" == *.* ]] && { schema=${STATS_TABLE%%.*}; tbl=${STATS_TABLE#*.}; }

if [ -z "${RESOLVE_SOFT:-}" ]; then
  psql "$SUPABASE_DB_URL" -X -Atqc 'select 1' >/dev/null \
    || { echo "::error::Cannot connect to the database. Check SUPABASE_DB_URL (Session pooler string)."; exit 1; }
fi

found=$(psql "$SUPABASE_DB_URL" -X -Atq -v s="$schema" -v t="$tbl" <<'SQL'
select 1 from information_schema.tables
where table_schema = :'s' and table_name = :'t' and table_type = 'BASE TABLE';
SQL
) || found=""

if [ -z "$found" ]; then
  list=$(psql "$SUPABASE_DB_URL" -X -At -F '|' -v col="$STATS_ID_COLUMN" -v ocol="${SAMPLE_ORDER_COLUMN:-popularity}" <<'SQL'
select c.table_schema || '.' || c.table_name,
       (bool_or(c.column_name = :'col') and bool_or(c.column_name = :'ocol'))::text
from information_schema.columns c
join information_schema.tables t using (table_schema, table_name)
where t.table_type = 'BASE TABLE'
  and c.table_schema !~ '^pg_'
  and c.table_schema not in ('information_schema','auth','storage','realtime','vault','extensions',
      'graphql','graphql_public','pgsodium','pgsodium_masks','supabase_functions','supabase_migrations',
      'net','cron','pgbouncer','_realtime','_analytics')
group by 1 order by 1;
SQL
  ) || list=""
  matches=$(grep '|true$' <<<"$list" | cut -d'|' -f1 || true)
  names=$(cut -d'|' -f1 <<<"$list" | head -n 40 | paste -sd, - | sed 's/,/, /g')

  if [ -z "${STATS_TABLE_VAR:-}" ] && [ -n "$matches" ] && [ "$(wc -l <<<"$matches")" -eq 1 ]; then
    echo "::warning::Table $schema.$tbl not found. Using $matches (the only table with the id and popularity columns). Set the STATS_TABLE variable to silence this."
    schema=${matches%%.*}; tbl=${matches#*.}
  else
    msg="Table $schema.$tbl does not exist. Set the STATS_TABLE repo variable (Settings > Secrets and variables > Actions > Variables) to your anime table. Tables found: ${names:-none}"
    if [ -n "${RESOLVE_SOFT:-}" ]; then echo "::warning::$msg"; else echo "::error::$msg"; exit 1; fi
  fi
fi
STATS_TABLE="$schema.$tbl"
