from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from price_monitor.price_compare import models as _price_compare_models  # noqa: E402,F401
from price_monitor.price_compare.live import models as _price_compare_live_models  # noqa: E402,F401
