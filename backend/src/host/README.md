# Host

HTTP, auth, and AyDEO platform wiring for this agentic app. Trading tools register from `src.theo` through `register_sample_modules()` in `factory.py`.

## Responsibilities

| Module | Role |
| --- | --- |
| `factory.py` | Builds `AydeoHostBlueprint` via kit `build_aydeo_host`, registers domain modules, wires `HostConfig` |
| `case_state_adapter.py` | `AydeoCaseStateAdapter` — CMS `GET /api/v1/internal/cms/cases/{id}/invoke-facts` via `AydeoCmsInternalClient` (authoritative `assignee_subject` / `consulting_entitled`) |
| `catalog_scope.py` | SR_10 `CatalogScopeHelpers` — all registered tools require `active_open_case` |
| `case_lifecycle.py` | `is_case_open()` helper (P1 canonical lifecycle) |
| `facade.py` | BFA shell — trading tools attach via registration hooks |
| `api.py` / `http.py` | FastAPI routes: health, catalog, invoke, diagnostics |
| `adapters.py` | Test-mode management/runtime/capability validators (pytest patches kit adapters) |
| `auth.py`, `capability*.py` | Capability JWT binding for invoke plane |
| `schemas.py` | Invoke request/response DTOs |

Test-mode invoke diagnostic: `POST /api/v1/bfa/diagnostics/invoke-ping` when `invoke_diagnostic_mode` is on (see repo-root `README.md`). Diagnostic path validates runtime identity only — **no** `case_id`.

## Production assembly (`build_aydeo_host`)

`get_host_blueprint()` calls kit `build_aydeo_host(...)` with:

- Platform adapters from `build_platform_adapters(AydeoPlatformSettings)` (Entra, DRIS capability, Chat grants, approval proof)
- `AydeoCaseStateAdapter` + `AYDEO_CMS_BASE_URL` (required when `AUTH_TEST_MODE=false`) + `AYDEO_PLATFORM_INTERNAL_SERVICE_TOKEN` (resolve-time)
- `catalog_scope` from all registered tool names (SR_10: `active_open_case`)
- `catalog_metadata_provider=CatalogMetadataProvider()` as an extra `build_aydeo_host` kwarg (not an adapter override)

**Test mode:** same `build_aydeo_host` path with dummy platform settings. Pytest patches `bfa.aydeo_host.platform.factory.build_platform_adapters` to inject validators from `adapters.py` (see `tests/host/platform_adapter_mocks.py`). Kit **v0.2.27** permits three named identity/capability adapter slots (since v0.2.26); policies and Lane A/B stay sealed. This host does not pass those slots — patch `build_platform_adapters` instead.

## Case/hold parity harness

Frozen parity vectors run through `build_aydeo_host` in `tests/host/case_policy_harness.py` with:

- **`CanaryBFA`** — isolated BFA in `backend/tests/fixtures/case_policy_parity/`
- **`ScenarioCaseStateAdapter`** — harness-only facts for `hold_fail` vectors
- **`AydeoCaseStateAdapter`** + mocked `AydeoCmsInternalClient.get_case_invoke_facts` for open/closed/held/unknown/scope_fail
- Platform mocks — harness patches `build_platform_adapters` before assembly

Not used by `get_host_blueprint()`, `warm_host_on_startup()`, or HTTP routes.

## HTTP invoke and `case_id`

All scoped business-tool invokes on `POST /api/v1/bfa/invoke` must include `case_id` (UUID of an open case the caller may access). Pytest supplies a default open-case CMS mock and `test_open_case_id` fixture.

## Host-trusted invoke-facts (kit v0.2.27)

Kit `CaseWorkAuthorityPolicy` matches `facts.assignee_subject` to the invoke Entra subject and uses `consulting_entitled` plus a non-blank `thread_id` for consulting reads. Production `AydeoCaseStateAdapter` consumes `AydeoCmsInternalClient.get_case_invoke_facts` (`GET /api/v1/internal/cms/cases/{id}/invoke-facts` with `X-AyDEO-Internal-Service-Token`). Public `GET /api/v1/cases/{id}` is leftover ABAC and is **not** used for authority.

`assignee_subject` is never copied from `invoking_subject`. Consulting allow still needs the CMS boolean **and** a non-blank `thread_id`. Missing CMS URL or internal token, and client 401/403/503/transport, map to `dependency_failure="scope_unavailable"` (kit Scope owns 503).

Pytest injects a **test-only** wrapper (`tests/host/case_identity_wrapper.py`) by patching the factory adapter constructor before blueprint cache. The wrapper `dataclasses.replace`s identity fields after delegating to the real adapter. The same wrapper supplies `de-123` for CMS-backed parity vectors. Synthetic overlay facts are **not** live-CMS proof. HTTP tests marked `case_identity(production=True)` mock invoke-facts without the overlay.

## Startup warm-up

The kit BFA shell binds tool specs at construction. `get_host_bfa()` is cached. If it is built before `register_theo_tools` attaches, catalog and invoke see zero tools until the process restarts.

To avoid intermittent empty catalog on cold start:

1. **`warm_host_on_startup()`** in `main.py` lifespan (before serving traffic) calls `get_host_blueprint()` so tools register and singletons cache in a fixed order.
2. **`get_host_bfa()`** always runs `register_sample_modules()` first and rebuilds the cache if a stale empty instance is detected.
3. **`register_sample_modules()`** clears the facade cache when the trading tools are first attached (the kit binds tools at BFA construction).

Do not call `_get_host_bfa_cached()` directly outside tests. Route handlers should use `get_host_blueprint()` before any tool lookup.

**Production audit identity:** kit v0.2.26 stamps generic BFA / ActionStepKit `digital_employee_id` from trusted capability `de_id` (`CallContext.digital_employee_id`). Constructor `employee_id` is episodic memory only — not the audit id. The host `RuntimeDeOutbox` must not overwrite that field with Entra `sub`/`oid`; missing `de_id` is omit/null. `wrap_runtime_identity_validator()` is a pass-through (Entra subject is not the audit id). `RuntimeDeOutbox` still rewrites audit `action_domain` to ``{BFA_SERVICE_SLUG}.{kit domain}`` (e.g. `agent-007-theo.domain` for ActionKit events, `agent-007-theo.bfa` for BFA deferral events). Kit v0.2.27 puts `correlation_id` on `OutboxEvent`. The wrapper fills it from the invoke body only when the kit left it blank, and it passes `invoke_phase`, `tool_kind`, `authorization_id`, and `authorization_source` through unchanged. Audit SDK 0.1.2 copies those four fields onto the ingest envelope.

The blueprint accepts a **`catalog_metadata_provider`** for `operating_context` on catalog responses.

## Risk, execute context, and deferral (HTTP)

On the **HTTP invoke plane**, capability JWT `risk` is combined with catalog tool `risk` to produce `effective_risk`. That drives submit deferral assertions:

| Effective profile | Submit assertion | This app |
| --- | --- | --- |
| Low | runs in that invoke | `place_market_equity_order` and the other low-risk place tools |
| High | `needs-superior-defer` | `place_large_*_equity_order` |

`execute_context` tells AyDEO Chat whether the requestor must be in session (`requestor_in_session`) or the DE may run headless (`de_autonomous`). It does **not** replace risk — both appear in the catalog.

Facade-only tests (`invoke_with_context` without a capability JWT) treat high-risk tools as medium for deferral. HTTP tests assert superior deferral.

Local **`BFA_CONFIRM_TEST_MODE=true`** bypasses Chat handoff on **confirm only**; submit deferral still follows capability risk.

## Display metadata

DE-facing copy comes from three places:

1. **Catalog tool `description`** — passed to `@host_cls.query` / `@host_cls.action_factory`.
2. **`operating_context`** — optional string from `CatalogMetadataProvider.operating_context()` on catalog responses.
3. **Input JSON Schema** — pydantic `Field(description=…)` on action/query input models; exported to catalog and validated on invoke.

Action **guard metadata** (`assert_that.pre` ids and messages) is exported via `handle.export_guards()` for catalog consumers.

## Preflight and invariant failures

Before submit reaches deferral, coordinated actions run **guards**. Failed guards return invoke `status: failed` **without** a `plan_token` (preflight failure, not confirmation deferral).

Trading-tool guards raise domain errors that surface as failed invokes or step failures on confirm. See `src/theo/errors.py`.

Distinguish:

- **Preflight failed** — bad inputs or a guard assertion failed, with no `plan_token`
- **Deferral** — `status: failed` with `outputs.plan_token` and assertion `needs-superior-defer`
- **Confirm success** — `status: succeeded` with the action outputs
