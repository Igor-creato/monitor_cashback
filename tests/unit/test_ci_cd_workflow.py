from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ci_workflow_scans_secrets_and_runs_quality_gates() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "permissions:" in workflow
    assert "contents: read" in workflow
    assert "secret-scan:" in workflow
    assert "gitleaks/gitleaks-action@v3" in workflow
    assert "fetch-depth: 0" in workflow
    assert "GITHUB_TOKEN: ${{ github.token }}" in workflow
    assert "python -m pytest" in workflow
    assert "python -m ruff check ." in workflow
    assert "python -m ruff format --check ." in workflow
    assert "python -m mypy" in workflow
    assert "git diff --check" in workflow
    assert "docker compose config --quiet" in workflow
    assert "docker build -t price-monitor:${{ github.sha }} ." in workflow
    assert "aquasecurity/trivy-action@0.35.0" in workflow
    assert "scanners: vuln,config,secret" in workflow
    assert '-czf "$RUNNER_TEMP/release.tar.gz" .' in workflow
    assert " release.tar.gz ." not in workflow


def test_ci_workflow_deploys_to_test_server_only_from_develop() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "branches: [develop, master" in workflow
    assert "deploy-test:" in workflow
    assert "needs: [quality, secret-scan]" in workflow
    assert "github.event_name == 'push' && github.ref == 'refs/heads/develop'" in workflow
    assert "github.ref == 'refs/heads/master'" not in workflow
    assert "environment: test" in workflow
    assert "TEST_SERVER_HOST" in workflow
    assert "TEST_SERVER_USER" in workflow
    assert "TEST_SERVER_PORT" in workflow
    assert "TEST_SERVER_SSH_KEY" in workflow
    assert "TEST_SERVER_KNOWN_HOSTS" in workflow
    assert "/home/igor/monitor_cashback" in workflow
    assert 'mkdir -p "$BASE_DIR/releases/$RELEASE_SHA" "$BASE_DIR/shared"' in workflow
    assert 'ln -sfn "$BASE_DIR/releases/$RELEASE_SHA" "$BASE_DIR/current"' in workflow
    assert 'PRICE_MONITOR_ENV_FILE="$BASE_DIR/shared/.env"' in workflow
    assert "alembic upgrade head" in workflow
    assert (
        'docker compose --env-file "$BASE_DIR/shared/.env" run --rm api alembic upgrade head'
        in workflow
    )
    assert 'docker compose --env-file "$BASE_DIR/shared/.env" up -d --build' in workflow
    assert "http://127.0.0.1:8000/health/live" in workflow
    assert "http://127.0.0.1:8000/health/ready" in workflow


def test_compose_uses_server_managed_env_file_override() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert compose.count("${PRICE_MONITOR_ENV_FILE:-.env.example}") == 4


def test_compose_keeps_stateful_service_credentials_and_ports_server_safe() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert compose.count("${PRICE_MONITOR_ENV_FILE:-.env.example}") == 4
    assert "POSTGRES_PASSWORD: price_monitor" not in compose
    assert "RABBITMQ_DEFAULT_PASS: price_monitor" not in compose
    assert "${PRICE_MONITOR_BIND_ADDRESS:-127.0.0.1}:5432:5432" in compose
    assert "${PRICE_MONITOR_BIND_ADDRESS:-127.0.0.1}:5672:5672" in compose
    assert "${PRICE_MONITOR_BIND_ADDRESS:-127.0.0.1}:15672:15672" in compose
    assert "${PRICE_MONITOR_BIND_ADDRESS:-127.0.0.1}:6379:6379" in compose
    assert "${PRICE_MONITOR_BIND_ADDRESS:-127.0.0.1}:8000:8000" in compose
    assert "COMPOSE_PROJECT_NAME=monitor_cashback" in env_example
    assert "PRICE_MONITOR_BIND_ADDRESS=127.0.0.1" in env_example
    assert "POSTGRES_PASSWORD=synthetic-local-postgres-password" in env_example
    assert "RABBITMQ_DEFAULT_PASS=synthetic-local-rabbitmq-password" in env_example
    assert (
        "PRICE_MONITOR_DATABASE_URL=postgresql+psycopg://"
        "price_monitor:synthetic-local-postgres-password@postgres:5432/price_monitor" in env_example
    )
    assert (
        "PRICE_MONITOR_RABBITMQ_URL=amqp://"
        "price_monitor:synthetic-local-rabbitmq-password@rabbitmq:5672//" in env_example
    )


def test_compose_worker_does_not_inherit_api_http_healthcheck() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    worker_section = compose.split("  worker:", maxsplit=1)[1]

    assert "healthcheck:" in worker_section
    assert "disable: true" in worker_section
