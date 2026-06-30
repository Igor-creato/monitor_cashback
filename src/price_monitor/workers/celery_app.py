from celery import Celery
from kombu import Exchange, Queue

TASK_EXCHANGE = Exchange("price-monitor", type="direct", durable=True, delivery_mode=2)
TASK_QUEUES = (
    Queue("price-monitor.default", TASK_EXCHANGE, routing_key="default", durable=True),
    Queue("price-monitor.fetch", TASK_EXCHANGE, routing_key="fetch.product", durable=True),
    Queue("price-monitor.outbox", TASK_EXCHANGE, routing_key="outbox.publish", durable=True),
)


def create_celery_app(broker_url: str, result_backend: str) -> Celery:
    celery_app = Celery("price_monitor", broker=broker_url, backend=result_backend)
    celery_app.conf.update(
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        worker_enable_remote_control=False,
        worker_send_task_events=False,
        task_default_queue="price-monitor.default",
        task_default_exchange="price-monitor",
        task_default_routing_key="default",
        task_queues=TASK_QUEUES,
        task_create_missing_queues=False,
        task_send_sent_event=False,
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
        event_queue_durable=True,
        event_queue_exclusive=False,
        timezone="UTC",
    )
    return celery_app
