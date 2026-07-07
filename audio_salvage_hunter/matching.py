from __future__ import annotations

import re
from difflib import SequenceMatcher

from .models import DonorEquipment


WORD_RE = re.compile(r"[a-z0-9]+")

COMMON_NORMALISATIONS = {
    "xfi": "x fi",
    "x-fi": "x fi",
    "soundblaster": "sound blaster",
    "sonar": "xonar",
    "zonar": "xonar",
    "asusxonar": "asus xonar",
    "creativeaudigy": "creative audigy",
    "audigy4": "audigy 4",
    "essance": "essence",
    "titanum": "titanium",
    "titanimum": "titanium",
}


def normalize_text(value: str) -> str:
    text = value.lower().replace("_", " ").replace("-", " ")
    for wrong, right in COMMON_NORMALISATIONS.items():
        text = text.replace(wrong, right)
    return " ".join(WORD_RE.findall(text))


def fuzzy_ratio(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_text(left), normalize_text(right)).ratio()


def tokens(value: str) -> list[str]:
    normalized = normalize_text(value)
    return normalized.split() if normalized else []


def contains_term(text: str, term: str) -> bool:
    normalized_text = f" {normalize_text(text)} "
    normalized_term = normalize_text(term)
    return bool(normalized_term) and f" {normalized_term} " in normalized_text


def find_terms(text: str, terms: list[str] | tuple[str, ...]) -> list[str]:
    matches: list[str] = []
    normalized_text = normalize_text(text)
    for term in terms:
        normalized_term = normalize_text(term)
        if not normalized_term:
            continue
        if f" {normalized_term} " in f" {normalized_text} " or fuzzy_ratio(normalized_text, normalized_term) >= 0.92:
            matches.append(term)
    return matches


def best_window_ratio(text: str, term: str) -> float:
    text_tokens = tokens(text)
    term_tokens = tokens(term)
    if not text_tokens or not term_tokens:
        return 0.0
    width = len(term_tokens)
    best = fuzzy_ratio(" ".join(text_tokens[:width]), " ".join(term_tokens))
    for extra in (0, 1):
        window_width = width + extra
        if window_width <= 0 or window_width > len(text_tokens):
            continue
        for index in range(0, len(text_tokens) - window_width + 1):
            candidate = " ".join(text_tokens[index : index + window_width])
            best = max(best, fuzzy_ratio(candidate, " ".join(term_tokens)))
    return best


def match_donor(text: str, donors: list[DonorEquipment], threshold: float = 0.86) -> tuple[DonorEquipment | None, str | None, float]:
    best: tuple[DonorEquipment | None, str | None, float] = (None, None, 0.0)
    for donor in donors:
        for name in donor.all_names:
            if contains_term(text, name):
                return donor, name, 1.0
            ratio = best_window_ratio(text, name)
            if ratio > best[2]:
                best = (donor, name, ratio)
    if best[2] >= threshold:
        return best
    return None, None, best[2]
