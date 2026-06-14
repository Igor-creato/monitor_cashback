from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
PRICE_MONITOR_ROOT = REPOSITORY_ROOT / "price-monitor"
COMPOSE_PATH = PRICE_MONITOR_ROOT / "docker-compose.yml"
ENV_EXAMPLE_PATH = PRICE_MONITOR_ROOT / ".env.example"
README_PATH = PRICE_MONITOR_ROOT / "README.md"


def _compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def _env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        values[key] = value
    return values


def test_compose_defines_local_minio_and_bucket_init() -> None:
    compose = _compose()
    services = compose["services"]

    minio = services["minio"]
    minio_init = services["minio-init"]

    assert minio["image"] == "alpine/minio:RELEASE.2025-10-15T17-29-55Z"
    assert minio["command"] == 'server /data --console-address ":9001"'
    assert "9000:9000" in minio["ports"]
    assert "9001:9001" in minio["ports"]
    assert "minio-data:/data" in minio["volumes"]

    assert minio_init["image"] == "minio/mc:latest"
    assert minio_init["depends_on"] == ["minio"]
    init_command = minio_init["entrypoint"]
    assert "mc alias set local http://minio:9000" in init_command
    assert (
        "mc mb --ignore-existing local/$${OBJECT_STORAGE_BUCKET:-product-images}"
        in (init_command)
    )
    assert "minio-data" in compose["volumes"]


def test_backend_compose_exposes_object_storage_environment() -> None:
    backend_environment = _compose()["services"]["backend-api"]["environment"]

    assert backend_environment["OBJECT_STORAGE_ENABLED"] == (
        "${OBJECT_STORAGE_ENABLED:-true}"
    )
    assert backend_environment["OBJECT_STORAGE_ENDPOINT"] == (
        "${OBJECT_STORAGE_ENDPOINT:-http://minio:9000}"
    )
    assert backend_environment["OBJECT_STORAGE_ACCESS_KEY"] == (
        "${OBJECT_STORAGE_ACCESS_KEY:-minioadmin}"
    )
    assert backend_environment["OBJECT_STORAGE_SECRET_KEY"] == (
        "${OBJECT_STORAGE_SECRET_KEY:-minioadmin123}"
    )
    assert backend_environment["OBJECT_STORAGE_BUCKET"] == (
        "${OBJECT_STORAGE_BUCKET:-product-images}"
    )
    assert backend_environment["OBJECT_STORAGE_PUBLIC_BASE_URL"] == (
        "${OBJECT_STORAGE_PUBLIC_BASE_URL:-http://localhost:9000/product-images}"
    )


def test_env_example_contains_local_minio_object_storage_defaults() -> None:
    values = _env_example()

    assert values["MINIO_ROOT_USER"] == "minioadmin"
    assert values["MINIO_ROOT_PASSWORD"] == "minioadmin123"
    assert values["OBJECT_STORAGE_ENABLED"] == "true"
    assert values["OBJECT_STORAGE_ENDPOINT"] == "http://minio:9000"
    assert values["OBJECT_STORAGE_ACCESS_KEY"] == "minioadmin"
    assert values["OBJECT_STORAGE_SECRET_KEY"] == "minioadmin123"
    assert values["OBJECT_STORAGE_BUCKET"] == "product-images"
    assert (
        values["OBJECT_STORAGE_PUBLIC_BASE_URL"]
        == "http://localhost:9000/product-images"
    )


def test_readme_documents_local_minio_usage() -> None:
    readme = README_PATH.read_text(encoding="utf-8")

    assert "rtk docker compose up -d minio minio-init" in readme
    assert "http://localhost:9000" in readme
    assert "http://localhost:9001" in readme
    assert "`product-images`" in readme
    assert "S3-compatible" in readme
