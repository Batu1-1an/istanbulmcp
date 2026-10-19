# Bounded DataStore SQL

## Neden yerel SQLite?

Kontrol edilen İBB CKAN kurulumunda `datastore_search_sql` action'ı bilinmiyor.
Bu araç desteklenmeyen bir endpoint'e SQL göndermez. `datastore_search`
ile izin verilen **tek** resource'un tam, sınırlı kopyasını alır; ayrı bir
`:memory:` SQLite bağlantısında `records` tablosu üzerinden SELECT çalıştırır.

`istanbul_query_resource` basit upstream filtreleme için kalır. Yeni
`istanbul_datastore_query(resource_id,sql,limit?)`, GROUP BY/toplam/sıralama
gibi analiz içindir. SQL diyalekti SQLite'tır; PostgreSQL işlevleriyle aynı
davranış/ondalık hassasiyeti varsayılmamalıdır.

## Etkinleştirme

```bash
# Operatörün katalogdan kontrol ettiği etkin DataStore resource ID'leri:
export CKAN_SQL_ALLOWED_RESOURCE_IDS="<RESOURCE_ID_1>,<RESOURCE_ID_2>"
```

Varsayılan allowlist **boştur**. Tool keşfedilir ama yapılandırılmayan resource
için `resource_not_allowlisted` verir ve kaynağa istek yapmaz. Kullanıcı resource
URL'i, portal URL'i, yerel dosya adı veya SQLite bağlantısı belirleyemez.

Önce `istanbul_get_resource_schema` ile kolonları öğrenin. Ardından:

```json
{
  "name": "istanbul_datastore_query",
  "arguments": {
    "resource_id": "<ALLOWLISTED_RESOURCE_ID>",
    "sql": "SELECT district, COUNT(*) AS n FROM records GROUP BY district ORDER BY n DESC",
    "limit": 10
  }
}
```

Yazımdaki `district` örnektir; gerçek source kolon adını kullanın.
Gösterim limiti kullanıcı SQL'inde LIMIT olmasa, negatif veya çok büyük LIMIT
yazsa da dış SELECT ile en fazla 100'e sınırlandırılır. Bu, GROUP BY girdisini
örneklemek değildir; agregasyon her zaman tam kabul edilmiş kopyadan hesaplanır.

## Kabul edilen SQL

- Tek SELECT; tek `records` tablosu ve yayınlanmış kaynak kolonları.
- WHERE, GROUP BY, HAVING, ORDER BY, DISTINCT, LIMIT ve güvenli ifadeler.
- Fonksiyon allowlist'i: count, sum, avg, min, max, total, round, abs,
  coalesce, ifnull, nullif, lower, upper, length, substr/substring,
  trim/ltrim/rtrim, like, glob, date, datetime, strftime, julianday.
  CAST gibi SQLite sözdizimi de kullanılabilir.
- Join, alt sorgu, CTE, window, UNION, birden fazla statement yok.
- Write, ATTACH, PRAGMA, metadata tabloları, extension/file fonksiyonları yok.
- Sorgu 4.096 karakter ve 256 AST node ile sınırlı. Derin/karmaşık ifadeler
  ayrıca SQLite engine limitlerine tabidir.

SQLGlot AST doğrulaması birinci katmandır. İkinci katman, SQLite'ın
deny-by-default authorizer'ıdır: sadece kayıt tablosu READ, SELECT ve izinli
işlevler. `query_only`, kapalı trusted schema, attachment sınırı, zorunlu dış
LIMIT ve engine limitleri ayrıca uygulanır. Uygulamanın katalog, coğrafya veya
API kota DB'si bu bağlantıda **hiç açılmaz**. Kaynak kolon isimleri quoted
identifier, değerleri bound parametre olarak yüklenir; `executescript` kullanılmaz.

Bu bir tam AppSec/pentest raporu değildir. Sınırlandırılmış veri/SQL özelliğidir;
OS-seviyesinde ayrı sandbox veya mutlak process heap kotası iddia edilmez.

## Tamlık ve tazelik

1. `limit=0` metadata isteği: tam ve tahmin olmayan total + şema.
2. `_id asc` sıralı sayfalama: sayfalar aynı total/şemayı korumalı;
   _id'ler artan, benzersiz integer olmalı.
3. Son metadata kontrolü: total ve şema değişmemiş olmalı.
4. Ancak bundan sonra yerel sorgu çalışır.

Eksik sayfa, değişen/tahminî total, şema değişimi, yinelenen _id, byte/süre/satır
sınırı veya kaynak hatasında **kısmi agregasyon yapılmaz**. Tamamen boş ve
doğrulanmış kaynak ise COUNT(*)=0 döndürebilir.

Bu kontroller HTTP sayfalarını upstream transaction snapshot'ına dönüştürmez.
Aynı total ile kaynak değerleri değişebilir; bu sınırlama her başarılı cevabın
warnings alanında belirtilir. Freshness, **kopyanın alınma zamanı**dır; kayıtlara
anlık/bugüne ait damgası eklenmez. Kaynağın yayın zamanı bilinmiyorsa null kalır.

## Sınırlar

| Ayar | Varsayılan | Hard cap |
|---|---:|---:|
| `CKAN_SQL_MAX_ROWS` | 50.000 | 50.000 |
| `CKAN_SQL_MAX_BYTES` | 20 MiB | 20 MiB |
| `CKAN_SQL_PAGE_SIZE` | 5.000 | 5.000 |
| `CKAN_SQL_SNAPSHOT_TTL_SECONDS` | 900 | 3.600 |
| `CKAN_SQL_LOAD_TIMEOUT_SECONDS` | 30 | 60 |
| `CKAN_SQL_QUERY_TIMEOUT_SECONDS` | 0,5 | 2 |

- Byte bütçesi metadata dahil **bütün HTTP yanıtlarının toplamıdır**.
  identity encoding istenir; beklenmeyen sıkıştırma reddedilir.
  Content-Length ön kontrolü ve akış sırasında gerçek byte sayacı vardır.
  Redirect takip edilmez.
- Şema en fazla 80 kolon; hücre/SQLite row-length bütçesi 64 KiB.
  Kaynak tipine uymayan sayılar sessizce sıfır toplamına dönüşmez.
- Query VM bütçesi 2.000.000 instruction; çıktı en fazla 256 KiB ve 100 satır.
- Aynı process'te bir SQL yükleme/sorgusu kabul edilir, diğerleri `sql_busy`
  ile hızlı döner. İptal edilen sorgunun bounded worker'ı bitmeden kapı açılmaz.
- Ayrı cache'de en fazla **iki** tam kopya tutulur. Genel 1.024-entry source
  cache'i kullanılmaz. Python/SQLite memory gösterimi wire byte boyutundan
  **daha büyüktür**; küçük Railway instance'larında satır/byte limitini düşürün.
- Veri RAM cache'indedir; process restart'ta yeniden indirilir. API günlük kota
  sayacı ise SQLite disk dosyasında tutulur; bu ikisi farklıdır.

## Test

```bash
pytest tests/test_guarded_sql.py tests/test_datastore_sql.py tests/test_ckan_bounded.py
```

Fixture'lar metadata/sayfa/tamlık kontrolünü ve aggregate sonuçlarını doğrular.
Parser kapısı devreden çıkarılsa bile authorizer'ın dosya/metadata/extension
erişimini reddetmesi ayrı test edilir. Normal unit testler canlı İBB'ye bağlanmaz.
