from fastapi import APIRouter, Depends

from app.core.incoming_hmac import verify_incoming_hmac_request

router = APIRouter()


@router.post(
    "/internal/wordpress/ping",
    dependencies=[Depends(verify_incoming_hmac_request)],
)
def wordpress_ping() -> dict[str, str]:
    return {"status": "ok"}
