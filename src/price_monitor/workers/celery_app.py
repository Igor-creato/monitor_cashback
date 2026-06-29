from celery import Celery


def create_celery_app(broker_url: str, result_backend: str) -> Celery:
    celery_app = Celery("price_monitor", broker=broker_url, backend=result_backend)
    celery_app.conf.update(
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_default_queue="price-monitor.default",
        task_default_exchange="price-monitor",
        task_default_routing_key="default",
        task_publish_retry=True,
        task_publish_retry_policy={
            "max_retries": 3,
            "interval_start": 0,
            "interval_step": 0.2,
            "interval_max": 1.0,
        },
        task_routes={
            "price_monitor.workers.tasks.fetch_product": {
                "queue": "price-monitor.fetch",
                "routing_key": "fetch.product",
            },
            "price_monitor.workers.tasks.publish_outbox": {
                "queue": "price-monitor.outbox",
                "routing_key": "outbox.publish",
            },
        },
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
    )
    return celery_app
