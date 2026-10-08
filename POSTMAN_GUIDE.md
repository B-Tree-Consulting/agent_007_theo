## Postman — agent-007-theo

### Import

1. Import `postman/environment.json` as an environment.
2. Import `postman/collection.json` as a collection.
3. Select the **agent-007-theo (local)** environment.

### Auth modes (test vs production)

The collection supports **both** local mock auth and real Entra tokens via `auth_mode`:

| Mode | Environment | Server | Behavior |
|------|-------------|--------|----------|
| **test** (default) | `auth_mode=test`, `auth_auto_mint=true` | `AUTH_TEST_MODE=true` | Pre-request auto-mints HS256 mock JWTs |
| **production** | `auth_mode=production`, `auth_auto_mint=false` | `AUTH_TEST_MODE=false` | Never mints; paste Entra JWTs manually |

Import **`postman/environment.json`**. For production Entra, change two variables in that same environment: `auth_mode=production`, `auth_auto_mint=false`, then paste your JWT into `access_token`.

**Production workflow:**

1. Select environment with `auth_mode=production`.
2. Paste your Entra management JWT into **`access_token`** (or **`management_token`** — they sync automatically).
3. Run **Setup → Validate production management token** (checks `/health/ready` and `/api/v1/bfa/catalog` with the same bearer).
4. Run **BFA → GET /api/v1/bfa/catalog (management)** — no mock mint, uses your token.

Runtime invoke in production also requires platform-minted **`de_token`** and **`capability_token`** (Postman cannot auto-generate those).

### AUTH_TEST_MODE auto-mint (test mode)

When the server runs with **`AUTH_TEST_MODE=true`** (see repo-root `.env`):

1. Set environment variable **`auth_auto_mint`** to **`true`** (default in `postman/environment.json`).
2. Run any request under **Setup** or **BFA** — the folder pre-request script mints mock JWTs and sets:
   - `management_token` — `AyDEO-Config-Admin`
   - `de_token` — `AyDEO-DE` for `bfa_test_de_id` (mock subject; dev/test only)
   - `capability_token` — grants all tools from the management catalog response

### BFA confirm test mode (kit v0.2.27)

Local `.env` sets **`BFA_CONFIRM_TEST_MODE=true`** (wired to `HostConfig.confirm_test_mode`). This is **dev/test only** — production CMS hosts must keep it **off** and require real AyDEO Chat handoff grants.

When enabled:

- Management catalog exposes `service.confirm_test_mode: true` (see **GET /api/v1/bfa/catalog (management)** test script).
- Confirm uses base `tool_name`, `invoke_phase="confirm"`, top-level `plan_token`, and flat base `inputs` — without `thread_id`, `handoff_invoke_grant`, or `approval_record_id`.
- A leftover `{tool}.confirm` `tool_name` is unknown-tool (**404**); use base tool + `invoke_phase="confirm"`.
- Capability validation, tool version checks, and input schema validation still apply.

### BFA invoke diagnostic mode (kit v0.2.14)

When **`AUTH_TEST_MODE=true`** (default locally), `invoke_diagnostic_mode` defaults **on** unless overridden by `BFA_INVOKE_DIAGNOSTIC_MODE=false`. Production must keep `AUTH_TEST_MODE=false` and diagnostic mode off.

### Production mode note

When **`auth_mode=production`**, the collection **does not** auto-mint tokens. Paste real Entra JWTs into `access_token` / `management_token`. Capability and DE runtime tokens must come from the AyDEO platform (DRIS mint / Chat).

When **`auth_mode=test`** (default), the collection auto-mints HS256 mock tokens and does not generate real Entra, DRIS capability, Chat grants, or approval proofs.

When enabled:

- Management and runtime catalogs expose `service.invoke_diagnostic_mode: true`.
- **`POST /api/v1/bfa/diagnostics/invoke-ping`** exercises invoke-plane auth (DE bearer + capability header) without cataloguing a diagnostic tool. Expect `{"status":"ok","diagnostic":"invoke_ping",...}`.
- When mode is off, the route returns **404** before auth (no 401 leak).

**Postman:** run **POST /api/v1/bfa/diagnostics/invoke-ping** after minting tokens (replaces the retired `bfa.health.ping` invoke smoke).

Without confirm test mode, confirm returns `403` — *confirm envelope is not valid for any hosted flow* — because Chat handoff proof is missing.

Or run **Setup → Mint AUTH_TEST_MODE tokens** once (hits public `GET /health` but only runs the mint script).

Script logic lives in the collection **pre-request scripts** (Setup, Health, and BFA folders). Edit `postman/collection.json` in Postman or in the repo — no build step.

**Refresh tokens:** set `auth_force_refresh` to `true` in the environment, then send any **Setup** or **BFA** request (or **GET /health/ready** after minting tokens via Setup).

**Disable auto-mint:** set `auth_auto_mint` to `false` and paste tokens manually.

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `base_url` | `http://localhost:8015` | Local compose API |
| `auth_mode` | `test` | `test` = auto-mint mocks; `production` = paste Entra JWTs |
| `auth_auto_mint` | `true` | Run pre-request JWT minting (test mode only) |
| `access_token` | (manual) | Production: paste Entra management JWT here (syncs to `management_token`) |
| `auth_test_mode` | `true` | Reminder: server must use AUTH_TEST_MODE |
| `bfa_test_de_id` | `00000000-0000-4000-8000-0000000000de` | Mock DE `sub` for auto-minted tokens (dev/test only) |
| `bfa_service_slug` | `agent-007-theo` | Capability JWT slug claim |
| `bfa_confirm_test_mode` | `true` | Reminder: server must use `BFA_CONFIRM_TEST_MODE=true` for local confirm |
| `bfa_invoke_diagnostic_mode` | `true` | Reminder: diagnostic route follows `AUTH_TEST_MODE` unless overridden |
| `management_token` | (auto) | Management Entra JWT mock |
| `de_token` | (auto) | Runtime DE Entra JWT mock |
| `capability_token` | (auto) | `X-AyDEO-Capability-Token` mock JWT |
| `auth_tokens_minted_at` | (auto) | Last mint timestamp |
| `plan_token` | (auto) | Set by order submit test scripts |

### Manual mint (Python)

Same helpers as pytest:

```bash
cd backend && PYTHONPATH=. python3 -c "
from src.shared.test_utils import create_config_admin_token, create_de_token
from src.config import get_settings
from src.host.facade import get_host_bfa
from src.host.testing.capability import catalog_tools_for_mock_capability, mint_mock_capability_token
get_settings.cache_clear()
de_id = get_settings().bfa_test_de_id
facade = get_host_bfa()
tools = catalog_tools_for_mock_capability(facade.catalog(), code_tools=facade.tools())
print('management_token:', create_config_admin_token())
print('de_token:', create_de_token(de_id))
print('capability_token:', mint_mock_capability_token(de_id, tools))
"
```

### Collection folders

- **Setup** — test token refresh; production management token validation
- **Health** — `GET /health` (public, no pre-request script), `GET /health/ready` (management bearer; mint tokens via **Setup** first)
- **BFA** — management/runtime catalog, `POST /api/v1/bfa/diagnostics/invoke-ping` (test mode)

### Optional AyDEO Audit (external service)

This compose stack does **not** run the audit service. To emit real audit events during Postman invokes, run [`b-tree-aydeo-audit`](https://github.com/B-Tree-Consulting/b-tree-aydeo-audit) separately and set all three repo-root `.env` variables:

- `AYDEO_AUDIT_URL` — e.g. `http://host.docker.internal:8003`
- `OUTBOX_INTERNAL_SERVICE_TOKEN` (or SDK alias `AYDEO_INTERNAL_SERVICE_TOKEN`)
- `AYDEO_AUDIT_SPOOL_PATH` — e.g. `/tmp/audit-spool` (ephemeral inside Docker unless you mount a volume)

Partial configuration fails fast at startup. With audit enabled, successful invoke paths produce outbox events; `digital_employee_id` is capability JWT `de_id` (`digital_employees.id`), not the `de_token` Entra subject, and audit `action_domain` is ``{BFA_SERVICE_SLUG}.{kit domain}``. Scoped tool invokes require **`case_id`** (open case UUID the digital employee may access).
