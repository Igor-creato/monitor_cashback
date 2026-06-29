# Deploy

## Local/Test Stage

The supported foundation deployment target is Docker Compose:

```powershell
rtk docker compose up -d --build
rtk docker compose ps
rtk docker compose logs api
```

Run migrations before accepting traffic:

```powershell
rtk docker compose run --rm api alembic upgrade head
```

## Smoke Checks

```powershell
rtk curl http://localhost:8000/health/live
rtk curl http://localhost:8000/health/ready
```

## Rollback

For test-stage rollback, deploy the previous image tag or previous Git commit,
then run:

```powershell
rtk docker compose up -d --build api worker
rtk curl http://localhost:8000/health/ready
```

Database migrations must be forward-compatible unless a separate rollback plan
has been reviewed.
