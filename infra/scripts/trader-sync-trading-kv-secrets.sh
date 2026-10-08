#!/usr/bin/env bash
# Store trader-app demo secrets from repo-root .env in demo Key Vault.
#
# Usage:
#   ./infra/scripts/trader-sync-trading-kv-secrets.sh
#   ENV_FILE=/path/to/.env ./infra/scripts/trader-sync-trading-kv-secrets.sh
#
# Trading App Configuration: each assignment becomes
# trader-app-<ENV_VAR> (underscores to hyphens, lowercased).
# Example: T212_API_KEY -> trader-app-t212-api-key
#
# DB Setup: stores trader-app-database-url. DEMO_DATABASE_URL is used when
# set; otherwise DATABASE_URL. Compose hosts (postgres, localhost) are refused.
# An Azure Postgres host gets sslmode=require when the URL has no sslmode.
# POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_HOST are not stored separately.
#
# The Build docker image section, including GITHUB_TOKEN, is not uploaded.
# Empty values are skipped. Values are not printed.
# This does not bind the secrets onto the Container App.
#
# Prerequisites: az login; Key Vault Secrets Officer on kv-aydeo-demo-weu.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=trader-build-lib.sh
source "$SCRIPT_DIR/trader-build-lib.sh"

ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
KV_NAME="${KV_NAME:-kv-aydeo-demo-weu}"
SECRET_PREFIX="${SECRET_PREFIX:-trader-app-}"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '1,21p' "$0"
  exit 0
fi
if [[ $# -gt 0 ]]; then
  echo "error: unknown argument: $1" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: env file not found: $ENV_FILE" >&2
  exit 1
fi

require_demo_subscription

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

manifest="$(python3 - "$ENV_FILE" "$workdir" "$SECRET_PREFIX" <<'PY'
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

env_path, workdir, prefix = sys.argv[1:]
lines = Path(env_path).read_text(encoding="utf-8").splitlines()
key_re = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
secret_re = re.compile(r"[a-z][a-z0-9-]{0,126}")
local_hosts = {"postgres", "localhost", "127.0.0.1", "host.docker.internal"}
banner_re = re.compile(r"# =+")


def section_body(title: str):
    start = next((index for index, line in enumerate(lines) if title in line), None)
    if start is None:
        return None
    for index in range(start + 1, len(lines)):
        if banner_re.fullmatch(lines[index].strip()):
            body = []
            for line in lines[index + 1 :]:
                if banner_re.fullmatch(line.strip()):
                    break
                body.append(line)
            return body
    sys.stderr.write(f"error: {title} banner is missing\n")
    sys.exit(1)


def unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def assignments(body, title: str):
    found = []
    for line in body:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key_re.fullmatch(key):
            sys.stderr.write(f"error: invalid env name in {title}: {key}\n")
            sys.exit(1)
        found.append((key, unquote(value)))
    return found


def write_secret(env_name: str, secret_name: str, value: str, seen: list) -> None:
    if not secret_re.fullmatch(secret_name):
        sys.stderr.write(f"error: Key Vault name is invalid for {env_name}\n")
        sys.exit(1)
    path = Path(workdir) / secret_name
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    seen.append(f"{env_name}\t{secret_name}")


def database_url(body):
    values = {key: value for key, value in assignments(body, "DB Setup")}
    demo = values.get("DEMO_DATABASE_URL", "")
    local = values.get("DATABASE_URL", "")
    if demo.strip():
        return "DEMO_DATABASE_URL", demo
    if local.strip():
        return "DATABASE_URL", local
    sys.stderr.write("skip empty DATABASE_URL\n")
    return None


def demo_database_url(env_name: str, value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"postgresql", "postgresql+psycopg"}:
        sys.stderr.write(
            f"error: {env_name} must start with postgresql:// or postgresql+psycopg://\n"
        )
        sys.exit(1)
    host = parsed.hostname or ""
    if host in local_hosts:
        sys.stderr.write(
            f"error: {env_name} host is '{host}'. "
            "Set DEMO_DATABASE_URL in the DB Setup section to the demo Postgres URL.\n"
        )
        sys.exit(1)
    if host.endswith(".postgres.database.azure.com"):
        query = parse_qsl(parsed.query, keep_blank_values=True)
        if not any(key == "sslmode" for key, _unused in query):
            query.append(("sslmode", "require"))
            value = urlunparse(parsed._replace(query=urlencode(query)))
    return value


seen = []
db_body = section_body("DB Setup")
if db_body is not None:
    chosen = database_url(db_body)
    if chosen is not None:
        env_name, value = chosen
        write_secret(env_name, f"{prefix}database-url", demo_database_url(env_name, value), seen)

trading = section_body("Trading App Configuration")
if trading is None:
    sys.stderr.write("error: # Trading App Configuration section not found\n")
    sys.exit(1)
for key, value in assignments(trading, "Trading App Configuration"):
    if value.strip() == "":
        sys.stderr.write(f"skip empty {key}\n")
        continue
    write_secret(key, prefix + key.lower().replace("_", "-"), value, seen)

if not seen:
    sys.stderr.write("error: no values to store\n")
    sys.exit(1)
sys.stdout.write("\n".join(seen) + "\n")
PY
)"

stored=0
while IFS=$'\t' read -r env_name secret_name; do
  [[ -n "$env_name" ]] || continue
  echo "Storing $env_name as $KV_NAME/$secret_name"
  az keyvault secret set "${AZ_SUBSCRIPTION_ARGS[@]}" \
    --vault-name "$KV_NAME" \
    --name "$secret_name" \
    --file "$workdir/$secret_name" \
    -o none
  stored=$((stored + 1))
done <<<"$manifest"

echo "Stored $stored secret(s) in $KV_NAME. Values were not printed."
