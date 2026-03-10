"""
Pydantic models for request/response validation in the Transak gateway.

Provides type-safe, self-documenting data structures for all API I/O.
"""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class WidgetUrlRequest(BaseModel):
    """Input payload for POST /transak/widget-url."""

    fiatAmount: Optional[str] = Field(
        default=None,
        description="Fiat amount to pre-fill in the Transak widget (e.g. '50').",
    )
    fiatCurrency: str = Field(
        default="EUR",
        description="ISO 4217 fiat currency code (e.g. 'EUR', 'USD').",
        min_length=3,
        max_length=3,
    )
    partnerCustomerId: Optional[str] = Field(
        default=None,
        description="Identifier for the customer on the partner's platform.",
        max_length=64,
    )
    partnerOrderId: Optional[str] = Field(
        default=None,
        description="Unique order identifier for reconciliation.",
        max_length=64,
    )

    @field_validator("fiatCurrency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("fiatAmount")
    @classmethod
    def positive_fiat_amount(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            try:
                amount = float(value)
            except ValueError:
                raise ValueError("fiatAmount must be a numeric value")
            if amount <= 0:
                raise ValueError("fiatAmount must be greater than zero")
        return value


class WidgetUrlResponse(BaseModel):
    """Successful response from POST /transak/widget-url."""

    success: bool = True
    widgetUrl: str
    walletAddress: str
    network: str = "polygon"
    cryptoCurrencyCode: str = "MATIC"


class ErrorResponse(BaseModel):
    """Standardised error response."""

    success: bool = False
    error: str
    details: str
