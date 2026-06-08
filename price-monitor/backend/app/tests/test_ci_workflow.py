from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"


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
