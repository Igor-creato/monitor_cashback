from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.incoming_hmac import verify_incoming_hmac_request
from app.db import get_db
from app.schemas.user_region import UserRegionPatch, UserRegionResponse
from app.services.user_regions import set_default_user_region

router = APIRouter(
    prefix="/v1/user-region",
    dependencies=[Depends(verify_incoming_hmac_request)],
)
DbSession = Annotated[Session, Depends(get_db)]


@router.patch("", response_model=UserRegionResponse)
def patch_user_region(
    payload: UserRegionPatch,
    request: Request,
    session: DbSession,
) -> UserRegionResponse:
    _verify_site_matches_request(request, payload.site_id)
    return set_default_user_region(session, payload)


def _verify_site_matches_request(request: Request, site_id: str) -> None:
    if request.headers.get("X-Savello-Site", "").strip() != site_id:
        raise HTTPException(status_code=403, detail="Incoming authentication failed.")
