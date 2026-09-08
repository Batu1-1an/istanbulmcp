# Eczane yanıtlarında harita bağlantısı

Her gösterilen eczane için koordinat bağlantısı, koordinat yoksa adı, adresi,
ilçesi ve İstanbul bilgisiyle adres araması sunulur. Adres araması doğrulanmış
konum olarak gösterilmez. İlçe sonuçlarında mesafe sıralaması iddia edilmez.

Sunum tercihi iki eczane aracının açıklamasında belirtilir: İBB kaynak adı,
URL'si ve kaynak dipnotu kullanıcı kaynak istemedikçe yanıta yazılmaz.
`sources` teknik izlenebilirlik için korunur. Güncellik, eski veri ve telefonla
teyit uyarıları korunur. MCP istemcisi son yanıtın sunumunu kontrol eder;
sunucu açıklamaları istemci davranışını kesin olarak garanti etmez.

Kaynak alanlarını silmek yerine araç açıklaması kullanılması mevcut cevap
zarfını korur. Koordinatsız kayıtlarda mevcut harita arama yardımcısı kullanılır.
Fixture testleri koordinat bağlantısı ile adres aramasını ve ilçe sonuçlarında
bağlantı bulunmasını doğrular. Araç listesi kontrolü açıklamaların MCP üzerinden
sunulduğunu doğrular.

Dokümantasyon: Context7 ile `/modelcontextprotocol/python-sdk/v1.12.4`
belgeleri kontrol edildi; araç açıklamaları ve yapılandırılmış sonuçlar için
[Python SDK README](https://github.com/modelcontextprotocol/python-sdk/blob/v1.12.4/README.md)
örnekleri incelendi. Mevcut dekoratör ve sözlük dönüş sözleşmesi korundu.
