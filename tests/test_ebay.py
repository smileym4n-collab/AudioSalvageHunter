import unittest

from audio_salvage_hunter.ebay import deduplicate, parse_listing
from audio_salvage_hunter.models import Listing


class EbayParsingTests(unittest.TestCase):
    def test_total_price_uses_item_price_plus_shipping(self) -> None:
        listing = parse_listing(
            {
                "itemId": "1",
                "title": "ASUS Xonar D2",
                "price": {"value": "30.00", "currency": "GBP"},
                "shippingOptions": [{"shippingCost": {"value": "4.50", "currency": "GBP"}}],
                "seller": {"username": "seller"},
                "itemLocation": {"city": "Bristol", "country": "GB"},
                "buyingOptions": ["FIXED_PRICE"],
            }
        )
        self.assertEqual(listing.price, 30.0)
        self.assertEqual(listing.postage, 4.5)
        self.assertEqual(listing.total_price, 34.5)
        self.assertFalse(listing.postage_unknown)

    def test_missing_postage_keeps_delivered_total_unknown(self) -> None:
        listing = parse_listing({"itemId": "1", "title": "ASUS Xonar D2", "price": {"value": "30.00", "currency": "GBP"}})
        self.assertEqual(listing.price, 30.0)
        self.assertIsNone(listing.postage)
        self.assertIsNone(listing.total_price)
        self.assertTrue(listing.postage_unknown)

    def test_auction_uses_current_bid_when_available(self) -> None:
        listing = parse_listing(
            {
                "itemId": "1",
                "title": "Creative SB0380",
                "price": {"value": "50.00", "currency": "GBP"},
                "currentBidPrice": {"value": "12.50", "currency": "GBP"},
                "shippingOptions": [{"shippingCost": {"value": "3.00", "currency": "GBP"}}],
                "buyingOptions": ["AUCTION"],
            }
        )
        self.assertEqual(listing.price, 12.5)
        self.assertEqual(listing.total_price, 15.5)
        self.assertEqual(listing.price_basis, "current bid")

    def test_missing_api_fields_do_not_crash(self) -> None:
        listing = parse_listing({"itemId": "1"})
        self.assertEqual(listing.title, "")
        self.assertEqual(listing.location, "")
        self.assertIsNone(listing.price)
        self.assertIsNone(listing.total_price)

    def test_duplicate_detection_keeps_lower_known_total(self) -> None:
        high = Listing("1", "high", "url", 20, 5, 25, "GBP", "", "", "", "", "", "")
        low = Listing("1", "low", "url", 15, 5, 20, "GBP", "", "", "", "", "", "")
        other = Listing("2", "other", "url", 10, 1, 11, "GBP", "", "", "", "", "", "")
        unique = deduplicate([high, other, low])
        self.assertEqual(len(unique), 2)
        self.assertEqual([item for item in unique if item.item_id == "1"][0].title, "low")


if __name__ == "__main__":
    unittest.main()
