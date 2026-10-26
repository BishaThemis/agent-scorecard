# Agent Scorecard

[English](README.md) · **Türkçe**

Claude Code alt ajanlarının ne yaptığını izleyen, her görevi sabit ve incelenebilir kurallarla 100 üzerinden
puanlayan ve **doğrulanmış** sonucu gereksiz token harcamadan üreten ajanları ödüllendiren bir Claude Code
eklentisi. İngilizce/Türkçe dil seçimli bir masaüstü paneliyle gelir.

**Puanlama hiçbir zaman LLM çağırmaz.** Her şey Claude Code'un zaten diske yazdığı alt ajan transkriptlerinden,
sıradan Python kodu ve yerel bir SQLite dosyasıyla hesaplanır. Tek gereksinim Python 3.10+.

![Panel: puan dökümüyle görev listesi](docs/dashboard-tr.png)

## Ne yapar

- **Her alt ajanı izler:** hangi ajan hangi görevde çalıştı; girdi, çıktı ve önbellek tokenları, araç çağrıları, hatalar, süre ve API eşdeğeri maliyet.
- **Sonucu kanıtla karşılaştırır:** test çalıştırmaları, build/lint kontrolleri ve kabul kriterleri. Doğrulanamayan görev başarılı sayılmaz, *doğrulama bekliyor* olarak işaretlenir.
- **Her görevi altı bölümde 100 üzerinden puanlar.** Her puanın hangi veriden geldiği izlenebilir.
- **İyi işi ödüllendirir:** görev başına Elmas / Altın / Gümüş / Bronz kademeleri, ajan başına toplam puan ve başarı oranı.
- **İsrafı yakalar:** aynı girdiyle aynı çıktıyı veren ve arada hiçbir şeyin değişmediği tekrar çağrılar, değişiklik yapmadan tekrar denenen hatalar.
- **Yönlendirme önerir:** her görev kategorisi ve zorluğunda en iyi geçmişe sahip ajan. Öneri yalnızca yeterli veri varsa gösterilir.

## Kurulum

Claude Code'da:

```
/plugin marketplace add BishaThemis/agent-scorecard
/plugin install agent-scorecard@agent-scorecard
```

Ardından Claude Code'u yeniden başlatın. Hook'lar `python` komutunu çağırır; `python --version` komutunun
terminalde çalıştığından emin olun.

| Komut | Ne yapar |
|---|---|
| `/scorecard` | Karneyi sohbette metin olarak gösterir |
| `/scorecard dashboard` | Masaüstü panelini açar |
| `/scorecard --lang tr` | Karneyi Türkçe gösterir |

Panelin sağ üst köşesindeki **Dil** seçiminden arayüzü Türkçe ya da İngilizce yapabilirsiniz. Seçim kaydedilir
ve geçmiş görevlerin puan dökümleri de seçilen dilde gösterilir.

## Nasıl çalışır

1. **SubagentStart** hook'u ajanı hemen *Canlı* sekmesine ekler.
2. Ajan çalışırken panel transkriptini birkaç saniyede bir okuyup token ve araç sayılarını canlı gösterir.
3. **SubagentStop** hook'u biten transkripti ayrıştırır, ölçümleri kaydeder ve yeniden puanlar. Hook Claude'u hiçbir zaman engellemez; hataları `~/.agent-scorecard/hook.log` dosyasına yazar.
4. Görevler zaman sırasıyla puanlanır. Token referansı yalnızca o görev **başlamadan önce** bitmiş görevlerden alınır, bu yüzden yeni veri geldikçe eski puanlar oynamaz.

Kategori ve zorluk yalnızca görev açıklamasından ve isteminden çıkarılır, ajanın harcadığı tokenlardan değil.

## Puanlama kuralları

| Bölüm | Puan | Ölçüm |
|---|---:|---|
| Görev başarısı | 30 | Son test/build sonuçları, kabul kriterleri veya paneldeki oyunuz. Kanıt yoksa *doğrulama bekliyor*, 0 puan. Kısmen başarı en fazla 15. Bitmemiş işi bitti diye bildirmek: −15. |
| Çıktı kalitesi | 25 | Son test geçti: 15 · kabul kriterleri: 5 · gerileme yok: 5. Ölçülemeyen kısım verilmez. |
| Token verimliliği | 20 | Aynı kategori ve zorluktaki daha önce **başarılı** olmuş görevlerin ortalamasına göre: ≤0,5× → 20, 0,6× → 16, 0,8× → 10, 1,0× → 5, 1,2× → 2, ≥1,5× → 0, arası orantılı. Doğrulanmış başarı ve en az 3 referans görev gerekir. |
| Araç verimliliği | 10 | Aynı girdiyle aynı çıktıyı veren ve arada hiçbir şeyin değişmediği her çağrı için −1. Test ve build tekrarları cezalandırılmaz. Doğrulanmış başarı gerekir. |
| Hata yönetimi | 10 | Başarısız bir çağrıyı hiçbir şey değiştirmeden tekrar denemek, her seferinde −2. |
| Güvenilirlik | 5 | Kanıtlı rapor: 5 · "doğrulamadım" diye açıkça belirtmek: 3 · kanıt olmadan "bitti/testler geçti" iddiası: −15. Yanlış bildirim başarı bölümünde cezalandırıldıysa burada tekrar cezalandırılmaz. |

**Kademeler:** 95+ Elmas · 85+ Altın · 70+ Gümüş · 50+ Bronz. Her puan **ölçülebilir maksimumuyla** birlikte
gösterilir; örneğin *75/95*, token karşılaştırmasının henüz yapılamadığı bir görevi anlatır.

### İstem işaretleri

Ana ajan, alt ajan istemine bu satırları ekleyerek doğrulamayı ve karşılaştırmayı kesinleştirebilir.
İngilizce adlar da (`ACCEPT-FILE`, `ACCEPT-CMD`, `DIFFICULTY`, `CATEGORY`, `TASK-ID`) çalışır.

```
KABUL-DOSYA: src/odeme/fatura.py    # dosya var ve bu ajan yazdı/değiştirdi
KABUL-KOMUT: npm test               # ajan bu komutu çalıştırdı ve son çalıştırma geçti
ZORLUK: zor                         # kolay | orta | zor
KATEGORI: hata ayıklama
GOREV-ID: FAT-142                   # aynı işe birden fazla ajan veya deneme varsa gruplar
```

## Ayarlar

Tüm eşikler, ağırlıklar, tespit kalıpları ve model fiyatları
[`rules.json`](plugins/agent-scorecard/scripts/scorecard/rules.json) dosyasındadır. Değiştirmek için
`~/.agent-scorecard/rules.json` dosyasını oluşturup yalnızca değiştirmek istediğiniz anahtarları yazın, sonra
`python scripts/scorecard_cli.py rescore` komutunu çalıştırın. Fiyatı tanımlanmamış modellerin maliyeti tahmin
edilmez, "fiyatı bilinmiyor" olarak gösterilir.

## Bilinen sınırlar

- Maliyet, liste fiyatlarıyla hesaplanmış **API eşdeğeridir**; abonelikle kullanımda gerçek fatura değildir.
- Ana ajanın alt ajan için harcadığı tokenlar alt ajana yazılmaz.
- "Kısmen" ve "bitti" iddiaları İngilizce ve Türkçe metin kalıplarıyla bulunur, yanılabilir. Paneldeki oyunuz her zaman otomatik kararın önüne geçer.
- Claude Code eski transkriptleri `cleanupPeriodDays` süresi dolunca siler. Ölçümler veritabanında kalır ama silinen transkript yeniden ayrıştırılamaz.
- Transkript biçimi resmî bir arayüz değildir; ayrıştırıcı Claude Code 2.1.310 ile yazıldı.

Sonraki adımlar için: [ROADMAP.md](ROADMAP.md) (İngilizce).
