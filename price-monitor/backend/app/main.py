from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.health import router as health_router
from app.api.internal import router as internal_router
from app.api.metrics import router as metrics_router
from app.api.product_history import router as product_history_router
from app.api.watchlist import router as watchlist_router
from app.core.config import settings

app = FastAPI(title=settings.app_name)
app.include_router(admin_router)
app.include_router(health_router)
app.include_router(internal_router)
app.include_router(metrics_router)
app.include_router(product_history_router)
app.include_router(watchlist_router)
