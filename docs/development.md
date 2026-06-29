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
rtk git diff --check
```

Use RED -> GREEN development for behavior changes:

1. Add or update the failing test.
2. Run the targeted test and confirm the expected failure.
3. Implement the smallest change.
4. Run targeted tests, then the relevant full gate.

Do not add production dependencies without documenting purpose, license,
maintenance state, CVE posture, alternatives, and removal plan.
