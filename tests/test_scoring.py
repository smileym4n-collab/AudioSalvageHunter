import unittest

from audio_salvage_hunter.models import DonorEquipment, Listing
from audio_salvage_hunter.scoring import score_listing


TERMS = {
    "desirable_components": ["PCM1794", "DAC", "op amp"],
    "powers_on": ["powers on"],
    "optical_mechanical_fault": ["optical", "tray"],
    "internal_photos": ["pcb photos"],
    "water_damage": ["water damage"],
    "burnt_smoke_damage": ["burnt", "smoke damage"],
    "no_audio": ["no audio", "no sound"],
    "missing_parts": ["missing board", "parts removed"],
    "collection_only": ["collection only"],
}


DONORS = [
    DonorEquipment(
        manufacturer="",
        model="ASUS Xonar Essence STX",
        aliases=("Essence STX",),
        category="PCIe sound card",
        valuable_components=("PCM1792A DAC", "op-amps"),
        component_type=("standalone DAC", "op-amp"),
        confidence_level="confirmed",
        desirability_score=96,
        maximum_total_price_gbp=150,
        ideal_fault_types=("powers on",),
        risky_fault_types=("water damage",),
        salvage_difficulty="medium",
        package_or_removal_notes="",
        source_or_verification_note="fixture",
        general_comments="",
        notes="",
    )
]


def listing(title: str, total: float | None = 40.0) -> Listing:
    return Listing(
        item_id="1",
        title=title,
        item_url="https://example.invalid",
        price=total,
        postage=0 if total is not None else None,
        total_price=total,
        currency="GBP",
        condition="For parts or not working",
        seller="seller",
        location="London, GB",
        image_url="",
        start_time="",
        end_time="",
    )


class ScoringTests(unittest.TestCase):
    def test_score_rewards_donor_model_salvage_signals_and_price(self) -> None:
        result = score_listing(
            listing("ASUS Xonar Essence STX faulty powers on with PCB photos"),
            DONORS,
            TERMS,
            collection_only_penalty=12,
            default_max_total_price_gbp=80,
        )
        self.assertEqual(result.score, 80)
        self.assertEqual(result.matched_donor, "ASUS Xonar Essence STX")
        self.assertTrue(any("Possible reusable components" in reason for reason in result.reasons))
        self.assertTrue(any("Final score calculation" in reason for reason in result.reasons))

    def test_positive_and_negative_fault_phrases_are_explained(self) -> None:
        result = score_listing(
            listing("ASUS Xonar Essence STX powers on tray fault no audio water damage"),
            DONORS,
            TERMS,
            collection_only_penalty=12,
            default_max_total_price_gbp=80,
        )
        self.assertIn("powers-on", " ".join(result.positive_indicators))
        self.assertIn("non-audio fault", " ".join(result.positive_indicators))
        self.assertIn("water", " ".join(result.risk_indicators))
        self.assertIn("no audio", " ".join(result.risk_indicators))

    def test_score_penalises_water_missing_parts_no_audio_and_collection_only(self) -> None:
        result = score_listing(
            listing("ASUS Xonar Essence STX no audio water damage missing board collection only"),
            DONORS,
            TERMS,
            collection_only_penalty=12,
            default_max_total_price_gbp=80,
        )
        self.assertEqual(result.score, 0)
        self.assertTrue(any("water" in reason.lower() for reason in result.reasons))
        self.assertTrue(any("collection-only" in reason.lower() for reason in result.reasons))

    def test_score_caps_at_100(self) -> None:
        result = score_listing(
            listing("ASUS Xonar Essence STX PCM1794 DAC op amp powers on optical tray pcb photos"),
            DONORS,
            TERMS,
            collection_only_penalty=12,
            default_max_total_price_gbp=80,
        )
        self.assertEqual(result.score, 100)
        self.assertGreater(result.raw_score, 100)

    def test_maximum_price_scoring(self) -> None:
        result = score_listing(
            listing("ASUS Xonar Essence STX", total=200.0),
            DONORS,
            TERMS,
            collection_only_penalty=12,
            default_max_total_price_gbp=80,
        )
        self.assertEqual(result.score, 50)
        self.assertTrue(any("above configured maximum" in reason for reason in result.reasons))


if __name__ == "__main__":
    unittest.main()
