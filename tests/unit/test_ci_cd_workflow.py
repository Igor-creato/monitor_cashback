from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _compose_service_section(compose: str, service: str) -> str:
    lines = compose.splitlines()
    start = lines.index(f"  {service}:")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line and not line.startswith(" "):
            end = index
            break
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            end = index
            break
    return "\n".join(lines[start:end])


def test_ci_workflow_scans_secrets_and_runs_quality_gates() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "permissions:" in workflow
    assert "contents: read" in workflow
    assert "secret-scan:" in workflow
    assert "gitleaks/gitleaks-action@v3.0.0" in workflow
    assert "fetch-depth: 0" in workflow
    assert "GITHUB_TOKEN: ${{ github.token }}" in workflow
    assert "python -m pytest" in workflow
    assert "python -m ruff check ." in workflow
    assert "python -m ruff format --check ." in workflow
    assert "python -m mypy" in workflow
    assert "git diff --check" in workflow
    assert "docker compose config --quiet" in workflow
    assert "docker build -t price-monitor:${{ github.sha }} ." in workflow
    assert "aquasecurity/trivy-action@v0.36.0" in workflow
    assert "scanners: vuln,config,secret" in workflow
    assert '-czf "$RUNNER_TEMP/release.tar.gz" .' in workflow
    assert " release.tar.gz ." not in workflow


def test_runtime_and_ci_versions_use_latest_compatible_stable_pins() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "FROM python:3.14.6-slim-bookworm AS runtime" in dockerfile
    assert "image: postgres:18.4-alpine" in compose
    assert "image: rabbitmq:4.3.2-management-alpine" in compose
    assert "image: redis:8.8.0-alpine" in compose
    assert 'requires = ["setuptools==82.0.1", "wheel==0.47.0"]' in pyproject
    assert '"fastapi==0.138.2"' in pyproject
    assert "actions/checkout@v7.0.0" in workflow
    assert "actions/setup-python@v6.3.0" in workflow
    assert 'python-version: "3.14.6"' in workflow
    assert "aquasecurity/trivy-action@v0.36.0" in workflow
    assert "gitleaks/gitleaks-action@v3.0.0" in workflow


def test_ci_workflow_deploys_to_test_server_only_from_develop() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    postgres_upgrade = (ROOT / ".github" / "scripts" / "postgres-major-upgrade.sh").read_text(
        encoding="utf-8"
    )

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
        'docker compose --env-file "$BASE_DIR/shared/.env" '
        "run --rm --build api alembic upgrade head" in workflow
    )
    assert 'docker compose --env-file "$BASE_DIR/shared/.env" up -d --build --force-recreate' in (
        workflow
    )
    assert "POSTGRES_MAJOR_UPGRADE_COMMAND=" in workflow
    assert "TARGET_POSTGRES_MAJOR=18" in workflow
    assert "pg_dump" in postgres_upgrade
    assert "pg_restore" in postgres_upgrade
    assert "postgres-data-pg18" in compose
    assert "postgres-data-pg18:/var/lib/postgresql" in compose
    assert "postgres-data-v18:/var/lib/postgresql/data" not in compose
    assert "find_latest_dump" in postgres_upgrade
    assert "logs --no-color --tail=200 postgres" in postgres_upgrade
    assert "http://127.0.0.1:8000/health/live" in workflow
    assert "http://127.0.0.1:8000/health/ready" in workflow
    assert 'docker compose --env-file "$BASE_DIR/shared/.env" ps' in workflow
    assert 'docker compose --env-file "$BASE_DIR/shared/.env" images' in workflow
    assert "platform.python_version()" in workflow
    assert "fastapi.__version__" in workflow
    assert "postgres --version" in workflow
    assert "redis-server --version" in workflow
    assert "rabbitmq-diagnostics server_version" in workflow


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


def test_compose_sets_resource_limits_and_low_noise_healthchecks() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    expected_limits = {
        "postgres": "1g",
        "rabbitmq": "768m",
        "redis": "256m",
        "api": "512m",
        "worker": "1536m",
    }

    for service, memory_limit in expected_limits.items():
        section = _compose_service_section(compose, service)
        assert f"    mem_limit: {memory_limit}" in section
        assert f"    memswap_limit: {memory_limit}" in section

    for service in ("postgres", "rabbitmq", "redis", "api"):
        section = _compose_service_section(compose, service)
        assert "      interval: 60s" in section


def test_compose_hardens_rabbitmq_memory_and_logs_for_fresh_servers() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    rabbitmq_conf = (ROOT / "deploy" / "rabbitmq" / "rabbitmq.conf").read_text(encoding="utf-8")

    assert "x-json-logging: &json-logging" in compose
    assert compose.count("    logging: *json-logging") == 5
    assert compose.count('max-size: "10m"') == 1
    assert compose.count('max-file: "3"') == 1

    rabbitmq_section = _compose_service_section(compose, "rabbitmq")
    assert "./deploy/rabbitmq/rabbitmq.conf:/etc/rabbitmq/conf.d/20-monitor.conf:ro" in (
        rabbitmq_section
    )
    assert "vm_memory_high_watermark.absolute = 512MB" in rabbitmq_conf
    assert "deprecated_features.permit.global_qos = true" in rabbitmq_conf
    assert "deprecated_features.permit.transient_nonexcl_queues" not in rabbitmq_conf


def test_compose_worker_does_not_inherit_api_http_healthcheck() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    worker_section = _compose_service_section(compose, "worker")

    assert "healthcheck:" in worker_section
    assert "disable: true" in worker_section
    assert "--without-heartbeat" in worker_section
