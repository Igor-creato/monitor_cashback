from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.monitoring import UserRegion
from app.schemas.user_region import UserRegionPatch, UserRegionResponse


def get_default_user_region(
    session: Session,
    *,
    site_id: str,
    external_user_id: str,
) -> UserRegionResponse:
    region = session.scalar(
        select(UserRegion).where(
            UserRegion.site_id == site_id,
            UserRegion.external_user_id == external_user_id,
            UserRegion.is_default.is_(True),
        )
    )
    if region is None:
        return UserRegionResponse(
            region_code="default",
            country_code=None,
            is_default=True,
        )
    return _serialize(region)


def set_default_user_region(
    session: Session,
    request: UserRegionPatch,
) -> UserRegionResponse:
    regions = session.scalars(
        select(UserRegion).where(
            UserRegion.site_id == request.site_id,
            UserRegion.external_user_id == request.external_user_id,
        )
    ).all()
    selected = None
    for region in regions:
        if region.region_code == request.region_code:
            selected = region
            break

    if selected is None:
        selected = UserRegion(
            site_id=request.site_id,
            external_user_id=request.external_user_id,
            region_code=request.region_code,
        )
        session.add(selected)
        session.flush()

    for region in regions:
        region.is_default = region.id == selected.id

    selected.country_code = request.country_code
    selected.is_default = True
    session.commit()
    session.refresh(selected)
    return _serialize(selected)


def _serialize(region: UserRegion) -> UserRegionResponse:
    return UserRegionResponse(
        region_code=region.region_code,
        country_code=region.country_code,
        is_default=region.is_default,
    )
