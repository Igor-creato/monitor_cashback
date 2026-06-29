from price_monitor.core.config import get_settings
from price_monitor.workers.celery_app import create_celery_app

settings = get_settings()
celery_app = create_celery_app(settings.rabbitmq_url, settings.redis_url)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="price_monitor.workers.tasks.fetch_product",
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    soft_time_limit=25,
    time_limit=30,
)
def fetch_product(product_id: str) -> dict[str, str]:
    return {"product_id": product_id, "status": "queued"}
