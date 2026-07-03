from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_product_link_monitoring_modules_are_removed():
    removed_paths = [
        ROOT / "src" / "price_monitor" / "domains",
        ROOT / "src" / "price_monitor" / "api" / "v1" / "watchlist.py",
        ROOT / "src" / "price_monitor" / "api" / "v1" / "price_history.py",
        ROOT / "src" / "price_monitor" / "workers" / "tasks" / "fetch_product.py",
    ]

    for path in removed_paths:
        assert not path.exists()


def test_compose_no_longer_runs_browser_renderer():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "browserless" not in compose
    assert "decodo" not in compose.lower()
