from app.services.places import district_from_text, normalize_place, resolve_place


def test_resolve_place_accepts_turkish_and_ascii_aliases():
    turkish = resolve_place("Kadıköy")
    ascii_name = resolve_place("Kadikoy")

    assert turkish is not None
    assert ascii_name is not None
    assert turkish.lat == ascii_name.lat
    assert turkish.district == "Kadikoy"


def test_normalize_place_handles_common_turkish_characters():
    assert normalize_place(" Beşiktaş, ") == "besiktas"
    assert normalize_place("BAŞAKŞEHİR") == "basaksehir"


def test_district_from_text_detects_exact_and_loose_district_mentions():
    assert district_from_text("Kadıköy") == "Kadıköy"
    assert district_from_text("Başakşehir merkez") == "Başakşehir"
    assert district_from_text("Kadıköy Rıhtım") == "Kadıköy"
