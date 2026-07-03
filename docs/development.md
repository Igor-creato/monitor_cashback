# Development

## Setup

```powershell
rtk python -m pip install -e ".[dev]"
```

## Test and Quality Gates

```powershell
rtk python -m pytest
rtk python -m ruff check .
rtk python -m ruff format --check .
rtk python -m mypy
rtk docker compose config --quiet
rtk git diff --check
```

Use RED -> GREEN development for future behavior changes. Keep new service code
source-neutral until the product search/comparison contract is approved.
