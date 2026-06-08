import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
PYPROJECT_PATH = REPOSITORY_ROOT / "price-monitor" / "backend" / "pyproject.toml"
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
DOCKERFILE_PATH = REPOSITORY_ROOT / "price-monitor" / "backend" / "Dockerfile"
COMPOSE_PATH = REPOSITORY_ROOT / "price-monitor" / "docker-compose.yml"


def test_ci_workflow_runs_required_checks_without_deployment_steps() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    for command in (
        "python -m pytest -q",
        "python -m ruff check .",
        "python -m ruff format --check .",
        "alembic upgrade head",
        "docker compose config",
    ):
        assert command in workflow

    for forbidden_marker in (
        "ssh",
        "scp",
        "rsync",
        "kubectl",
        "deploy",
        "secrets.",
    ):
        assert forbidden_marker not in workflow.lower()


def test_backend_image_build_uses_configurable_pip_index() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "ARG PIP_INDEX_URL" in dockerfile
    assert "PIP_INDEX_URL" in compose


def test_backend_package_discovery_only_includes_application_package() -> None:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    package_finder = pyproject["tool"]["setuptools"]["packages"]["find"]

    assert package_finder["include"] == ["app*"]
