## AyDEO agent-007-theo — local dev

This checkout is the image for the demo Container App **`trader-app`**. The process slug on that app is **`agent-007-theo`**. The demo scripts below build **this** repository and roll that existing app. They do not create a second app and they do not update `aydeo-sample-bfa`.

### Demo operator flow

Container App **`trader-app`** in **`rg-aydeo-demo-weu`** (`cae-aydeo-demo-weu`), identity **`id-trader-app`**. Callers use `https://trader-app.<defaultDomain>`. Apply sets `BFA_SERVICE_SLUG=agent-007-theo` on that app. Image repository is `acraydeodemo.azurecr.io/trader-app`. Tags from this repo look like `agent-007-theo-YYYYMMDD-HHMMSS-<gitsha>`.

Secret values stay in Key Vault **`kv-aydeo-demo-weu`**. Names only:

| Key Vault secret | Container App secret | Env var |
| --- | --- | --- |
| `trader-app-database-url` | `trader-app-database-url` | `DATABASE_URL` |
| `trader-app-t212-api-key` | `trader-app-t212-api-key` | `T212_API_KEY` |
| `trader-app-t212-api-secret` | `trader-app-t212-api-secret` | `T212_API_SECRET` |
| `trader-app-theo-whitelist` | `trader-app-theo-whitelist` | `THEO_WHITELIST` |
| `trader-app-theo-whitelist-path` | `trader-app-theo-whitelist-path` | `THEO_WHITELIST_PATH` |
| `trader-app-theo-symbol-overrides` | `trader-app-theo-symbol-overrides` | `THEO_SYMBOL_OVERRIDES` |
| `aydeo-chat-internal-service-token` | `chat-internal-service-token` | `AYDEO_CHAT_INTERNAL_TOKEN` |
| `aydeo-platform-internal-service-token` | `platform-internal-service-token` | `AYDEO_PLATFORM_INTERNAL_SERVICE_TOKEN` |

The app already exists on demo. Create is idempotent if identity or secret bindings need a refresh. Sync uploads `DEMO_DATABASE_URL` from the **DB Setup** section and assignments from **Trading App Configuration** in the repo-root `.env`. It does not print values. Apply binds the Key Vault names already on the app.

```bash
az login
az extension add --name containerapp
./infra/scripts/trader-create.sh          # only if the app or its bindings need a refresh
./infra/scripts/trader-sync-trading-kv-secrets.sh   # only when demo secrets should change
./infra/scripts/trader-build-push.sh
./infra/scripts/trader-apply.sh
```

Build needs the GitHub token file at `$HOME/.config/aydeo-demo/github_token` (see `b-tree-aydeo_be/infra/scripts/github_token.example`). The token is a BuildKit secret, not a build-arg. Non-secret defaults are listed in [`backend/.env.demo.example`](backend/.env.demo.example).

Smoke:

```bash
curl -sS "https://trader-app.<defaultDomain>/health"
```

A healthy body has `"service":"agent-007-theo"`. A later apply from `../trader_app` rolls this same container back to that repository's image.

