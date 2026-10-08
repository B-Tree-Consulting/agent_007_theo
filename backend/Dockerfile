# syntax=docker/dockerfile:1.4
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git rsync \
    && rm -rf /var/lib/apt/lists/*

ARG GH_TOKEN=
ARG AGENTSTEPKIT_REF=v0.2.27
ARG AYDEO_AUDIT_SDK_REF=0.1.2
ARG AYDEO_CMS_CLIENT_REF=main
ARG AYDEO_CMS_CLIENT_VERSION=0.3.0

COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/vendor /app/backend/vendor

# Read the GitHub token with xtrace off so the build log does not expand it.
# ARG GH_TOKEN remains for docker-compose. Demo builds mount the secret instead.
RUN --mount=type=secret,id=github_token,required=false \
    set -eu \
    && github_token_ready=0 \
    && { \
         set +x; \
         token="${GH_TOKEN:-}"; \
         if [ -z "$token" ] && [ -f /run/secrets/github_token ]; then \
           token="$(tr -d '\r\n' < /run/secrets/github_token)"; \
         fi; \
         if [ -n "$token" ]; then \
           git config --global url."https://${token}@github.com/".insteadOf "https://github.com/"; \
           github_token_ready=1; \
         fi; \
         unset token; \
         unset GH_TOKEN; \
       } \
    && set -eux \
    && python -m pip install --no-cache-dir --upgrade pip \
    && if [ -f /app/backend/vendor/agentstepkit/pyproject.toml ]; then \
         pip install --no-cache-dir /app/backend/vendor/agentstepkit \
         && pip install --no-cache-dir -e ".[dev]" --no-deps \
         && pip install --no-cache-dir \
              fastapi "uvicorn[standard]" "sqlalchemy>=2.0,<3" "alembic>=1.13,<2" \
              "psycopg[binary]>=3.1,<4" "pydantic>=2.6,<3" "pydantic-settings>=2.2,<3" \
              "PyJWT>=2.8,<3" "cryptography>=42,<46" \
              pytest "pytest-cov>=5,<7" "httpx>=0.27,<1"; \
       elif [ "$github_token_ready" -eq 1 ]; then \
         pip install --no-cache-dir "agentstepkit @ git+https://github.com/B-Tree-Consulting/b-tree-aydeo-bfa.git@${AGENTSTEPKIT_REF}" \
         && pip install --no-cache-dir -e ".[dev]" --no-deps \
         && pip install --no-cache-dir \
              fastapi "uvicorn[standard]" "sqlalchemy>=2.0,<3" "alembic>=1.13,<2" \
              "psycopg[binary]>=3.1,<4" "pydantic>=2.6,<3" "pydantic-settings>=2.2,<3" \
              "PyJWT>=2.8,<3" "cryptography>=42,<46" \
              pytest "pytest-cov>=5,<7" "httpx>=0.27,<1"; \
       else \
         echo "error: run scripts/prepare-vendor-kit.sh or set GITHUB_TOKEN or mount the github_token build secret" >&2; \
         exit 1; \
       fi \
    && rm -f /root/.gitconfig

# Fail fast if build did not install the pinned kit.
RUN python -c "import importlib.metadata as m; v=m.version('agentstepkit'); assert v=='0.2.27', f'agentstepkit must be 0.2.27, got {v}'"

RUN --mount=type=secret,id=github_token,required=false \
    set -eu \
    && github_token_ready=0 \
    && { \
         set +x; \
         token="${GH_TOKEN:-}"; \
         if [ -z "$token" ] && [ -f /run/secrets/github_token ]; then \
           token="$(tr -d '\r\n' < /run/secrets/github_token)"; \
         fi; \
         if [ -n "$token" ]; then \
           git config --global url."https://${token}@github.com/".insteadOf "https://github.com/"; \
           github_token_ready=1; \
         fi; \
         unset token; \
         unset GH_TOKEN; \
       } \
    && set -eux \
    && if [ -f /app/backend/vendor/aydeo_audit_sdk/pyproject.toml ]; then \
         pip install --no-cache-dir /app/backend/vendor/aydeo_audit_sdk; \
       elif [ "$github_token_ready" -eq 1 ]; then \
         pip install --no-cache-dir "aydeo-audit-sdk @ git+https://github.com/B-Tree-Consulting/b-tree-aydeo-audit.git@${AYDEO_AUDIT_SDK_REF}#subdirectory=packages/aydeo_audit_sdk"; \
       else \
         echo "error: run scripts/prepare-vendor-audit-sdk.sh or set GITHUB_TOKEN or mount the github_token build secret" >&2; \
         exit 1; \
       fi \
    && rm -f /root/.gitconfig

RUN python -c "import importlib.metadata as m; v=m.version('aydeo-audit-sdk'); assert v=='0.1.2', f'aydeo-audit-sdk must be 0.1.2, got {v}'"

RUN --mount=type=secret,id=github_token,required=false \
    set -eu \
    && github_token_ready=0 \
    && { \
         set +x; \
         token="${GH_TOKEN:-}"; \
         if [ -z "$token" ] && [ -f /run/secrets/github_token ]; then \
           token="$(tr -d '\r\n' < /run/secrets/github_token)"; \
         fi; \
         if [ -n "$token" ]; then \
           git config --global url."https://${token}@github.com/".insteadOf "https://github.com/"; \
           github_token_ready=1; \
         fi; \
         unset token; \
         unset GH_TOKEN; \
       } \
    && set -eux \
    && if [ "$github_token_ready" -eq 1 ]; then \
         pip install --no-cache-dir "aydeo-cms-client @ git+https://github.com/B-Tree-Consulting/b-tree-aydeo_be.git@${AYDEO_CMS_CLIENT_REF}#subdirectory=packages/aydeo_cms_client" \
         && python -c "import importlib.metadata as m; v=m.version('aydeo-cms-client'); print('aydeo-cms-client', v, 'ref=${AYDEO_CMS_CLIENT_REF}', 'want=${AYDEO_CMS_CLIENT_VERSION}'); assert v=='${AYDEO_CMS_CLIENT_VERSION}', f'aydeo-cms-client must be ${AYDEO_CMS_CLIENT_VERSION}, got {v}'"; \
       else \
         echo "error: set GITHUB_TOKEN or mount the github_token build secret for aydeo-cms-client docker build" >&2; \
         exit 1; \
       fi \
    && rm -f /root/.gitconfig

COPY backend/docker-entrypoint.sh /app/backend/docker-entrypoint.sh
RUN chmod +x /app/backend/docker-entrypoint.sh

COPY backend/alembic.ini /app/backend/alembic.ini
COPY backend/migrations /app/backend/migrations
COPY backend/contracts /app/backend/contracts
COPY backend/src /app/backend/src
COPY backend/tests /app/backend/tests
COPY scripts /app/scripts
RUN chmod +x /app/scripts/vendor-bfa-case-policy-parity.sh

EXPOSE 8000
ENTRYPOINT ["/app/backend/docker-entrypoint.sh"]
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
