# Price Monitor

Minimal FastAPI backend skeleton for the price-monitor service.

## Local checks

```powershell
Set-Location backend
python -m pytest -q
python -m ruff check .
python -m ruff format .
```

## Run

```powershell
Set-Location backend
uvicorn app.main:app --reload
```

Health endpoint:

```text
GET /health
```
