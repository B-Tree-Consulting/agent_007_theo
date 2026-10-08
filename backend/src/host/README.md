# Host template core

Keep this package when adapting the repository for a production BFA host. Sample domain code lives under `src/samples/` and is **optional** — remove it without touching this tree.

## Responsibilities

| Module | Role |
| --- | --- |
| `factory.py` | Builds `AydeoHostBlueprint` via kit `build_aydeo_host`, registers domain modules, wires `HostConfig` |
| `case_state_adapter.py` | `AydeoCaseStateAdapter` — CMS `GET /api/v1/internal/cms/cases/{id}/invoke-facts` via `AydeoCmsInternalClient` (authoritative `assignee_subject` / `consulting_entitled`) |
| `catalog_scope.py` | SR_10 `CatalogScopeHelpers` — all registered tools require `active_open_case` |
| `case_lifecycle.py` | `is_case_open()` helper (P1 canonical lifecycle) |
| `facade.py` | `HostSampleBFA` shell — business tools attach via registration hooks |
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

## Case/hold parity harness (sample#23)

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

## Must not depend on

Anything under `src/samples/`. The domain sample registers **into** the host via `register_sample_modules()` in `factory.py`; the host package never imports sample modules directly except through that hook.

## Registration hook (domain swap)

Domain swap is **only** these two seams — do not change case adapter, catalog scope, or platform adapter assembly:

1. **`register_sample_modules()`** — call your `register_*_tools(HostSampleBFA)` (idempotent).
2. **`catalog_metadata_provider=`** on **both** `build_aydeo_host(...)` calls in `_assemble_host_blueprint()` — your provider or omit.

```python
def register_sample_modules() -> None:
    """Lazy-register domain tools (domain sample today)."""
    from src.host.facade import HostSampleBFA, _get_host_bfa_cached
    from src.samples.domain.bootstrap import register_domain_tools

    if register_domain_tools(HostSampleBFA):
        # BFA binds class tool specs at construction; drop a stale empty cached instance.
        _get_host_bfa_cached.cache_clear()
```

After domain strip (or a empty stub), **wire tools before `docker compose up`**: `get_host_bfa()` / `warm_host_on_startup()` **hard-fail** when no tools are registered.

Leave `get_host_bfa()`, `AydeoCaseStateAdapter`, `build_catalog_scope`, and production `AydeoPlatformSettings` wiring unchanged.

## Startup warm-up (Docker / uvicorn)

The kit BFA shell **binds tool specs at construction**. `get_host_bfa()` is cached (`@lru_cache`); if it is built before sample tools attach to `HostSampleBFA`, catalog and invoke see **zero tools** until process restart.

To avoid intermittent empty catalog on cold start:

1. **`warm_host_on_startup()`** in `main.py` lifespan (before serving traffic) calls `get_host_blueprint()` so tools register and singletons cache in a fixed order.
2. **`get_host_bfa()`** always runs `register_sample_modules()` first and rebuilds the cache if a stale empty instance is detected.
3. **`register_sample_modules()`** clears the facade cache when domain tools are first attached (kit binds tools at BFA construction).

Do not call `_get_host_bfa_cached()` directly outside tests. Route handlers should use `get_host_blueprint()` before any tool lookup.

**Production audit identity:** kit v0.2.26 stamps generic BFA / ActionStepKit `digital_employee_id` from trusted capability `de_id` (`CallContext.digital_employee_id`). Constructor `employee_id` is episodic memory only — not the audit id. The host `RuntimeDeOutbox` must not overwrite that field with Entra `sub`/`oid`; missing `de_id` is omit/null. `wrap_runtime_identity_validator()` is a pass-through (Entra subject is not the audit id). `RuntimeDeOutbox` still rewrites audit `action_domain` to ``{BFA_SERVICE_SLUG}.{kit domain}`` (e.g. `agent-007-theo.domain` for ActionKit events, `agent-007-theo.bfa` for BFA deferral events). Kit v0.2.27 puts `correlation_id` on `OutboxEvent`. The wrapper fills it from the invoke body only when the kit left it blank, and it passes `invoke_phase`, `tool_kind`, `authorization_id`, and `authorization_source` through unchanged. Audit SDK 0.1.2 copies those four fields onto the ingest envelope.

The blueprint also accepts a **`catalog_metadata_provider`** (today `CatalogMetadataProvider`) for `operating_context` copy on catalog responses. Swap this when you remove domain.

## Adding your domain module

Follow the domain sample layout as a reference (`src/samples/<domain>/README.md`). Minimum steps:

### 1. Create a domain package

```text
backend/src/your_domain/
  bootstrap.py       # register_your_tools(host_cls) — idempotent
  catalog_metadata.py  # optional CatalogMetadataProvider
  schemas/           # pydantic input/output models (Field descriptions!)
  queries/           # @host_cls.query tools
  actions/           # coordinated_action + @host_cls.action_factory
  clients/           # domain I/O facades
  stores/            # persistence (or external API adapters)
  errors.py          # domain errors
```

**Import boundary:** domain code must **not** import `src.host` (see `tests/samples/<domain>/test_import_boundary.py`). Registration receives `host_cls` as a parameter from `factory.py`.

### 2. Register queries

Pattern from `samples/<domain>/queries/menu.py`:

```python
def register(host_cls: type) -> None:
    @host_cls.query(
        name="get_something",
        describe="Human-readable catalog description.",
        version="1.0.0",
        risk="low",
        execute_context=ExecuteContext.DE_AUTONOMOUS,
        input_model=GetSomethingInput,
        output_model=GetSomethingOutput,
    )
    async def get_something(self, inputs: GetSomethingInput) -> GetSomethingOutput:
        ...
```

Queries are **low risk** and use `execute_context=de_autonomous` (required for catalog registration).

### 3. Register actions

Pattern from `samples/<domain>/actions/_common.py` and `order_for_me.py`:

1. Define a `coordinated_action` handle with guards (`assert_that.pre`) and a plan.
2. Call `register_action_on_host()` (or equivalent) with:
   - `risk`: `"medium"` | `"high"` | … — drives AyDEO deferral on HTTP invoke
   - `execute_context`: `ExecuteContext.REQUESTOR_IN_SESSION` or `ExecuteContext.DE_AUTONOMOUS`
   - `case_tool_class`: `"read"` | `"case_support"` | `"case_effect"` (required for every `active_open_case` tool)
   - `description`: catalog tool description
   - `input_model`: pydantic model with `Field(description=…)` on every DE-visible field

Confirm uses the kit confirm-phase shape (introduced in v0.2.24; current pin **v0.2.27**): base `tool_name` + `invoke_phase="confirm"` + top-level `plan_token` + flat base `inputs`. Public catalog and `tools()` do **not** emit `{tool}.confirm` rows; a leftover `{tool}.confirm` HTTP name is unknown-tool (404).

### 4. Wire clients and stores

Expose a factory (like `get_demo_clients()`) that returns shared client instances. Inject dependencies in the action factory (`make_action_factory` in domain) so each invoke gets fresh store sessions where needed.

Add Alembic migrations under `backend/migrations/` for any new tables. Run `./scripts/greenfield-alembic-test.sh` before merge when migrations change.

### 5. Hook into `factory.py`

1. Replace `register_domain_tools` with your `register_*_tools(host_cls)`.
2. Replace `CatalogMetadataProvider` with your metadata provider (or omit if not needed).
3. Keep `HostConfig`, adapters, and `get_host_bfa()` as-is unless service slug or test-mode flags change.

### 6. Tests and Postman

- Unit tests under `backend/tests/your_domain/`
- HTTP flow smoke under `backend/tests/host/` if multi-step invoke sequences matter
- Postman requests under a new collection folder; remove **BFA → Domain** when domain is gone

## Risk, execute context, and deferral (HTTP)

On the **HTTP invoke plane**, capability JWT `risk` is combined with catalog tool `risk` to produce `effective_risk`. That drives submit deferral assertions:

| Effective profile | Submit assertion | Typical domain example |
| --- | --- | --- |
| Medium | `needs-confirmation` | `domain_action_medium` |
| High | `needs-superior-defer` | `domain_action_high_team`, `domain_action_high_event` |

`execute_context` tells AyDEO Chat whether the requestor must be in session (`requestor_in_session`) or the DE may run headless (`de_autonomous`). It does **not** replace risk — both appear in the catalog.

**Facade-only tests** (`invoke_with_context` without capability JWT) treat high-risk tools as medium for deferral. Use HTTP smoke tests (`tests/host/test_bfa_flow_smoke.py`) to assert superior deferral.

Local **`BFA_CONFIRM_TEST_MODE=true`** bypasses Chat handoff on **confirm only**; submit deferral still follows capability risk.

## Display metadata

DE-facing copy comes from three places:

1. **Catalog tool `description`** — passed to `@host_cls.query` / `@host_cls.action_factory`.
2. **`operating_context`** — optional string from `CatalogMetadataProvider.operating_context()` on catalog responses.
3. **Input JSON Schema** — pydantic `Field(description=…)` on action/query input models; exported to catalog and validated on invoke.

Action **guard metadata** (`assert_that.pre` ids and messages) is exported via `handle.export_guards()` for catalog consumers.

## Preflight and invariant failures

Before submit reaches deferral, coordinated actions run **guards**. Failed guards return invoke `status: failed` **without** a `plan_token` (preflight failure, not confirmation deferral).

Domain **invariants** in stores (e.g. illegal order status transitions) raise domain errors that surface as failed invokes or step failures on confirm — see domain `errors.py` and `order_transitions.py`.

Distinguish in tests and Postman:

- **Preflight failed** — bad inputs, unknown refs, guard assertion failed
- **Deferral** — `status: failed` **with** `outputs.plan_token` and assertion `needs-confirmation` or `needs-superior-defer`
- **Confirm success** — `status: succeeded` with action outputs (e.g. `order_ref`)

## Removing the domain sample

`./scripts/bootstrap-new-host.sh --strip-domain` is a **complete** repo-root strip (factory stub, models, migrations, domain HTTP tests, Postman domain folder, generated README/POSTMAN wording). Do not leave a leftover “remove Postman by hand” step.

After strip:

1. Wire `register_sample_modules()` to your domain (or keep the empty stub only until you are ready — process will not start without tools).
2. Set `catalog_metadata_provider=` on both `build_aydeo_host(...)` calls, or omit it.
3. Generated HTTP tests use **test-only canaries** under `tests/` — never register those in production `factory.py` / `main.py`.
4. Then `compose up`.

Do not change case/hold or platform adapter assembly for a domain swap.
