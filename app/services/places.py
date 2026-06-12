from __future__ import annotations

from dataclasses import dataclass
from unicodedata import normalize


@dataclass(frozen=True)
class ResolvedPlace:
    query: str
    name: str
    lat: float
    lon: float
    district: str | None = None
    neighborhood: str | None = None
    confidence: str = "curated"


_PLACES: tuple[ResolvedPlace, ...] = (
    ResolvedPlace("kadikoy", "Kadikoy", 40.9909, 29.0303, "Kadikoy"),
    ResolvedPlace("kadikoy rihtim", "Kadikoy Rihtim", 40.9909, 29.0303, "Kadikoy", "Osmanağa"),
    ResolvedPlace("moda", "Moda", 40.9870, 29.0250, "Kadikoy", "Caferağa"),
    ResolvedPlace("taksim", "Taksim", 41.0369, 28.9850, "Beyoglu", "Gümüşsuyu"),
    ResolvedPlace("besiktas", "Besiktas", 41.0438, 29.0094, "Besiktas"),
    ResolvedPlace("uskudar", "Uskudar", 41.0255, 29.0153, "Uskudar"),
    ResolvedPlace("eminonu", "Eminonu", 41.0179, 28.9705, "Fatih"),
    ResolvedPlace("fatih", "Fatih", 41.0167, 28.9497, "Fatih"),
    ResolvedPlace("levent", "Levent", 41.0812, 29.0105, "Besiktas"),
    ResolvedPlace("mecidiyekoy", "Mecidiyekoy", 41.0677, 28.9878, "Sisli"),
    ResolvedPlace("sisli", "Sisli", 41.0605, 28.9872, "Sisli"),
    ResolvedPlace("bakirkoy", "Bakirkoy", 40.9780, 28.8724, "Bakirkoy"),
    ResolvedPlace("atasehir", "Atasehir", 40.9923, 29.1244, "Atasehir"),
    ResolvedPlace("sariyer", "Sariyer", 41.1663, 29.0500, "Sariyer"),
    ResolvedPlace("kartal", "Kartal", 40.8998, 29.1936, "Kartal"),
)

_ALIASES = {
    "kadıkoy": "kadikoy",
    "kadıköy": "kadikoy",
    "kadiköy": "kadikoy",
    "kadikoy rihtim": "kadikoy rihtim",
    "kadıköy rıhtım": "kadikoy rihtim",
    "kadikoy rıhtım": "kadikoy rihtim",
    "beşiktaş": "besiktas",
    "besiktas": "besiktas",
    "üsküdar": "uskudar",
    "uskudar": "uskudar",
    "eminönü": "eminonu",
    "şişli": "sisli",
    "mecidiyeköy": "mecidiyekoy",
    "bakırköy": "bakirkoy",
    "ataşehir": "atasehir",
    "sarıyer": "sariyer",
}

_INDEX = {place.query: place for place in _PLACES}


def resolve_place(place: str) -> ResolvedPlace | None:
    key = normalize_place(place)
    return _INDEX.get(_ALIASES.get(key, key))


def known_place_names() -> list[str]:
    return sorted(place.name for place in _PLACES)


def normalize_place(value: str) -> str:
    normalized = normalize("NFKC", value).strip().casefold()
    replacements = str.maketrans(
        {
            "ı": "i",
            "ö": "o",
            "ü": "u",
            "ş": "s",
            "ğ": "g",
            "ç": "c",
            "İ": "i",
            ",": " ",
            ".": " ",
        }
    )
    return " ".join(normalized.translate(replacements).split())
