# Yer ve ilçe çözümleme

2026-10-25: P1'in ilk aşaması, sürüm 0.2.1. Yeni araç eklenmedi; canlı araç sayısı değişmez.
SQL aracı, allowlist ve sorgu davranışı değişmedi.
Yeni `district` parametresi için istemcinin önbelleğindeki `tools/list` şemasını yenileyin.

## Kapsam

`istanbul_city_services_nearby` ve `istanbul_mobility_nearby`, `district` ile
İstanbul'un 39 ilçesini destekler. Türkçe/ASCII ve büyük/küçük harfler normalize
edilir. İlçe adı içeren keyfi bir sokak adresi ilçe sorgusuna dönüştürülmez.
Yalnız ilçe adı, `merkez` veya `ilçesi` ekiyle verilen `place` de ilçe modudur.

İlçe modunda koordinat üretilmez. Mobilite yalnız otopark; şehir hizmetleri
kütüphane ve kültür merkezi adresleri döndürür. WiFi ve diğer ulaşım bileşenleri
kontrol edilmez. `radius_m` doğrulanır fakat uygulanmaz; `limit` uygulanır.
Önceden `place="Kadıköy"` ile sabit merkez çevresinde WiFi aranıyordu; artık ilçe
modu kullanılır. Nokta çevresi için `Kadıköy Rıhtım` veya koordinat verin.

```text
istanbul_city_services_nearby(district="Pendik", limit=5)
istanbul_mobility_nearby(place="Başakşehir merkez", limit=5)
istanbul_city_services_nearby(place="Bostancı", radius_m=600)
istanbul_city_services_nearby(place="Acıbadem, Üsküdar")
```

`district`, `place` veya koordinatla karıştırılamaz. Bilinmeyen ilçe/adres kaynak
çağrısından önce reddedilir. Tek başına `Acıbadem`, `ambiguous_place` döndürür ve
Kadıköy/Üsküdar seçimini ister. Mahalle adını içeren hastane, cadde veya bina
adresi bir mahalle noktasına sessizce indirgenmez.

## Eklenen statik referanslar

Koordinat ve ilçe ilişkisi, 2026-10-25 tarihinde Wikidata'nın P625/P131
yapılandırılmış kayıtlarından kontrol edildi. Veriler CC0-1.0 kapsamındadır;
[lisans politikası](https://www.wikidata.org/wiki/Wikidata:Licensing).
Bu kontrol resmî belediye geocode doğrulaması veya saha ölçümü değildir.

| Yer | İlçe | Enlem, boylam | Wikidata sürümü |
|---|---|---|---|
| Bostancı | Kadıköy | 40.95833333, 29.09555556 | [Q3564169 / 2522641156](https://www.wikidata.org/w/index.php?title=Q3564169&oldid=2522641156) |
| Karaköy | Beyoğlu | 41.022777777778, 28.975 | [Q2706262 / 2553343183](https://www.wikidata.org/w/index.php?title=Q2706262&oldid=2553343183) |
| Nişantaşı | Şişli | 41.051666666667, 28.991388888889 | [Q251601 / 2556915721](https://www.wikidata.org/w/index.php?title=Q251601&oldid=2556915721) |
| Acıbadem | Kadıköy | 41.001667, 29.038611 | [Q2823844 / 2522640416](https://www.wikidata.org/w/index.php?title=Q2823844&oldid=2522640416) |
| Acıbadem | Üsküdar | 41.0073, 29.0533 | [Q2756264 / 2522640408](https://www.wikidata.org/w/index.php?title=Q2756264&oldid=2522640408) |

Semt olan Karaköy ve Nişantaşı için resmî mahalle adı uydurulmaz.
Yeni referanslar `confidence=wikidata_reference`, `coordinate_scope=area_reference_point`,
`source_revision`, `source_checked_on` taşır. `sources[]` içinde yayıncı
`Wikidata contributors`, lisans `CC0-1.0` ve kalıcı sürüm bağlantısı bulunur.
Sorgu anında Wikidata'ya istek yapılmaz; yeni API anahtarı veya servis bağımlılığı yoktur.

Önceden var olan 15 referansın koordinatları korunur. Yeni beş kayıtla toplam
20 nokta vardır. 39 ilçe desteği, 39 ilçe merkezi koordinatı veya tüm mahalle
kapsamı anlamına gelmez. Özetin veri tazeliği, statik yer noktasının güncel
olduğunu kanıtlamaz. Uzaklık referans noktasından hesaplanır; tam kullanıcı
adresi ya da doğrulanmış sınır merkezi değildir.

## Doğrulama

```bash
pytest tests/test_places.py tests/test_place_queries.py tests/test_city_service.py tests/test_city_open_data.py
pytest
```

Tüm 39 ilçe, Türkçe/ASCII eşleme, açık `district` ve ilçe `place` modları,
belirsiz Acıbadem, kaynak/lisans/sürüm, karışık girdiler, limit/yarıçap ve
başarısız kaynakların boş sonuç sayılmaması fixture/mock testleriyle sınanır.
İki MCP protokolünde yeni parametrenin şeması ve gerçek çağrı yolu test edilir.

Yerel tam paket sonucu: **1195 geçti, 25 atlandı** (opt-in canlı testler).
Yayın işlemi için güncel Railway CLI belgeleri Context7 `/railwayapp/cli`
üzerinden kontrol edildi: durum, deployment listesi ve sınırlı log okuma.

Sonraki aşama: lisansı ve işletim koşulları uygun, geniş kapsamlı adres/yer
indeksi. Bu değişiklik tam sokak/bina adresi geocoding'i sunduğunu iddia etmez.
