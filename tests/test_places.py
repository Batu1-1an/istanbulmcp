import pytest

from app.services.places import district_from_text, district_names, normalize_place, place_candidates, resolve_district, resolve_place


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


def test_district_from_text_reads_slash_and_parenthesized_address_suffixes():
    assert district_from_text("Harbiye Mh. Darülbedayi Cd. No:6 Şişli/İstanbul") == "Şişli"
    assert district_from_text("Yavuz Selim Mh. Fevzi Çakmak Cd. No:2 Esenler/İstanbul") == "Esenler"
    assert district_from_text("Cumhuriyet Cd. No:12 (Beyoğlu)") == "Beyoğlu"


@pytest.mark.parametrize("district", district_names())
def test_all_39_districts_resolve_in_turkish_and_ascii(district):
    assert len(district_names()) == 39
    for value in (district, district.upper(), normalize_place(district), f"{district} merkez", f"{district} ilçesi"):
        assert resolve_district(value) == district


@pytest.mark.parametrize("value", ["unknown street Pendik", "Kadıköy Üsküdar", "Pendik sahil", "Arnavutköy, Beşiktaş", ""])
def test_district_resolution_does_not_treat_an_address_or_neighborhood_as_a_district(value):
    assert resolve_district(value) is None


@pytest.mark.parametrize("name,district,lat,lon,entity,revision", [
    ("Bostancı", "Kadıköy", 40.95833333, 29.09555556, "Q3564169", "2522641156"),
    ("Karaköy", "Beyoğlu", 41.022777777778, 28.975, "Q2706262", "2553343183"),
    ("Nişantaşı", "Şişli", 41.051666666667, 28.991388888889, "Q251601", "2556915721"),
    ("Acıbadem, Kadıköy", "Kadıköy", 41.001667, 29.038611, "Q2823844", "2522640416"),
    ("Acıbadem, Üsküdar", "Üsküdar", 41.0073, 29.0533, "Q2756264", "2522640408"),
])
def test_reference_points_retain_checked_wikidata_coordinates_and_revision(name, district, lat, lon, entity, revision):
    place = resolve_place(name)
    assert place is not None
    assert (place.lat, place.lon, place.district) == (lat, lon, district)
    assert place.confidence == "wikidata_reference"
    assert place.source_url == f"https://www.wikidata.org/wiki/{entity}"
    assert place.source_revision == revision


def test_acibadem_requires_district_and_accepts_qualified_neighborhood_names():
    assert resolve_place("Acıbadem") is None
    assert len(place_candidates("ACIBADEM")) == 2
    for value in ("Üsküdar/Acıbadem", "Acibadem Mahallesi, Uskudar", "ÜSKÜDAR ACIBADEM MAH."):
        assert resolve_place(value).district == "Üsküdar"
    assert resolve_place("Bostancı, Üsküdar") is None
    assert resolve_place("Bostancı İstasyon Caddesi 10") is None
