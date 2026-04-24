from __future__ import annotations

import re

from commercelens.schemas.product import Price

CURRENCY_SYMBOLS = {
    "$": "USD",
    "£": "GBP",
    "€": "EUR",
    "¥": "JPY",
    "₹": "INR",
}

CURRENCY_CODES = {"USD", "GBP", "EUR", "JPY", "INR", "AUD", "CAD", "NZD", "CHF", "CNY"}

PRICE_RE = re.compile(
    r"(?P<code>USD|GBP|EUR|JPY|INR|AUD|CAD|NZD|CHF|CNY)?\s*"
    r"(?P<symbol>[$£€¥₹])?\s*"
    r"(?P<amount>[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)",
    flags=re.IGNORECASE,
)


def parse_price(raw: str | None, default_currency: str | None = None) -> Price | None:
    if not raw:
        return None

    text = " ".join(raw.split())
    match = PRICE_RE.search(text)
    if not match:
        return Price(raw=text, currency=default_currency)

    amount_text = match.group("amount").replace(",", "")
    try:
        amount = float(amount_text)
    except ValueError:
        amount = None

    code = match.group("code")
    symbol = match.group("symbol")
    currency = None
    if code and code.upper() in CURRENCY_CODES:
        currency = code.upper()
    elif symbol:
        currency = CURRENCY_SYMBOLS.get(symbol)
    else:
        currency = default_currency

    return Price(amount=amount, currency=currency, raw=text)
