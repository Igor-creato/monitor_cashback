import hmac

from fastapi import HTTPException, Request

from app.core.config import settings


def verify_admin_api_key(request: Request) -> None:
    expected_key = settings.admin_api_key.get_secret_value().strip()
    provided_key = request.headers.get("ADMIN_API_KEY", "").strip()

    if expected_key == "" or provided_key == "":
        raise HTTPException(status_code=401, detail="Admin authentication required.")

    if not hmac.compare_digest(expected_key, provided_key):
        raise HTTPException(status_code=403, detail="Admin authentication failed.")
