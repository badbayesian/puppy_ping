"""Shared filter normalization and query helpers for PupSwipe."""

from __future__ import annotations

import hashlib
import json
from html import escape

from puppyping.pupswipe.config import (
    MAX_BREED_FILTER_LENGTH,
    MAX_NAME_FILTER_LENGTH,
    MAX_PUPPY_AGE_MONTHS,
)

MAX_SPECIES_FILTER_LENGTH = 40
MIN_MAX_AGE_MONTHS = 0.5
MAX_MAX_AGE_MONTHS = 120.0


def normalize_breed_filter(value: str | None) -> str:
    """Normalize user-entered breed filter text."""
    text = " ".join((value or "").split()).strip()
    if not text:
        return ""
    return text[:MAX_BREED_FILTER_LENGTH]


def normalize_name_filter(value: str | None) -> str:
    """Normalize user-entered name filter text."""
    text = " ".join((value or "").split()).strip()
    if not text:
        return ""
    return text[:MAX_NAME_FILTER_LENGTH]


def normalize_provider_filter(value: str | None, sources: tuple[str, ...]) -> str:
    """Normalize provider filter text to known source keys."""
    candidate = (value or "").strip()
    if not candidate:
        return ""
    if candidate in sources:
        return candidate
    return ""


def normalize_species_filter(value: str | None) -> str:
    """Normalize species filter text."""
    text = " ".join((value or "").split()).strip().lower()
    if not text:
        return ""
    return text[:MAX_SPECIES_FILTER_LENGTH]


def normalize_max_age_filter(
    value,
    default: float = MAX_PUPPY_AGE_MONTHS,
) -> float:
    """Normalize age filter to a bounded positive month value."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(default)
    return max(MIN_MAX_AGE_MONTHS, min(MAX_MAX_AGE_MONTHS, parsed))


def normalized_filter_payload(
    *,
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    species_filter: str = "",
    max_age_months: float = MAX_PUPPY_AGE_MONTHS,
    sources: tuple[str, ...],
) -> dict[str, str | float]:
    """Build canonical normalized filter payload."""
    return {
        "breed": normalize_breed_filter(breed_filter),
        "name": normalize_name_filter(name_filter),
        "provider": normalize_provider_filter(provider_filter, sources),
        "species": normalize_species_filter(species_filter),
        "max_age": normalize_max_age_filter(max_age_months),
    }


def has_active_filters(payload: dict[str, str | float]) -> bool:
    """Return True when payload has at least one non-default filter value."""
    return bool(
        str(payload.get("breed") or "").strip()
        or str(payload.get("name") or "").strip()
        or str(payload.get("provider") or "").strip()
        or str(payload.get("species") or "").strip()
        or float(payload.get("max_age") or MAX_PUPPY_AGE_MONTHS) != MAX_PUPPY_AGE_MONTHS
    )


def filter_hash(payload: dict[str, str | float]) -> str:
    """Create short stable hash identifier for a filter payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def filter_hidden_inputs(
    *,
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    species_filter: str = "",
    max_age_months: float = MAX_PUPPY_AGE_MONTHS,
    filter_hash_value: str = "",
    review_mode: str = "",
    sources: tuple[str, ...],
) -> str:
    """Render hidden form inputs for currently active filters."""
    hidden_inputs: list[str] = []
    normalized_payload = normalized_filter_payload(
        breed_filter=breed_filter,
        name_filter=name_filter,
        provider_filter=provider_filter,
        species_filter=species_filter,
        max_age_months=max_age_months,
        sources=sources,
    )
    active_hash = (filter_hash_value or "").strip()
    if not active_hash and has_active_filters(normalized_payload):
        active_hash = filter_hash(normalized_payload)
    if active_hash:
        hidden_inputs.append(
            f'<input type="hidden" name="f" value="{escape(active_hash)}" />'
        )
    if (review_mode or "").strip().lower() == "passed":
        hidden_inputs.append('<input type="hidden" name="review" value="passed" />')
    return "\n            ".join(hidden_inputs)


def add_active_filters(
    query_params: dict[str, str],
    *,
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    species_filter: str = "",
    max_age_months: float = MAX_PUPPY_AGE_MONTHS,
    filter_hash_value: str = "",
    review_mode: str = "",
    sources: tuple[str, ...],
) -> dict[str, str]:
    """Attach non-empty filters to query params for redirects and links."""
    active_hash = (filter_hash_value or "").strip()
    if not active_hash:
        normalized_payload = normalized_filter_payload(
            breed_filter=breed_filter,
            name_filter=name_filter,
            provider_filter=provider_filter,
            species_filter=species_filter,
            max_age_months=max_age_months,
            sources=sources,
        )
        if has_active_filters(normalized_payload):
            active_hash = filter_hash(normalized_payload)
    if active_hash:
        query_params["f"] = active_hash
    if (review_mode or "").strip().lower() == "passed":
        query_params["review"] = "passed"
    return query_params
