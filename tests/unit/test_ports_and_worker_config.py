from price_monitor.domains.integrations.ports import MarketplaceOAuthProvider
from price_monitor.domains.products.ports import ProductMatcher, ProductNormalizer
from price_monitor.domains.sources.ports import ProductSourceAdapter
from price_monitor.workers.celery_app import create_celery_app


def test_domain_ports_expose_extension_points_required_by_plan() -> None:
    assert hasattr(ProductSourceAdapter, "fetch_product")
    assert hasattr(ProductNormalizer, "normalize_url")
    assert hasattr(ProductMatcher, "match_offer")
    assert hasattr(MarketplaceOAuthProvider, "build_authorization_url")


def test_celery_app_defaults_to_reliable_at_least_once_worker_settings() -> None:
    celery_app = create_celery_app("memory://", "redis://localhost:6379/0")

    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.task_default_queue == "price-monitor.default"
    assert (
        celery_app.conf.task_routes["price_monitor.workers.tasks.fetch_product"]["queue"]
        == "price-monitor.fetch"
    )
