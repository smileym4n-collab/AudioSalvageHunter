from __future__ import annotations

import logging
import os

from .reports import ScoredListing, money

LOG = logging.getLogger(__name__)


def telegram_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def send_telegram_notifications(results: list[ScoredListing]) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    for row in results:
        listing = row.listing
        flag = "new listing" if row.is_new else f"price drop GBP {row.price_reduction:.2f}"
        text = (
            f"Audio Salvage Hunter: {flag}\n"
            f"Score {row.score.score} | {money(listing.total_price, listing.currency or 'GBP')} delivered\n"
            f"{listing.title}\n"
            f"{listing.item_url}\n\n"
            + "\n".join(f"- {reason}" for reason in row.score.reasons[:6])
        )
        try:
            import requests

            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": chat_id, "text": text, "disable_web_page_preview": "false"},
                timeout=15,
            )
            if response.status_code >= 400:
                LOG.warning("Telegram notification failed with HTTP %s: %s", response.status_code, response.text[:200])
        except ModuleNotFoundError:
            LOG.warning("Telegram notification skipped because the requests package is not installed.")
            return
        except Exception as exc:
            LOG.warning("Telegram notification failed: %s", exc)
