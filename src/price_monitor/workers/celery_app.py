from celery import Celery
from kombu import Exchange, Queue

from price_monitor.core.config import get_settings

TASK_EXCHANGE = Exchange("monitor-cashback", type="direct", durable=True, delivery_mode=2)
TASK_QUEUES = (
    Queue("monitor-cashback.default", TASK_EXCHANGE, routing_key="default", durable=True),
)


def create_celery_app(broker_url: str, result_backend: str) -> Celery:
    celery_app = Celery("monitor_cashback", broker=broker_url, backend=result_backend)
    celery_app.conf.update(
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        worker_enable_remote_control=False,
        worker_send_task_events=False,
        task_default_queue="monitor-cashback.default",
        task_default_exchange="monitor-cashback",
        task_default_routing_key="default",
        task_queues=TASK_QUEUES,
        task_create_missing_queues=False,
        task_send_sent_event=False,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
    )
    return celery_app


settings = get_settings()
celery_app = create_celery_app(settings.rabbitmq_url, settings.redis_url)
