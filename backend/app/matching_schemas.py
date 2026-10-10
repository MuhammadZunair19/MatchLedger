from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class MatchRunInput(BaseModel):
    invoice_id: str
    purchase_order_id: str
    matching_mode: Literal['TWO_WAY', 'THREE_WAY'] = 'THREE_WAY'
    receipt_ids: list[str] = Field(default_factory=list, max_length=100)
    line_associations: dict[str, str] = Field(default_factory=dict)
    save_mappings: bool = False
    review_notes: str | None = Field(default=None, max_length=2000)


class MatchingSettingsInput(BaseModel):
    price_tolerance_percent: Decimal = Field(default=Decimal('0'), ge=0, max_digits=9, decimal_places=4)
    price_tolerance_absolute: Decimal = Field(default=Decimal('0'), ge=0, max_digits=18, decimal_places=2)
    quantity_tolerance: Decimal = Field(default=Decimal('0'), ge=0, max_digits=18, decimal_places=3)
    total_tolerance_absolute: Decimal = Field(default=Decimal('0.01'), ge=0, max_digits=18, decimal_places=2)
    unit_conversions: dict[str, Decimal] = Field(default_factory=dict)

    @field_validator('unit_conversions')
    @classmethod
    def conversions_are_positive(cls, value):
        if any(factor <= 0 for factor in value.values()):
            raise ValueError('Unit conversion factors must be positive')
        return value
