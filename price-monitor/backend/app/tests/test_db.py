import app.db as db


def test_create_db_engine_enables_stale_connection_recovery(monkeypatch) -> None:
    captured = {}

    def fake_create_engine(database_url: str, **kwargs):
        captured["database_url"] = database_url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(db, "create_engine", fake_create_engine)

    db.create_db_engine("mysql+pymysql://user:password@db/price_monitor")

    assert captured == {
        "database_url": "mysql+pymysql://user:password@db/price_monitor",
        "kwargs": {
            "pool_pre_ping": True,
            "pool_recycle": 3600,
        },
    }
