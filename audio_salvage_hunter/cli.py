from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from .config import load_config
from .donors import load_donors
from .ebay import EbayApiError, EbayClient, deduplicate
from .models import Listing
from .notify import send_telegram_notifications, telegram_configured
from .reports import ScoredListing, sort_results, terminal_report, write_csv, write_html
from .scoring import score_listing
from .store import SeenStore

LOG = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search eBay UK for audio salvage donor equipment.")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Alias for --mock-data; does not call eBay or write SQLite.")
    parser.add_argument("--mock-data", action="store_true", help="Use realistic sample listings without eBay credentials or SQLite writes.")
    parser.add_argument("--show-all", action="store_true", help="Show all results, not just listings above the alert threshold.")
    parser.add_argument("--no-telegram", action="store_true", help="Disable Telegram notifications for this run.")
    parser.add_argument("--telegram-test", action="store_true", help="Send a Telegram test message from mock data and exit.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def setup_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def mock_listings() -> list[Listing]:
    return [
        Listing(
            item_id="MOCK-001",
            title="ASUS Xonar Essence STX sound card faulty powers on internal PCB photos",
            item_url="https://www.ebay.co.uk/itm/MOCK-001",
            price=42.0,
            postage=4.5,
            total_price=46.5,
            currency="GBP",
            condition="Used, faulty",
            seller="sample-seller",
            location="Bristol, GB",
            image_url="",
            start_time="",
            end_time="",
            buying_options=("FIXED_PRICE",),
        ),
        Listing(
            item_id="MOCK-002",
            title="Creative X Fi Titanium HD spares repair water damage missing board",
            item_url="https://www.ebay.co.uk/itm/MOCK-002",
            price=20.0,
            postage=3.5,
            total_price=23.5,
            currency="GBP",
            condition="For parts or not working",
            seller="sample-seller",
            location="Leeds, GB",
            image_url="",
            start_time="",
            end_time="",
            buying_options=("AUCTION",),
            price_basis="current bid",
        ),
        Listing("MOCK-003", "Creative SB0380 Audigy 4 Pro untested job lot two cards", "https://www.ebay.co.uk/itm/MOCK-003", 31.0, 5.0, 36.0, "GBP", "For parts or not working", "audio-clearout", "Manchester, GB", "", "", "", ("AUCTION",), "current bid"),
        Listing("MOCK-004", "ASUS Sonar Essance STX misspelled listing powers on op amp DAC", "https://www.ebay.co.uk/itm/MOCK-004", 58.0, 4.0, 62.0, "GBP", "Used", "pcpartsuk", "Cardiff, GB", "", "", "", ("FIXED_PRICE",), "item price"),
        Listing("MOCK-005", "ASUS Xonar D2X PCIe sound card no audio output", "https://www.ebay.co.uk/itm/MOCK-005", 29.0, 3.99, 32.99, "GBP", "Faulty", "retro-audio", "York, GB", "", "", "", ("FIXED_PRICE",), "item price"),
        Listing("MOCK-006", "Xonar Essence ST rare card boxed but overpriced", "https://www.ebay.co.uk/itm/MOCK-006", 220.0, 8.0, 228.0, "GBP", "Used", "optimistic-seller", "London, GB", "", "", "", ("FIXED_PRICE", "BEST_OFFER"), "item price"),
        Listing("MOCK-007", "Creative SB1270 USB X-Fi HD phono ADC powers on", "https://www.ebay.co.uk/itm/MOCK-007", 18.0, 3.0, 21.0, "GBP", "Untested", "cablebox", "Glasgow, GB", "", "", "", ("AUCTION",), "current bid"),
        Listing("MOCK-008", "Job lot audio boards transformers op amp DAC unknown models", "https://www.ebay.co.uk/itm/MOCK-008", 24.0, 7.0, 31.0, "GBP", "Spares or repair", "workshop-clearance", "Birmingham, GB", "", "", "", ("FIXED_PRICE",), "item price"),
        Listing("MOCK-009", "ASUS Xonar D2 sound card collection only lights up", "https://www.ebay.co.uk/itm/MOCK-009", 25.0, None, None, "GBP", "Faulty", "local-only", "Norwich, GB", "", "", "", ("FIXED_PRICE",), "item price", True),
        Listing("MOCK-010", "Creative Audigy 4 Pro SB0380 burnt smell smoke damage", "https://www.ebay.co.uk/itm/MOCK-010", 9.99, 3.5, 13.49, "GBP", "Parts only", "honestseller", "Derby, GB", "", "", "", ("FIXED_PRICE",), "item price"),
        Listing("MOCK-011", "ASUS Xonar D2 laser optical fault listed by mistake", "https://www.ebay.co.uk/itm/MOCK-011", 35.0, 4.5, 39.5, "GBP", "Faulty", "mixed-electronics", "Exeter, GB", "", "", "", ("FIXED_PRICE",), "item price"),
        Listing("MOCK-012", "Creative sound card untested no model visible possible X-Fi", "https://www.ebay.co.uk/itm/MOCK-012", 12.0, 3.99, 15.99, "GBP", "Untested", "atticfinds", "", "", "", "", ("AUCTION",), "current bid"),
        Listing("MOCK-013", "ASUS Xonar Essence STX missing op amps parts removed", "https://www.ebay.co.uk/itm/MOCK-013", 45.0, 5.0, 50.0, "GBP", "For parts or not working", "repairbench", "Newcastle, GB", "", "", "", ("FIXED_PRICE",), "item price"),
        Listing("MOCK-014", "Creative X-Fi Titanium HD internal photos board pictured", "https://www.ebay.co.uk/itm/MOCK-014", 75.0, 4.0, 79.0, "GBP", "Used", "camera-shy", "Bath, GB", "", "", "", ("FIXED_PRICE",), "item price"),
        Listing("MOCK-015", "Vintage amplifier job lot transformers power amp parts water damage", "https://www.ebay.co.uk/itm/MOCK-015", 40.0, 12.0, 52.0, "GBP", "Spares repair", "shed-clearance", "Swansea, GB", "", "", "", ("FIXED_PRICE",), "item price"),
        Listing("MOCK-016", "ASUS Xonar Essence STX postage not specified", "https://www.ebay.co.uk/itm/MOCK-016", 64.0, None, None, "GBP", "Used", "unknown-postage", "Leicester, GB", "", "", "", ("FIXED_PRICE",), "item price", True),
        Listing("MOCK-017", "Creative SB0380 duplicate lower price", "https://www.ebay.co.uk/itm/MOCK-017", 30.0, 4.0, 34.0, "GBP", "Untested", "duplicate-demo", "Oxford, GB", "", "", "", ("FIXED_PRICE",), "item price"),
        Listing("MOCK-017", "Creative SB0380 duplicate higher price", "https://www.ebay.co.uk/itm/MOCK-017", 35.0, 4.0, 39.0, "GBP", "Untested", "duplicate-demo", "Oxford, GB", "", "", "", ("FIXED_PRICE",), "item price"),
    ]


def collect_queries(search_groups: dict[str, list[str]]) -> list[tuple[str, str]]:
    queries: list[tuple[str, str]] = []
    for group_name, terms in search_groups.items():
        for term in terms:
            queries.append((group_name, term))
    return queries


def should_notify(row: ScoredListing, minimum_score: int) -> bool:
    return row.score.score >= minimum_score and (row.is_new or row.price_reduction is not None)


def detect_price_reduction(previous_best: float | None, current_total: float | None, meaningful_drop: float) -> float | None:
    if previous_best is None or current_total is None:
        return None
    reduction = previous_best - current_total
    return reduction if reduction >= meaningful_drop else None


def run() -> int:
    args = parse_args()
    setup_logging(args.log_level)
    config = load_config(args.config)
    settings = config.settings

    donors = load_donors(settings.get("donor_database_path", "donor_database.csv"))
    minimum_score = int(settings.get("minimum_alert_score", 65))
    meaningful_drop = float(settings.get("meaningful_price_reduction_gbp", 5.0))
    reports_dir = Path(settings.get("reports_dir", "reports"))
    reports_dir.mkdir(parents=True, exist_ok=True)

    use_mock_data = args.dry_run or args.mock_data or args.telegram_test

    if use_mock_data:
        LOG.info("Mock-data mode enabled; using sample listings and leaving SQLite untouched.")
        listings = deduplicate(mock_listings())
        store = None
    else:
        client_id = os.getenv("EBAY_CLIENT_ID")
        client_secret = os.getenv("EBAY_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise SystemExit("EBAY_CLIENT_ID and EBAY_CLIENT_SECRET must be set unless --mock-data or --dry-run is used.")
        client = EbayClient(
            client_id=client_id,
            client_secret=client_secret,
            marketplace_id=str(settings.get("marketplace_id", "EBAY_GB")),
            timeout_seconds=int(settings.get("request_timeout_seconds", 20)),
            rate_limit_delay_seconds=float(settings.get("rate_limit_delay_seconds", 0.4)),
        )
        found: list[Listing] = []
        for group_name, query in collect_queries(config.search_groups):
            try:
                LOG.info("Searching %s: %s", group_name, query)
                found.extend(client.search(query, limit=int(settings.get("max_results_per_query", 25))))
            except EbayApiError as exc:
                LOG.warning("Skipping query after eBay API error: %s", exc)
        listings = deduplicate(found)
        store = SeenStore(settings.get("sqlite_path", "audio_salvage_hunter.sqlite3"))

    results: list[ScoredListing] = []
    for listing in listings:
        score = score_listing(
            listing=listing,
            donors=donors,
            scoring_terms=config.scoring_terms,
            collection_only_penalty=int(settings.get("collection_only_penalty", 12)),
            default_max_total_price_gbp=float(settings.get("default_max_total_price_gbp", 80)),
        )
        seen = store.get(listing.item_id) if store else None
        is_new = seen is None
        price_reduction = None
        if seen and listing.total_price is not None and seen.best_total_price is not None:
            price_reduction = detect_price_reduction(seen.best_total_price, listing.total_price, meaningful_drop)
        row = ScoredListing(listing=listing, score=score, is_new=is_new, price_reduction=price_reduction)
        results.append(row)
        if store:
            store.upsert(listing, score.score)

    results = sort_results(results)
    report_text = terminal_report(results, show_all=args.show_all, minimum_score=minimum_score)
    print(report_text)

    write_csv(results, reports_dir / "audio_salvage_hunter_report.csv")
    write_html(results, reports_dir / "audio_salvage_hunter_report.html", show_all=args.show_all, minimum_score=minimum_score)
    LOG.info("Wrote reports to %s", reports_dir)

    notify_rows = [row for row in results if should_notify(row, minimum_score)]
    if args.telegram_test:
        if not telegram_configured():
            raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set for --telegram-test.")
        send_telegram_notifications(notify_rows[:1] or results[:1])
        LOG.info("Sent Telegram test notification.")
    elif not use_mock_data and not args.no_telegram and telegram_configured() and notify_rows:
        send_telegram_notifications(notify_rows)
        LOG.info("Sent Telegram notifications for %d listings.", len(notify_rows))
    elif telegram_configured() and use_mock_data:
        LOG.info("Telegram is configured but mock-data/dry-run mode suppresses notifications unless --telegram-test is used.")

    if store:
        store.close()
    return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except KeyboardInterrupt:
        raise SystemExit("Interrupted.")


if __name__ == "__main__":
    main()
