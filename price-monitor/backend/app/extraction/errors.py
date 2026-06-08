class ExtractionError(Exception):
    """Base class for product extraction failures."""


class ExtractionSchemaError(ExtractionError):
    """Raised when extraction input does not match the declared schema."""


class RequiredFieldNotFoundError(ExtractionError):
    def __init__(self, field_name: str) -> None:
        self.field_name = field_name
        super().__init__(f"Required field not found: {field_name}")


class PriceNotFoundError(RequiredFieldNotFoundError):
    def __init__(self) -> None:
        super().__init__("price_current")


class TitleNotFoundError(RequiredFieldNotFoundError):
    def __init__(self) -> None:
        super().__init__("title")
