import tempfile
import unittest
from pathlib import Path

from audio_salvage_hunter.cli import detect_price_reduction, should_notify
from audio_salvage_hunter.config import ConfigError, load_config
from audio_salvage_hunter.donors import load_donors
from audio_salvage_hunter.models import Listing, ScoreResult
from audio_salvage_hunter.reports import ScoredListing
from audio_salvage_hunter.store import SeenStore


class ConfigAndStoreTests(unittest.TestCase):
    def test_malformed_configuration_file_raises_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.yaml"
            path.write_text("search_groups: nope\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_loads_expanded_donor_schema_and_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "donors.csv"
            path.write_text(
                "manufacturer,model,aliases,category,likely_valuable_components,component_type,confidence_level,desirability_score,maximum_worthwhile_delivered_price_gbp,ideal_fault_types,risky_fault_types,salvage_difficulty,package_or_removal_notes,source_or_verification_note,general_comments\n"
                "Test,Model 1,Alias 1|Alias 2,CD player,DAC; op-amp,standalone DAC|op-amp,probable,70,40,tray fault,water damage,medium,notes,verify photo,comments\n",
                encoding="utf-8",
            )
            donor = load_donors(path)[0]
            self.assertEqual(donor.manufacturer, "Test")
            self.assertEqual(donor.valuable_components, ("DAC", "op-amp"))
            self.assertEqual(donor.component_type, ("standalone DAC", "op-amp"))
            self.assertEqual(donor.confidence_level, "probable")

    def test_price_drop_detection(self) -> None:
        self.assertEqual(detect_price_reduction(100.0, 90.0, 5.0), 10.0)
        self.assertIsNone(detect_price_reduction(100.0, 97.0, 5.0))
        self.assertIsNone(detect_price_reduction(None, 90.0, 5.0))

    def test_should_notify_only_new_or_price_drop_above_threshold(self) -> None:
        listing = Listing("1", "title", "url", 10, 2, 12, "GBP", "", "", "", "", "", "")
        score = ScoreResult(score=70, reasons=[])
        self.assertTrue(should_notify(ScoredListing(listing, score, True, None), 65))
        self.assertTrue(should_notify(ScoredListing(listing, score, False, 6.0), 65))
        self.assertFalse(should_notify(ScoredListing(listing, score, False, None), 65))
        self.assertFalse(should_notify(ScoredListing(listing, ScoreResult(score=40, reasons=[]), True, None), 65))

    def test_seen_store_preserves_first_seen_and_best_price(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "seen.sqlite3"
            store = SeenStore(db_path)
            first = Listing("1", "first", "url", 20, 5, 25, "GBP", "", "", "", "", "", "")
            cheaper = Listing("1", "cheaper", "url", 15, 5, 20, "GBP", "", "", "", "", "", "")
            store.upsert(first, 70)
            first_seen = store.get("1").first_seen_at
            store.upsert(cheaper, 75)
            seen = store.get("1")
            store.close()
            self.assertEqual(seen.first_seen_at, first_seen)
            self.assertEqual(seen.best_total_price, 20)
            self.assertEqual(seen.last_total_price, 20)


if __name__ == "__main__":
    unittest.main()
