from pydantic import BaseModel, ConfigDict, Field


class UserRegionPatch(BaseModel):
    site_id: str = Field(min_length=1, max_length=191)
    external_user_id: str = Field(min_length=1, max_length=191)
    region_code: str = Field(min_length=1, max_length=64)
    country_code: str | None = Field(default=None, max_length=8)

    model_config = ConfigDict(extra="forbid")


class UserRegionResponse(BaseModel):
    region_code: str
    country_code: str | None = None
    is_default: bool
