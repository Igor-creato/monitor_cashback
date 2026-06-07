import hashlib
import hmac
import time

from fastapi import HTTPException, Request

from app.core.config import settings

MAX_TIMESTAMP_SKEW_SECONDS = 300


def current_unix_time() -> int:
    return int(time.time())


async def verify_incoming_hmac_request(request: Request) -> None:
    expected_site_id = settings.price_monitor_incoming_site_id.strip()
    secret = settings.price_monitor_incoming_secret.get_secret_value()
    if expected_site_id == "" or secret == "":
        raise HTTPException(status_code=401, detail="Incoming authentication required.")

    site_id = request.headers.get("X-Savello-Site", "").strip()
    timestamp = request.headers.get("X-Savello-Timestamp", "").strip()
    signature = request.headers.get("X-Savello-Signature", "").strip()
    if site_id == "" or timestamp == "" or signature == "":
        raise HTTPException(status_code=401, detail="Incoming authentication required.")

    if site_id != expected_site_id:
        raise HTTPException(status_code=403, detail="Incoming authentication failed.")

    if not timestamp.isdigit():
        raise HTTPException(status_code=403, detail="Incoming authentication failed.")

    request_time = int(timestamp)
    if abs(current_unix_time() - request_time) > MAX_TIMESTAMP_SKEW_SECONDS:
        raise HTTPException(status_code=403, detail="Incoming authentication failed.")

    raw_body = await request.body()
    expected_signature = hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=403, detail="Incoming authentication failed.")
