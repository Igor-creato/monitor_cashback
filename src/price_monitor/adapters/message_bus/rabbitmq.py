from kombu import Connection, Exchange, Producer


class RabbitMQPublisher:
    def __init__(self, broker_url: str) -> None:
        self._broker_url = broker_url
        self._exchange = Exchange("price-monitor", type="topic", durable=True)

    def publish(
        self, *, routing_key: str, payload: dict[str, object], headers: dict[str, str]
    ) -> None:
        with Connection(self._broker_url) as connection:
            producer = Producer(connection)
            producer.publish(
                payload,
                exchange=self._exchange,
                routing_key=routing_key,
                headers=headers,
                declare=[self._exchange],
                serializer="json",
                delivery_mode=2,
                retry=True,
            )
