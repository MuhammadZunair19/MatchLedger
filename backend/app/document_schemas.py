from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .services.documents.field_extraction import COMMON, STRATEGIES

DocumentType = Literal['purchase_order', 'supplier_invoice', 'goods_receipt']


class ReviewLine(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=500)
    sku: str | None = Field(default=None, max_length=100)
    quantity: str | None = Field(default=None, max_length=40)
    unit_of_measure: str | None = Field(default=None, max_length=40)
    unit_price: str | None = Field(default=None, max_length=40)
    line_total: str | None = Field(default=None, max_length=40)
    purchase_order_line_id: str | None = Field(default=None, max_length=36)


class ReviewData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    extraction_id: str = Field(max_length=36)
    fields: dict[str, str | None]
    lines: list[ReviewLine] = Field(max_length=200)
    supplier_id: str | None = Field(default=None, max_length=36)
    purchase_order_id: str | None = Field(default=None, max_length=36)

    @field_validator('fields')
    @classmethod
    def valid_fields(cls, value):
        allowed = set(COMMON) | {k for strategy in STRATEGIES.values() for k in strategy}
        if not set(value).issubset(allowed) or any(v is not None and len(v) > 2000 for v in value.values()):
            raise ValueError('Unknown field or field too long')
        return value

    @field_validator('lines')
    @classmethod
    def unique_lines(cls, value):
        if len({line.id for line in value}) != len(value):
            raise ValueError('Line IDs must be unique')
        return value


class SaveReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0)
    data: ReviewData


class ConfirmReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0)
    acknowledge_warnings: bool = False
    create_supplier: bool = False
