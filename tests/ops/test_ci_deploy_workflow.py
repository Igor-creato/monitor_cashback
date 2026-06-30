from pathlib import Path


def test_deploy_migration_uses_fresh_api_image() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    expected = (
        'docker compose --env-file "$BASE_DIR/shared/.env" '
        "run --rm --build api alembic upgrade head"
    )

    assert expected in workflow
