from __future__ import annotations

from .matching import find_terms, match_donor
from .models import DonorEquipment, Listing, ScoreResult


def score_listing(
    listing: Listing,
    donors: list[DonorEquipment],
    scoring_terms: dict[str, list[str]],
    collection_only_penalty: int,
    default_max_total_price_gbp: float,
) -> ScoreResult:
    raw_description = ""
    if isinstance(listing.raw, dict):
        raw_description = str(listing.raw.get("shortDescription") or "")
    text = " ".join(
        value
        for value in [
            listing.title,
            listing.condition,
            listing.location,
            listing.seller,
            " ".join(listing.buying_options),
            raw_description,
        ]
        if value
    )
    score = 0
    reasons: list[str] = []
    possible_components: list[str] = []
    positive_indicators: list[str] = []
    risk_indicators: list[str] = []

    donor, matched_name, ratio = match_donor(text, donors)
    max_price = default_max_total_price_gbp
    if donor:
        score += 50
        max_price = donor.maximum_total_price_gbp or default_max_total_price_gbp
        display_name = f"{donor.manufacturer} {donor.model}".strip()
        positive_indicators.append(f"donor model matched: {display_name} via '{matched_name}'")
        reasons.append(f"+50 model/alias match: {display_name} via '{matched_name}'")
        reasons.append(f"Donor confidence: {donor.confidence_level}; component type: {', '.join(donor.component_type) if donor.component_type else 'unspecified'}")
        possible_components.extend(donor.valuable_components)
    elif ratio >= 0.75:
        reasons.append(f"+0 nearest donor name was only a weak fuzzy match ({ratio:.2f}); model treated as unconfirmed")

    desirable = find_terms(text, scoring_terms.get("desirable_components", []))
    if desirable:
        score += 25
        possible_components.extend(desirable)
        positive_indicators.append("component keywords: " + ", ".join(desirable))
        reasons.append("+25 desirable component term appears in listing text: " + ", ".join(desirable))

    powers_on = find_terms(text, scoring_terms.get("powers_on", []))
    if powers_on:
        score += 10
        positive_indicators.append("powers-on language: " + ", ".join(powers_on))
        reasons.append("+10 seller says it powers on or lights up: " + ", ".join(powers_on))

    optical = find_terms(text, scoring_terms.get("optical_mechanical_fault", []))
    if optical:
        score += 15
        positive_indicators.append("non-audio fault language: " + ", ".join(optical))
        reasons.append("+15 fault appears optical, mechanical or cosmetic rather than core audio: " + ", ".join(optical))

    internal = find_terms(text, scoring_terms.get("internal_photos", []))
    if internal:
        score += 10
        positive_indicators.append("possible internal photos: " + ", ".join(internal))
        reasons.append("+10 listing text suggests internal PCB photos may be present: " + ", ".join(internal))

    if listing.total_price is not None and listing.total_price <= max_price:
        score += 10
        positive_indicators.append(f"price GBP {listing.total_price:.2f} <= maximum GBP {max_price:.2f}")
        reasons.append(f"+10 price comparison: delivered price GBP {listing.total_price:.2f} is at or below configured maximum GBP {max_price:.2f}")
    elif listing.total_price is None:
        reasons.append(f"+0 price comparison: delivered price unavailable, maximum for comparison is GBP {max_price:.2f}")
    else:
        reasons.append(f"+0 price comparison: delivered price GBP {listing.total_price:.2f} is above configured maximum GBP {max_price:.2f}")

    water = find_terms(text, scoring_terms.get("water_damage", []))
    if water:
        score -= 25
        risk_indicators.append("water/liquid/corrosion: " + ", ".join(water))
        reasons.append("-25 water, liquid or corrosion risk mentioned: " + ", ".join(water))

    burnt = find_terms(text, scoring_terms.get("burnt_smoke_damage", []))
    if burnt:
        score -= 30
        risk_indicators.append("burnt/smoke/blown: " + ", ".join(burnt))
        reasons.append("-30 burnt, blown or smoke damage risk mentioned: " + ", ".join(burnt))

    no_audio = find_terms(text, scoring_terms.get("no_audio", []))
    if no_audio:
        score -= 20
        risk_indicators.append("reported no audio/output: " + ", ".join(no_audio))
        reasons.append("-20 reported no audio or no output: " + ", ".join(no_audio))

    missing = find_terms(text, scoring_terms.get("missing_parts", []))
    if missing:
        score -= 25
        risk_indicators.append("missing major parts: " + ", ".join(missing))
        reasons.append("-25 missing boards or major parts risk: " + ", ".join(missing))

    collection = find_terms(text, scoring_terms.get("collection_only", []))
    if collection:
        score -= collection_only_penalty
        risk_indicators.append("collection only: " + ", ".join(collection))
        reasons.append(f"-{collection_only_penalty} collection-only penalty: " + ", ".join(collection))

    raw_score = score
    score = max(0, min(100, score))
    if possible_components:
        reasons.append("Possible reusable components, not confirmed without photos or part markings: " + ", ".join(sorted(set(possible_components))))
    if positive_indicators:
        reasons.append("Positive indicators: " + "; ".join(positive_indicators))
    if risk_indicators:
        reasons.append("Risk indicators: " + "; ".join(risk_indicators))
    reasons.append(f"Final score calculation: raw {raw_score}, clamped to {score} out of 100.")
    if not reasons:
        reasons.append("No strong salvage signals found.")

    return ScoreResult(
        score=score,
        reasons=reasons,
        matched_donor=f"{donor.manufacturer} {donor.model}".strip() if donor else None,
        matched_name=matched_name,
        matched_confidence=donor.confidence_level if donor else None,
        matched_component_types=list(donor.component_type) if donor else [],
        possible_components=sorted(set(possible_components)),
        positive_indicators=positive_indicators,
        risk_indicators=risk_indicators,
        raw_score=raw_score,
    )
