from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any


WALLET_KEY = "toolbox_wallet"
PRIMARY_CURRENCY = "tool_coin"
DAILY_GRANT = 500
CURRENCIES: dict[str, dict[str, str]] = {
    "tool_coin": {"name": "툴코인", "short": "TC", "color": "#2dd4bf"},
}
DEFAULT_WALLET: dict[str, Any] = {
    "currencies": {PRIMARY_CURRENCY: 2500},
    "last_daily_grant": "",
}


def wallet(config_store: object) -> dict[str, Any]:
    data = config_store.get(WALLET_KEY, default=None)
    changed = False
    if not isinstance(data, dict):
        data = deepcopy(DEFAULT_WALLET)
        config_store.set(WALLET_KEY, value=data)
        changed = True
    if "currencies" not in data:
        try:
            old_coins = int(data.get("coins", DEFAULT_WALLET["currencies"][PRIMARY_CURRENCY]))
        except (TypeError, ValueError, OverflowError):
            old_coins = DEFAULT_WALLET["currencies"][PRIMARY_CURRENCY]
        data["currencies"] = {PRIMARY_CURRENCY: old_coins}
        data.pop("coins", None)
        changed = True
    if not isinstance(data["currencies"], dict):
        data["currencies"] = {}
        changed = True
    data.setdefault("last_daily_grant", "")
    for key, value in list(data["currencies"].items()):
        try:
            cleaned = max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            cleaned = 0
        if data["currencies"][key] != cleaned:
            data["currencies"][key] = cleaned
            changed = True
    for key, value in DEFAULT_WALLET["currencies"].items():
        if key not in data["currencies"]:
            data["currencies"][key] = value
            changed = True
    if changed:
        config_store.set(WALLET_KEY, value=data)
    return data


def ensure_daily_grant(config_store: object) -> bool:
    data = wallet(config_store)
    today = date.today().isoformat()
    if data.get("last_daily_grant") == today:
        return False
    currencies = data.setdefault("currencies", {})
    currencies[PRIMARY_CURRENCY] = int(currencies.get(PRIMARY_CURRENCY, 0)) + DAILY_GRANT
    data["last_daily_grant"] = today
    config_store.set(WALLET_KEY, value=data)
    return True


def balance(config_store: object, currency: str = PRIMARY_CURRENCY) -> int:
    ensure_daily_grant(config_store)
    return int(wallet(config_store).get("currencies", {}).get(currency, 0))


def add_coins(config_store: object, amount: int, currency: str = PRIMARY_CURRENCY) -> int:
    data = wallet(config_store)
    currencies = data.setdefault("currencies", {})
    currencies[currency] = max(0, int(currencies.get(currency, 0)) + int(amount))
    config_store.set(WALLET_KEY, value=data)
    _notify_wallet_changed(config_store)
    return int(currencies[currency])


def spend_coins(config_store: object, amount: int, currency: str = PRIMARY_CURRENCY) -> bool:
    amount = int(amount)
    data = wallet(config_store)
    currencies = data.setdefault("currencies", {})
    current = int(currencies.get(currency, 0))
    if amount < 0 or current < amount:
        return False
    currencies[currency] = current - amount
    config_store.set(WALLET_KEY, value=data)
    _notify_wallet_changed(config_store)
    return True


def format_coins(value: int, currency: str = PRIMARY_CURRENCY) -> str:
    meta = CURRENCIES.get(currency, {"short": currency})
    return f"{int(value):,} {meta['short']}"


def currency_name(currency: str = PRIMARY_CURRENCY) -> str:
    return CURRENCIES.get(currency, {"name": currency})["name"]


def currency_color(currency: str = PRIMARY_CURRENCY) -> str:
    return CURRENCIES.get(currency, {"color": "#2dd4bf"})["color"]


def wallet_entries(config_store: object) -> list[tuple[str, str, int]]:
    ensure_daily_grant(config_store)
    currencies = wallet(config_store).get("currencies", {})
    entries: list[tuple[str, str, int]] = []
    known = list(CURRENCIES)
    for currency in known:
        entries.append((currency_name(currency), currency, int(currencies.get(currency, 0))))
    for currency, amount in currencies.items():
        if currency not in CURRENCIES:
            entries.append((currency, currency, int(amount)))
    return entries


def _notify_wallet_changed(config_store: object) -> None:
    owner = getattr(config_store, "owner", None)
    if owner is not None and hasattr(owner, "refresh_wallet_display"):
        owner.refresh_wallet_display()
