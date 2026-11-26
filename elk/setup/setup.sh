#!/usr/bin/env bash
# One-shot ELK bootstrap, run by the `setup` service in docker-compose.elk.yml.
#
#  1. Sets the password of the built-in kibana_system user (Kibana 8 cannot
#     authenticate as the `elastic` superuser).
#  2. Creates a least-privilege role and user for Logstash, limited to writing
#     the minotaur-game-*, minotaur-ai-* and minotaur-pipeline-* indices.
#
# Idempotent: every call is a PUT/POST that overwrites the previous state, so
# it is safe to run on every `docker compose up`.
#
# Secrets arrive only as environment variables from .env and are never logged.

set -euo pipefail

ES_URL="http://elasticsearch:9200"

# Restrict passwords to a JSON- and shell-safe alphabet so they can be embedded
# in request bodies without escaping. `openssl rand -hex 24` output qualifies.
check_password() {
  local name="$1" value="$2"
  if [[ ! "$value" =~ ^[A-Za-z0-9_-]{16,}$ ]]; then
    echo "ERROR: $name must be at least 16 characters of [A-Za-z0-9_-]" >&2
    exit 1
  fi
}

check_password ELASTIC_PASSWORD "${ELASTIC_PASSWORD:-}"
check_password KIBANA_SYSTEM_PASSWORD "${KIBANA_SYSTEM_PASSWORD:-}"
check_password LOGSTASH_INTERNAL_PASSWORD "${LOGSTASH_INTERNAL_PASSWORD:-}"

# No password is ever a command-line argument (visible in the process list):
#  - curl reads the elastic credentials as a config file from a file descriptor
#    (bash process substitution, written by the printf builtin);
#  - request bodies, which carry the other passwords, go to curl on stdin.
es_curl() {
  curl -K <(printf 'user = "elastic:%s"\n' "$ELASTIC_PASSWORD") "$@"
}

es() {
  # Usage: es METHOD PATH JSON_BODY
  local method="$1" path="$2" body="$3"
  printf '%s' "$body" | es_curl -sS --fail-with-body -X "$method" \
    -H 'Content-Type: application/json' --data-binary @- "${ES_URL}${path}"
  echo
}

echo "Waiting for Elasticsearch to accept the elastic credentials..."
for _ in $(seq 1 60); do
  if es_curl -fsS -o /dev/null "${ES_URL}/_security/_authenticate"; then
    break
  fi
  sleep 2
done
es_curl -fsS -o /dev/null "${ES_URL}/_security/_authenticate" || {
  echo "ERROR: cannot authenticate as elastic. If the esdata volume already existed," >&2
  echo "       ELASTIC_PASSWORD in .env must match the password it was created with." >&2
  exit 1
}

echo "Setting kibana_system password..."
es POST /_security/user/kibana_system/_password \
  "{\"password\":\"${KIBANA_SYSTEM_PASSWORD}\"}"

echo "Creating role minotaur_logstash_writer..."
es PUT /_security/role/minotaur_logstash_writer '{
  "cluster": ["monitor"],
  "indices": [
    {
      "names": ["minotaur-game-*", "minotaur-ai-*", "minotaur-pipeline-*"],
      "privileges": ["create_index", "write"]
    }
  ]
}'

echo "Creating user logstash_internal..."
es PUT /_security/user/logstash_internal \
  "{\"password\":\"${LOGSTASH_INTERNAL_PASSWORD}\",\"roles\":[\"minotaur_logstash_writer\"],\"full_name\":\"Minotaur Logstash writer\"}"

echo "ELK setup complete."
