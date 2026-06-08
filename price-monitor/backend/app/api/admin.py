from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.admin_auth import verify_admin_api_key
from app.db import get_db
from app.schemas.admin import (
    AdminErrorsResponse,
    AdminJobsResponse,
    AdminOverviewResponse,
    AdminProductResponse,
    AdminProductsResponse,
    AdminSourcePatch,
    AdminSourceResponse,
    AdminSourcesResponse,
)
from app.services.admin import (
    get_admin_overview,
    get_admin_product,
    list_admin_errors,
    list_admin_jobs,
    list_admin_products,
    list_admin_sources,
    patch_admin_source,
)

router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(verify_admin_api_key)],
)
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/overview", response_model=AdminOverviewResponse)
def admin_overview(session: DbSession) -> AdminOverviewResponse:
    return get_admin_overview(session)


@router.get("/sources", response_model=AdminSourcesResponse)
def admin_sources(session: DbSession) -> AdminSourcesResponse:
    return AdminSourcesResponse(items=list_admin_sources(session))


@router.patch("/sources/{source_code}", response_model=AdminSourceResponse)
def admin_patch_source(
    source_code: str,
    patch: AdminSourcePatch,
    session: DbSession,
) -> AdminSourceResponse:
    source = patch_admin_source(session, source_code, patch)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    return source


@router.get("/products", response_model=AdminProductsResponse)
def admin_products(session: DbSession) -> AdminProductsResponse:
    return AdminProductsResponse(items=list_admin_products(session))


@router.get("/products/{tracked_product_id}", response_model=AdminProductResponse)
def admin_product(
    tracked_product_id: int,
    session: DbSession,
) -> AdminProductResponse:
    product = get_admin_product(session, tracked_product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    return product


@router.get("/jobs", response_model=AdminJobsResponse)
def admin_jobs(session: DbSession) -> AdminJobsResponse:
    return AdminJobsResponse(items=list_admin_jobs(session))


@router.get("/errors", response_model=AdminErrorsResponse)
def admin_errors(session: DbSession) -> AdminErrorsResponse:
    return AdminErrorsResponse(items=list_admin_errors(session))
