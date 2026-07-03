from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from price_monitor.price_compare import models as _price_compare_models  # noqa: E402,F401
