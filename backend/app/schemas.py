from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Annotated
import pycountry
from pydantic import BaseModel, ConfigDict, Field, EmailStr, StringConstraints, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


Name = Annotated[str, Field(min_length=1, max_length=160)]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=15, decimal_places=3)]
Money = Annotated[Decimal, Field(ge=0, max_digits=15, decimal_places=2)]


class Register(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    email: EmailStr
    password: Annotated[str, StringConstraints(strip_whitespace=False, min_length=12, max_length=128)]
    organization_name: Name


class Login(StrictModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(strip_whitespace=False, min_length=1, max_length=128)]


class MemberInput(StrictModel):
    email: EmailStr


class SwitchOrganization(StrictModel):
    organization_id: str


class SupplierInput(StrictModel):
    name: Name
    email: EmailStr | None = None
    phone: Annotated[str, Field(max_length=40)] | None = None
    address: Annotated[str, Field(max_length=1000)] | None = None


class POLineInput(StrictModel):
    description: Annotated[str, Field(min_length=1, max_length=500)]
    quantity: Quantity
    unit_price: Money


class ReceiptLineInput(StrictModel):
    description: Annotated[str, Field(min_length=1, max_length=500)]
    quantity: Quantity
    purchase_order_line_id: str


class InvoiceLineInput(POLineInput):
    purchase_order_line_id: str


class HeaderInput(StrictModel):
    supplier_id: str
    number: Annotated[str, Field(min_length=1, max_length=80)]
    date: date
    notes: Annotated[str, Field(max_length=2000)] | None = None


class CurrencyInput(HeaderInput):
    currency: str = 'SAR'

    @field_validator('currency')
    @classmethod
    def iso_currency(cls, value):
        value = value.upper()
        if not pycountry.currencies.get(alpha_3=value):
            raise ValueError('Use a valid ISO 4217 currency code')
        return value


class POInput(CurrencyInput):
    lines: Annotated[list[POLineInput], Field(min_length=1, max_length=200)]


class ReceiptInput(HeaderInput):
    purchase_order_id: str
    lines: Annotated[list[ReceiptLineInput], Field(min_length=1, max_length=200)]


class InvoiceInput(CurrencyInput):
    purchase_order_id: str
    lines: Annotated[list[InvoiceLineInput], Field(min_length=1, max_length=200)]


def line_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        return (quantity * unit_price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def sum_money(values) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        return sum(values, Decimal('0.00'))
