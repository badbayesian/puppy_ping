from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class PetMedia:
    images: list[str] = field(default_factory=list)
    videos: list[str] = field(default_factory=list)
    embeds: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Return a compact summary of media counts.

        Returns:
            Human-readable summary string.
        """
        return f"{len(self.images)} images, {len(self.videos)} videos, {len(self.embeds)} embeds"


@dataclass(frozen=True)
class PetProfile:
    dog_id: int
    url: str

    species: str = "dog"
    name: Optional[str] = None
    breed: Optional[str] = None
    gender: Optional[str] = None
    age_raw: Optional[str] = None
    age_months: Optional[float] = None
    weight_lbs: Optional[float] = None

    location: Optional[str] = None
    status: Optional[str] = None

    ratings: dict[str, Optional[int]] = field(default_factory=dict)
    description: Optional[str] = None
    media: PetMedia = field(default_factory=PetMedia)

    scraped_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        """Normalize species to a lowercase value with a sensible default."""
        normalized = str(self.species or "dog").strip().lower()
        object.__setattr__(self, "species", normalized or "dog")

    @property
    def pet_id(self) -> int:
        """Return canonical species-agnostic profile identifier."""
        return self.dog_id

    def __str__(self) -> str:
        """Return a human-readable profile summary.

        Returns:
            Formatted profile string.
        """

        def fmt(v):
            return v if v is not None else "--"

        order = [
            "children",
            "dogs",
            "cats",
            "home_alone",
            "activity",
            "environment",
            "human_sociability",
            "enrichment",
        ]
        ratings_str = (
            ", ".join(
                f"{k.replace('_', ' ').title()}: {self.ratings.get(k) if self.ratings.get(k) is not None else '--'}"
                for k in order
                if k in self.ratings
            )
            or "--"
        )

        return (
            f"PetProfile #{self.pet_id} ({self.species})\n"
            f"{'-' * 88}\n"
            f"Name       : {fmt(self.name)}\n"
            f"Species    : {fmt(self.species)}\n"
            f"Breed      : {fmt(self.breed)}\n"
            f"Gender     : {fmt(self.gender)}\n"
            f"Age        : {fmt(self.age_months)} months\n"
            f"Weight     : {fmt(self.weight_lbs)} lbs\n"
            f"Location   : {fmt(self.location)}\n"
            f"Status     : {fmt(self.status)}\n\n"
            f"Ratings    : {ratings_str}\n"
            f"Media      : {self.media.summary()}\n\n"
            f"URL        : {self.url}\n"
            f"Scraped At : {self.scraped_at_utc}\n"
        )


# Backward-compatible aliases while callers migrate from dog-specific names.
DogMedia = PetMedia
PetsProfile = PetProfile
DogProfile = PetProfile
