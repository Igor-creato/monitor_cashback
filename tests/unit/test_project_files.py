from pathlib import Path


def test_source_of_truth_docs_and_runtime_files_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    required = [
        "README.md",
        ".env.example",
        "docs/architecture.md",
        "docs/api-contract.md",
        "docs/security.md",
        "docs/development.md",
        "docs/deploy.md",
        "Dockerfile",
        "docker-compose.yml",
        ".github/workflows/ci.yml",
        "migrations/env.py",
        "migrations/versions/20260629_0001_service_foundation.py",
    ]

    missing = [path for path in required if not (root / path).exists()]

    assert missing == []
