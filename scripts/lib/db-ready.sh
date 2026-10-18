#!/usr/bin/env bash
# Stable PostgreSQL/Redis readiness gate shared by the validator scripts.
#
# The postgres:16-alpine entrypoint briefly runs a temporary postmaster to
# finish initialization, fast-shuts it down, then exec's the real server. A
# single `pg_isready` probe can therefore either succeed against the temporary
# server or fail during the temporary->final handover gap even though the
# database is healthy. The old "poll until first success, then one extra final
# check" pattern could land that extra check in the handover gap and emit a
# false "PostgreSQL did not become ready." (GitHub Quality run 34687551648).
# These gates only return 0 after a re-probe ~1s later succeeds too; the
# temporary server lives far less than 1s, so a pass always reflects the
# long-lived server.

con_pg_ok() {
  docker compose exec -T database pg_isready \
    -U "${JANUARY_DATABASE_USER:-january}" -d "${JANUARY_DATABASE_NAME:-january}" >/dev/null 2>&1
}

con_redis_ok() {
  docker compose exec -T redis redis-cli ping >/dev/null 2>&1
}

pg_ready() {
  for _ in $(seq 1 30); do
    if con_pg_ok; then
      sleep 1
      if con_pg_ok; then
        return 0
      fi
    fi
    sleep 1
  done
  return 1
}

redis_ready() {
  for _ in $(seq 1 30); do
    if con_redis_ok; then
      sleep 1
      if con_redis_ok; then
        return 0
      fi
    fi
    sleep 1
  done
  return 1
}