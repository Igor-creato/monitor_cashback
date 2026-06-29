from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from price_monitor.api.dependencies import get_db_session

router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.get("/{product_id}")
def product_detail(
    product_id: str, session: Annotated[Session, Depends(get_db_session)]
) -> dict[str, str]:
    del session
    return {"product_id": product_id, "status": "not_loaded"}
