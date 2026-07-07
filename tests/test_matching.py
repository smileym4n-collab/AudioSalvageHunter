import unittest

from audio_salvage_hunter.matching import find_terms, match_donor, normalize_text
from audio_salvage_hunter.models import DonorEquipment


def donor(model: str, aliases: tuple[str, ...] = ()) -> DonorEquipment:
    return DonorEquipment(
        manufacturer="",
        model=model,
        aliases=aliases,
        category="sound card",
        valuable_components=("DAC",),
        component_type=("standalone DAC",),
        confidence_level="confirmed",
        desirability_score=80,
        maximum_total_price_gbp=100,
        ideal_fault_types=(),
        risky_fault_types=(),
        salvage_difficulty="easy",
        package_or_removal_notes="",
        source_or_verification_note="",
        general_comments="",
        notes="",
    )


class MatchingTests(unittest.TestCase):
    def test_normalize_handles_common_xfi_and_xonar_misspellings(self) -> None:
        self.assertEqual(normalize_text("Creative XFi Titanium-HD"), "creative x fi titanium hd")
        self.assertEqual(normalize_text("ASUS Sonar Essence STX"), "asus xonar essence stx")

    def test_exact_model_matching(self) -> None:
        donors = [donor("Creative SB0380")]
        matched, matched_name, ratio = match_donor("Creative SB0380 faulty", donors)
        self.assertIsNotNone(matched)
        self.assertEqual(matched_name, "Creative SB0380")
        self.assertEqual(ratio, 1.0)

    def test_alias_matching(self) -> None:
        donors = [donor("ASUS Xonar Essence STX", ("Essence STX",))]
        matched, matched_name, ratio = match_donor("Essence STX faulty sound card", donors)
        self.assertIsNotNone(matched)
        self.assertEqual(matched.model, "ASUS Xonar Essence STX")
        self.assertEqual(matched_name, "Essence STX")
        self.assertEqual(ratio, 1.0)

    def test_fuzzy_matching_with_seller_spelling_mistakes(self) -> None:
        donors = [donor("ASUS Xonar Essence STX", ("Essence STX",))]
        matched, matched_name, ratio = match_donor("Asus Sonar Essance STX faulty", donors)
        self.assertIsNotNone(matched)
        self.assertEqual(matched.model, "ASUS Xonar Essence STX")
        self.assertEqual(matched_name, "ASUS Xonar Essence STX")
        self.assertGreaterEqual(ratio, 0.86)

    def test_component_keyword_matching(self) -> None:
        self.assertEqual(
            find_terms("Powers on, internal PCB photos, no sound, LM4562 op amp", ["powers on", "pcb photos", "water damage", "LM4562"]),
            ["powers on", "pcb photos", "LM4562"],
        )


if __name__ == "__main__":
    unittest.main()
