from dataclasses import dataclass


@dataclass(frozen=True)
class CounterSample:
    name: str
    value: int


def foundation_metrics() -> list[CounterSample]:
    return [CounterSample(name="price_monitor_foundation_info", value=1)]
