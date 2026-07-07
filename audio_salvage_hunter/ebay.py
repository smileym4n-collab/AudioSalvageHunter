from __future__ import annotations

import base64
import logging
import time
from typing import Any, Iterable

from .models import Listing

LOG = logging.getLogger(__name__)

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
BUY_SCOPE = "https://api.ebay.com/oauth/api_scope"
MAX_BROWSE_LIMIT = 200


class EbayApiError(RuntimeError):
    pass


class EbayClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        marketplace_id: str = "EBAY_GB",
        timeout_seconds: int = 20,
        rate_limit_delay_seconds: float = 0.4,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.marketplace_id = marketplace_id
        self.timeout_seconds = timeout_seconds
        self.rate_limit_delay_seconds = rate_limit_delay_seconds
        try:
            import requests
        except ModuleNotFoundError as exc:
            raise EbayApiError("The requests package is required for live eBay searches. Install requirements.txt first.") from exc
        self.session = requests.Session()
        self._access_token: str | None = None

    def authenticate(self) -> str:
        credentials = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        basic = base64.b64encode(credentials).decode("ascii")
        response = self.session.post(
            TOKEN_URL,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": BUY_SCOPE},
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise EbayApiError(f"eBay OAuth failed with HTTP {response.status_code}: {response.text[:300]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise EbayApiError("eBay OAuth response was not valid JSON.") from exc
        token = payload.get("access_token")
        if not token:
            raise EbayApiError("eBay OAuth response did not contain an access_token")
        self._access_token = str(token)
        return self._access_token

    @property
    def access_token(self) -> str:
        if not self._access_token:
            return self.authenticate()
        return self._access_token

    def search(self, query: str, limit: int = 25, page_size: int = 50) -> list[Listing]:
        wanted = min(max(limit, 1), 10000)
        per_page = min(max(page_size, 1), MAX_BROWSE_LIMIT, wanted)
        listings: list[Listing] = []
        offset = 0
        while len(listings) < wanted:
            payload = self._search_page(query=query, limit=per_page, offset=offset)
            items = payload.get("itemSummaries", [])
            if not isinstance(items, list):
                raise EbayApiError(f"eBay search response for '{query}' did not contain an itemSummaries list.")
            listings.extend(parse_listing(item) for item in items if isinstance(item, dict))
            if len(items) < per_page:
                break
            offset += per_page
        return listings[:wanted]

    def _search_page(self, query: str, limit: int, offset: int) -> dict[str, Any]:
        time.sleep(self.rate_limit_delay_seconds)
        response = self.session.get(
            BROWSE_SEARCH_URL,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id,
            },
            params={
                "q": query,
                "limit": limit,
                "offset": offset,
                "fieldgroups": "EXTENDED",
            },
            timeout=self.timeout_seconds,
        )
        if response.status_code == 401:
            self._access_token = None
            response = self.session.get(
                BROWSE_SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id,
                },
                params={"q": query, "limit": limit, "offset": offset, "fieldgroups": "EXTENDED"},
                timeout=self.timeout_seconds,
            )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "unknown")
            raise EbayApiError(f"eBay rate limit reached; Retry-After={retry_after}")
        if response.status_code >= 400:
            raise EbayApiError(f"eBay search failed for '{query}' with HTTP {response.status_code}: {response.text[:300]}")
        try:
            data = response.json()
        except ValueError as exc:
            raise EbayApiError(f"eBay search response for '{query}' was not valid JSON.") from exc
        if not isinstance(data, dict):
            raise EbayApiError(f"eBay search response for '{query}' was not a JSON object.")
        return data


def money_value(data: dict[str, Any] | None) -> float | None:
    if not data:
        return None
    value = data.get("value")
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_shipping_cost(item: dict[str, Any]) -> float | None:
    options = item.get("shippingOptions") or []
    for option in options:
        cost = money_value(option.get("shippingCost"))
        if cost is not None:
            return cost
    return None


def has_shipping_options(item: dict[str, Any]) -> bool:
    options = item.get("shippingOptions")
    return isinstance(options, list) and len(options) > 0


def parse_location(item: dict[str, Any]) -> str:
    location = item.get("itemLocation") or {}
    parts = [
        location.get("city"),
        location.get("stateOrProvince"),
        location.get("postalCode"),
        location.get("country"),
    ]
    return ", ".join(str(part) for part in parts if part)


def parse_listing(item: dict[str, Any]) -> Listing:
    buying_options_raw = item.get("buyingOptions") or []
    buying_options = tuple(str(option) for option in buying_options_raw if option)
    current_bid = money_value(item.get("currentBidPrice"))
    standard_price = money_value(item.get("price"))
    if "AUCTION" in buying_options and current_bid is not None:
        price = current_bid
        price_basis = "current bid"
    else:
        price = standard_price
        price_basis = "item price"
    postage = first_shipping_cost(item)
    total = None
    postage_unknown = not has_shipping_options(item) or postage is None
    if price is not None and not postage_unknown:
        total = price + postage
    seller = item.get("seller") or {}
    image = item.get("image") or {}
    return Listing(
        item_id=str(item.get("itemId") or ""),
        title=str(item.get("title") or ""),
        item_url=str(item.get("itemWebUrl") or ""),
        price=price,
        postage=postage,
        total_price=total,
        currency=str((item.get("price") or {}).get("currency") or ""),
        condition=str(item.get("condition") or ""),
        seller=str(seller.get("username") or ""),
        location=parse_location(item),
        image_url=str(image.get("imageUrl") or ""),
        start_time=str(item.get("itemCreationDate") or ""),
        end_time=str(item.get("itemEndDate") or ""),
        buying_options=buying_options,
        price_basis=price_basis,
        postage_unknown=postage_unknown,
        raw=item,
    )


def deduplicate(listings: Iterable[Listing]) -> list[Listing]:
    unique_by_id: dict[str, Listing] = {}
    for listing in listings:
        if not listing.item_id:
            continue
        existing = unique_by_id.get(listing.item_id)
        if existing is None or is_better_duplicate(candidate=listing, existing=existing):
            unique_by_id[listing.item_id] = listing
    return list(unique_by_id.values())


def is_better_duplicate(candidate: Listing, existing: Listing) -> bool:
    if candidate.total_price is not None and existing.total_price is not None:
        return candidate.total_price < existing.total_price
    if candidate.total_price is not None and existing.total_price is None:
        return True
    if candidate.total_price is None and existing.total_price is not None:
        return False
    candidate_richness = sum(bool(value) for value in (candidate.condition, candidate.location, candidate.image_url, candidate.end_time))
    existing_richness = sum(bool(value) for value in (existing.condition, existing.location, existing.image_url, existing.end_time))
    return candidate_richness > existing_richness
