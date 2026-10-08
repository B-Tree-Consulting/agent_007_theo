#!/usr/bin/env bash
# Bootstrap: copy this BFA host sample into a new (empty) git repository,
# rename service identity, and optionally remove the pizza demo module.
#
# Interactive:
#   ./scripts/bootstrap-new-host.sh
# Non-interactive (CI):
#   ./scripts/bootstrap-new-host.sh --non-interactive --target DIR --repo-name NAME \
#     --service-slug SLUG [--strip-pizza] [--strip-postgres] [--no-commit]
#
# Prerequisites: rsync, python3, target directory (empty or .git-only is ideal).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_ROOT=""

TEMPLATE_REPO_NAME="b-tree-bfa-host-sample"
TEMPLATE_SLUG="bfa-host-sample"
TEMPLATE_PYPROJECT="bfa-host-sample-backend"
TEMPLATE_VOLUME_PREFIX="bfa_host_sample"
TEMPLATE_POSTMAN_ENV_ID="bfa-host-sample-local"
TEMPLATE_API_TITLE="AyDEO BFA Host Sample API"
TEMPLATE_POSTMAN_NAME="AyDEO BFA Host Sample"
TEMPLATE_README_H1="AyDEO BFA Host Sample"

INVOCATION_CWD="$(pwd)"

# --- helpers -----------------------------------------------------------------

resolve_target_dir() {
  local input="$1"
  local base name root candidate resolved

  if [[ "$input" == /* ]]; then
    printf '%s' "$input"
    return 0
  fi

  base="$(dirname "$input")"
  name="$(basename "$input")"

  for root in "$INVOCATION_CWD" "$(cd "$TEMPLATE_ROOT/.." && pwd)" "$TEMPLATE_ROOT"; do
    if [[ "$base" == "." ]]; then
      candidate="${root}/${name}"
    else
      resolved="$(cd "$root" && cd "$base" && pwd)" || continue
      candidate="${resolved}/${name}"
    fi
    if [[ -d "$candidate" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done

  # Default location for create: cwd first, then sibling of sample repo.
  if [[ "$base" == "." ]]; then
    if [[ -d "$INVOCATION_CWD" ]]; then
      printf '%s/%s' "$INVOCATION_CWD" "$name"
    else
      printf '%s/%s' "$(cd "$TEMPLATE_ROOT/.." && pwd)" "$name"
    fi
  else
    resolved="$(cd "$INVOCATION_CWD" && cd "$base" && pwd)" || resolved="$(cd "$TEMPLATE_ROOT/.." && cd "$base" && pwd)"
    printf '%s/%s' "$resolved" "$name"
  fi
}

prompt() {
  local message="$1"
  local default="${2:-}"
  local reply
  if [[ -n "$default" ]]; then
    read -r -p "${message} [${default}]: " reply
    printf '%s' "${reply:-$default}"
  else
    read -r -p "${message}: " reply
    printf '%s' "$reply"
  fi
}

prompt_yes_no() {
  local message="$1"
  local default="${2:-n}"
  local hint="y/N"
  [[ "$default" == "y" ]] && hint="Y/n"
  local reply
  read -r -p "${message} [${hint}]: " reply
  reply="${reply:-$default}"
  [[ "$reply" =~ ^[Yy] ]]
}

slug_to_volume_prefix() {
  printf '%s' "$1" | tr '-' '_'
}

validate_slug() {
  local slug="$1"
  if [[ ! "$slug" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
    echo "Invalid slug '${slug}': use lowercase alphanumeric with hyphens (e.g. licence-management-bfa)." >&2
    return 1
  fi
}

validate_repo_name() {
  local name="$1"
  if [[ ! "$name" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Invalid repo name '${name}': use letters, digits, '.', '_', or '-' only." >&2
    return 1
  fi
}

# Re-prompt until validator succeeds. Prints the valid value on stdout.
prompt_until_valid() {
  local message="$1"
  local default="$2"
  local validator="$3"
  local value
  while true; do
    value="$(prompt "$message" "$default")"
    if [[ -z "$value" ]]; then
      echo "A value is required." >&2
      continue
    fi
    if "$validator" "$value"; then
      printf '%s' "$value"
      return 0
    fi
    echo "Please try again." >&2
  done
}

# Prints "owner/repo" from git remote origin, or returns non-zero.
detect_git_remote() {
  local dir="$1"
  local url owner repo

  [[ -d "$dir/.git" ]] || return 1
  url="$(git -C "$dir" config --get remote.origin.url 2>/dev/null)" || return 1
  url="${url%.git}"

  if [[ "$url" =~ github\.com[:/]([^/]+)/([^/]+)$ ]]; then
    owner="${BASH_REMATCH[1]}"
    repo="${BASH_REMATCH[2]}"
    printf '%s/%s' "$owner" "$repo"
    return 0
  fi

  return 1
}

count_target_entries() {
  local target="$1"
  find "$target" -mindepth 1 -maxdepth 1 \
    ! -name '.git' \
    ! -name '.DS_Store' \
    2>/dev/null | wc -l | tr -d ' '
}

replace_in_tree() {
  local root="$1"
  local old="$2"
  local new="$3"
  local esc_old esc_new
  if [[ "$old" == "$new" ]]; then
    return 0
  fi
  # Escape sed delimiters; LC_ALL=C avoids macOS "illegal byte sequence" on binary leftovers.
  esc_old="$(printf '%s' "$old" | sed 's/[\/&]/\\&/g')"
  esc_new="$(printf '%s' "$new" | sed 's/[\/&]/\\&/g')"
  while IFS= read -r -d '' file; do
    # -I: skip binary files (e.g. .coverage that may still be present in a dirty target).
    if LC_ALL=C grep -Iq -- "$old" "$file" 2>/dev/null; then
      if [[ "$(uname -s)" == "Darwin" ]]; then
        LC_ALL=C sed -i '' "s/${esc_old}/${esc_new}/g" "$file"
      else
        LC_ALL=C sed -i "s/${esc_old}/${esc_new}/g" "$file"
      fi
    fi
  done < <(
    find "$root" -type f \
      ! -path '*/.git/*' \
      ! -path '*/.venv/*' \
      ! -path '*/backend/vendor/*' \
      ! -path '*/.pytest_cache/*' \
      ! -path '*/.mypy_cache/*' \
      ! -path '*/.ruff_cache/*' \
      ! -path '*/__pycache__/*' \
      ! -name '*.pyc' \
      ! -name '*.pyo' \
      ! -name '*.png' \
      ! -name '*.jpg' \
      ! -name '*.jpeg' \
      ! -name '*.gif' \
      ! -name '*.webp' \
      ! -name '*.ico' \
      ! -name '*.pdf' \
      ! -name '.coverage' \
      ! -name '.coverage.*' \
      ! -name '.DS_Store' \
      -print0
  )
}

strip_pizza_sample() {
  local root="$1"
  echo "Removing pizza sample (repo-root strip)..."
  python3 "$SCRIPT_DIR/bootstrap_strip_pizza.py" "$root"
  echo "Note: Register domain tools in register_sample_modules() before docker compose up"
  echo "      (host hard-fails startup when no tools are registered)."
  echo "Note: Test-only canary tools live under tests/ and must not be registered in production."
}

strip_postgres_sample() {
  local root="$1"
  echo "Removing local Postgres from docker-compose / settings..."
  python3 "$SCRIPT_DIR/bootstrap_strip_postgres.py" "$root"
  echo "Note: DATABASE_URL is optional until your domain needs a database."
  echo "      Re-add the postgres service + migrations when you introduce SQL-backed stores."
}

print_summary() {
  local target="$1"
  local repo_name="$2"
  local slug="$3"
  local stripped="$4"
  local stripped_sql="$5"
  local did_commit="$6"
  local target_label
  local step_n=1
  target_label="$(basename "$target")"

  cat <<EOF

================================================================================
Bootstrap complete
================================================================================
New host repo    : B-Tree-Consulting/${repo_name}
Local directory  : ${target_label}
Service slug     : ${slug}
Pizza sample     : $([[ "$stripped" == "yes" ]] && echo "removed — register domain tools before compose up; tests use test-only canaries" || echo "kept (see samples/pizza/README.md)")
Postgres         : $([[ "$stripped_sql" == "yes" ]] && echo "removed from compose (optional until domain needs DB)" || echo "kept (docker-compose postgres + DATABASE_URL)")

Next steps
----------
EOF

  echo "${step_n}. cd into your target repo (${target_label})"
  step_n=$((step_n + 1))

  if [[ "$stripped" == "yes" ]]; then
    echo "${step_n}. Wire domain tools in backend/src/host/factory.py → register_sample_modules()"
    echo "   (and catalog_metadata_provider on both build_aydeo_host calls)."
    echo "   Host startup hard-fails until at least one tool is registered — do this before compose up."
    step_n=$((step_n + 1))
  fi

  echo "${step_n}. cp backend/.env.example .env and review:"
  step_n=$((step_n + 1))
  echo "   - GITHUB_TOKEN (private kit + aydeo-cms-client git install)"
  echo "   - BFA_SERVICE_SLUG (${slug})"
  if [[ "$stripped_sql" != "yes" ]]; then
    echo "   - POSTGRES_PASSWORD and DATABASE_URL"
  else
    echo "   - DATABASE_URL / POSTGRES_* only when you re-enable Postgres for domain stores"
  fi
  cat <<EOF
   - AYDEO_CMS_BASE_URL (case/hold; e.g. http://host.docker.internal:8000 for sibling aydeo_be)
   - IDP_ISSUER, IDP_AUDIENCE (and APP_ID / AYDEO_ENTRA_APP_ID as needed)
   - DRIS_CAPABILITY_JWKS_URI, DRIS_CAPABILITY_ISSUER
   - AYDEO_CHAT_BASE_URL, AYDEO_CHAT_INTERNAL_TOKEN
   - AYDEO_PLATFORM_APPROVAL_PROOF_JWKS_URL, AYDEO_PLATFORM_APPROVAL_PROOF_ISSUER
   - For real platform demos: AUTH_TEST_MODE=false and BFA_CONFIRM_TEST_MODE=false
   - Scoped invokes require case_id (open CMS case UUID)
EOF

  echo "${step_n}. docker compose up --build"
  step_n=$((step_n + 1))
  if [[ "$stripped_sql" != "yes" ]]; then
    echo "${step_n}. docker compose run --rm backend alembic upgrade head"
    step_n=$((step_n + 1))
  fi
  cat <<EOF
${step_n}. curl http://localhost:8005/health
$((step_n + 1)). Register external host slug '${slug}' in AyDEO Config
$((step_n + 2)). Open a spoke Task in ${repo_name} linked to your Hub Story

Developer docs in the new repo:
  - README.md (\"Copy this for a new demo BFA\")
  - backend/src/host/README.md
  - backend/.env.example / backend/.env.demo.example
$([[ "$stripped" != "yes" ]] && echo "  - backend/src/samples/pizza/README.md")

Git
---
$(
  if [[ "$did_commit" == "yes" ]]; then
    echo "Initial commit created. Push when ready:"
    echo "  git push -u origin main"
  elif [[ -d "${target}/.git" ]]; then
    echo "Review changes, then commit and push:"
    echo "  cd ${target}"
    echo "  git add ."
    echo '  git commit -m "Bootstrap from BFA host sample template"'
    echo "  git push -u origin main"
  else
    echo "No .git in target — initialize if needed:"
    echo "  cd ${target} && git init && git remote add origin git@github.com:B-Tree-Consulting/${repo_name}.git"
  fi
)
================================================================================
EOF
}

# --- CLI ---------------------------------------------------------------------

usage() {
  cat <<'EOF'
Usage:
  ./scripts/bootstrap-new-host.sh
  ./scripts/bootstrap-new-host.sh --non-interactive --target DIR --repo-name NAME --service-slug SLUG
      [--strip-pizza] [--strip-postgres] [--no-commit]

--strip-postgres requires --strip-pizza.
EOF
}

NON_INTERACTIVE="no"
TARGET_INPUT=""
REPO_NAME_FLAG=""
SERVICE_SLUG_FLAG=""
STRIP_PIZZA="no"
STRIP_SQL="no"
NO_COMMIT="no"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --non-interactive) NON_INTERACTIVE="yes"; shift ;;
    --target)
      TARGET_INPUT="${2:-}"
      shift 2
      ;;
    --repo-name)
      REPO_NAME_FLAG="${2:-}"
      shift 2
      ;;
    --service-slug)
      SERVICE_SLUG_FLAG="${2:-}"
      shift 2
      ;;
    --strip-pizza) STRIP_PIZZA="yes"; shift ;;
    --strip-postgres) STRIP_SQL="yes"; shift ;;
    --no-commit) NO_COMMIT="yes"; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "$STRIP_SQL" == "yes" && "$STRIP_PIZZA" != "yes" ]]; then
  echo "error: --strip-postgres is valid only with --strip-pizza" >&2
  exit 1
fi

if [[ "$NON_INTERACTIVE" == "yes" ]]; then
  if [[ -z "$TARGET_INPUT" || -z "$REPO_NAME_FLAG" || -z "$SERVICE_SLUG_FLAG" ]]; then
    echo "error: --non-interactive requires --target, --repo-name, and --service-slug" >&2
    exit 1
  fi
  if ! validate_repo_name "$REPO_NAME_FLAG"; then
    exit 1
  fi
  if ! validate_slug "$SERVICE_SLUG_FLAG"; then
    exit 1
  fi
fi

resolve_template_root() {
  if [[ -n "${AYDEO_BOOTSTRAP_TEMPLATE_ROOT:-}" ]]; then
    (cd "$AYDEO_BOOTSTRAP_TEMPLATE_ROOT" && pwd)
    return
  fi
  git -C "$SCRIPT_DIR/.." rev-parse --show-toplevel 2>/dev/null
}

if ! TEMPLATE_ROOT="$(resolve_template_root)"; then
  echo "error: run this script from inside the b-tree-bfa-host-sample repository" >&2
  exit 1
fi

echo ""
echo "AyDEO BFA host — bootstrap into a new repository"
echo ""

if [[ "$NON_INTERACTIVE" == "yes" ]]; then
  TARGET_DIR="$(resolve_target_dir "$TARGET_INPUT")"
  if [[ ! -d "$TARGET_DIR" ]]; then
    mkdir -p "$TARGET_DIR"
  fi
  TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"
  if [[ "$TARGET_DIR" == "$TEMPLATE_ROOT" ]]; then
    echo "error: target must not be the template repository itself" >&2
    exit 1
  fi
  REPO_NAME="$REPO_NAME_FLAG"
  SERVICE_SLUG="$SERVICE_SLUG_FLAG"
  TARGET_LABEL="$(basename "$TARGET_DIR")"
else
  echo "This copies the sample repo (B-Tree-Consulting/${TEMPLATE_REPO_NAME}) from your"
  echo "local clone into another directory — typically a clone of your new empty GitHub repo."
  echo ""
  echo "Tip: use a path relative to where you run this script, e.g. b-tree-aydeo-demo-bfa_1"
  echo "     or ../b-tree-aydeo-demo-bfa_1 when run from inside the sample repo."
  echo ""

  TARGET_INPUT="$(prompt "Path to your empty target repo" "")"
  if [[ -z "$TARGET_INPUT" ]]; then
    echo "error: target path is required" >&2
    exit 1
  fi

  TARGET_DIR="$(resolve_target_dir "$TARGET_INPUT")"

  if [[ ! -d "$TARGET_DIR" ]]; then
    echo ""
    echo "Could not find: ${TARGET_INPUT}"
    echo "  tried: ${TARGET_DIR}"
    if prompt_yes_no "Create that directory?" "y"; then
      mkdir -p "$TARGET_DIR"
    else
      exit 1
    fi
  fi

  TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"

  if [[ "$TARGET_DIR" == "$TEMPLATE_ROOT" ]]; then
    echo "error: target must not be the template repository itself" >&2
    exit 1
  fi

  ENTRY_COUNT="$(count_target_entries "$TARGET_DIR")"
  if [[ "$ENTRY_COUNT" -gt 0 ]]; then
    echo ""
    echo "Warning: target contains ${ENTRY_COUNT} item(s) besides .git (will be merged/overwritten by rsync)."
    find "$TARGET_DIR" -mindepth 1 -maxdepth 1 ! -name '.git' ! -name '.DS_Store' 2>/dev/null | head -10
    if ! prompt_yes_no "Continue anyway?" "n"; then
      exit 1
    fi
  fi

  TARGET_LABEL="$(basename "$TARGET_DIR")"
  GITHUB_REMOTE=""
  if GITHUB_REMOTE="$(detect_git_remote "$TARGET_DIR")"; then
    REPO_NAME="${GITHUB_REMOTE##*/}"
    echo ""
    echo "Detected git repository:"
    echo "  remote origin : ${GITHUB_REMOTE}"
    echo "  local folder  : ${TARGET_LABEL}"
    if ! prompt_yes_no "Bootstrap BFA host template into this repo?" "y"; then
      echo "Aborted."
      exit 0
    fi
  else
    echo ""
    echo "Target folder: ${TARGET_LABEL}"
    if [[ -d "$TARGET_DIR/.git" ]]; then
      echo "(git repo present, but no GitHub origin remote detected)"
    fi
    REPO_NAME="$(prompt_until_valid "GitHub repository name (B-Tree-Consulting/…)" "$TARGET_LABEL" validate_repo_name)"
    if ! prompt_yes_no "Bootstrap into ${TARGET_LABEL}?" "y"; then
      echo "Aborted."
      exit 0
    fi
  fi

  DEFAULT_SLUG="$(printf '%s' "$REPO_NAME" | tr '_' '-' | tr '[:upper:]' '[:lower:]')"
  SERVICE_SLUG="$(prompt_until_valid "BFA service slug — AyDEO Config external host (Enter to accept default)" "$DEFAULT_SLUG" validate_slug)"

  echo ""
  echo "Derived identifiers:"
  echo "  pyproject name   : ${SERVICE_SLUG}-backend"
  echo "  docker volume    : $(slug_to_volume_prefix "$SERVICE_SLUG")_postgres_data"
  echo "  postman env id   : ${SERVICE_SLUG}-local"
  echo ""

  if prompt_yes_no "Remove pizza sample? (then wire domain tools before compose up — startup hard-fails with no tools)" "n"; then
    STRIP_PIZZA="yes"
    if prompt_yes_no "Also remove Postgres from docker compose? (no local SQL until your domain needs a DB)" "y"; then
      STRIP_SQL="yes"
    fi
  fi

  echo ""
  echo "Plan — copy sample template into your repo and rename identifiers:"
  echo "  GitHub repo    : B-Tree-Consulting/${REPO_NAME}"
  echo "  Local folder   : ${TARGET_LABEL}"
  echo "  Service slug   : ${SERVICE_SLUG}"
  echo "  Strip pizza    : ${STRIP_PIZZA}"
  echo "  Strip Postgres : ${STRIP_SQL}"
  echo ""

  if ! prompt_yes_no "Proceed? (copies files into ${TARGET_LABEL})" "y"; then
    echo "Aborted — no files changed."
    exit 0
  fi
fi

VOLUME_PREFIX="$(slug_to_volume_prefix "$SERVICE_SLUG")"
PYPROJECT_NAME="${SERVICE_SLUG}-backend"
POSTMAN_ENV_ID="${SERVICE_SLUG}-local"
GREENFIELD_DB="${VOLUME_PREFIX}_greenfield_test"
API_TITLE="AyDEO ${SERVICE_SLUG} API"
POSTMAN_NAME="AyDEO ${SERVICE_SLUG}"

echo "Copying template files (rsync)..."
# Copies the local working tree (not git-only). Do not copy credentials, local MCP, or .knowledge.
rsync -a \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='.env' \
  --exclude='.env.local' \
  --exclude='.env.demo' \
  --exclude='.knowledge' \
  --exclude='.cursor/mcp.json' \
  --exclude='backend/vendor' \
  --exclude='.tmp-*' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache' \
  --exclude='.mypy_cache' \
  --exclude='.ruff_cache' \
  --exclude='.coverage' \
  --exclude='.coverage.*' \
  --exclude='.DS_Store' \
  --exclude='scripts/.demo-last-bfa-host-tag' \
  --exclude='.secrets' \
  "${TEMPLATE_ROOT}/" "${TARGET_DIR}/"

if [[ -f "${TEMPLATE_ROOT}/.secrets/README.md" ]]; then
  mkdir -p "${TARGET_DIR}/.secrets"
  cp "${TEMPLATE_ROOT}/.secrets/README.md" "${TARGET_DIR}/.secrets/README.md"
fi

# rsync excludes local vendor kits; keep an empty dir so Docker COPY backend/vendor succeeds.
mkdir -p "${TARGET_DIR}/backend/vendor"
: > "${TARGET_DIR}/backend/vendor/.gitkeep"

echo "Renaming template identifiers..."
# Longest / most specific replacements first.
replace_in_tree "$TARGET_DIR" "$TEMPLATE_API_TITLE" "$API_TITLE"
replace_in_tree "$TARGET_DIR" "$TEMPLATE_POSTMAN_NAME" "$POSTMAN_NAME"
replace_in_tree "$TARGET_DIR" "$TEMPLATE_README_H1" "$POSTMAN_NAME"
replace_in_tree "$TARGET_DIR" "$TEMPLATE_REPO_NAME" "$REPO_NAME"
replace_in_tree "$TARGET_DIR" "$TEMPLATE_PYPROJECT" "$PYPROJECT_NAME"
replace_in_tree "$TARGET_DIR" "${TEMPLATE_VOLUME_PREFIX}_greenfield_test" "$GREENFIELD_DB"
replace_in_tree "$TARGET_DIR" "${TEMPLATE_VOLUME_PREFIX}_postgres_data" "${VOLUME_PREFIX}_postgres_data"
replace_in_tree "$TARGET_DIR" "$TEMPLATE_POSTMAN_ENV_ID" "$POSTMAN_ENV_ID"
replace_in_tree "$TARGET_DIR" "$TEMPLATE_SLUG" "$SERVICE_SLUG"

if [[ "$STRIP_PIZZA" == "yes" ]]; then
  strip_pizza_sample "$TARGET_DIR"
fi
if [[ "$STRIP_SQL" == "yes" ]]; then
  strip_postgres_sample "$TARGET_DIR"
fi

DID_COMMIT="no"
if [[ "$NON_INTERACTIVE" != "yes" && "$NO_COMMIT" != "yes" && -d "${TARGET_DIR}/.git" ]]; then
  if prompt_yes_no "Create initial git commit in target repo?" "y"; then
    (
      cd "$TARGET_DIR"
      git add .
      if git diff --cached --quiet; then
        echo "Nothing to commit (working tree unchanged)."
      else
        git commit -m "Bootstrap from BFA host sample template

Service slug: ${SERVICE_SLUG}
Source: B-Tree-Consulting/${TEMPLATE_REPO_NAME}"
        DID_COMMIT="yes"
      fi
    )
  fi
fi

print_summary "$TARGET_DIR" "$REPO_NAME" "$SERVICE_SLUG" "$STRIP_PIZZA" "$STRIP_SQL" "$DID_COMMIT"
