from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class ExtractionSchema(BaseModel):
    source_code: str
    version: str
    content_type: Literal["json", "html"]
    title_path: str | None = None
    price_path: str | None = None
    old_price_path: str | None = None
    currency_path: str | None = None
    image_path: str | None = None
    availability_path: str | None = None
    seller_path: str | None = None
    css_title: str | None = None
    css_price: str | None = None
    css_old_price: str | None = None
    css_image: str | None = None
    css_availability: str | None = None
    required_fields: list[str] = Field(default_factory=list)


class ExtractedProductData(BaseModel):
    title: str | None = None
    price_current: Decimal | None = None
    price_old: Decimal | None = None
    currency: str | None = None
    image_url: str | None = None
    availability: bool | None = None
    seller_name: str | None = None
    source_status: str = "ok"
    extraction_schema_version: str
