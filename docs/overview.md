# FormAI Nedir?

## Kısa cevap

FormAI, form-heavy operasyonları daha az manuel tekrar, daha az kopyala-yapıştır ve daha görünür doğruluk sinyali ile yürütmek için tasarlanmış bir form işleme sistemidir.

Türkçe anlatımla:
- elindeki boş formu işe yarar hale getirir
- dolu formu okunabilir veriye çevirir
- gerekiyorsa bunu tekrar hedef forma basar
- tüm süreci insan review'ünü görünür tutarak yapar

Kısa İngilizce karşılık:
- `static form -> fillable workflow`
- `filled form -> structured extraction`
- `structured extraction -> final assembled output`

## Hangi problemi çözüyor?

Birçok ekip hâlâ şu akışla çalışır:
- düz PDF veya taranmış belge gelir
- biri belgeyi açar
- içindeki değerleri manuel okur
- başka bir sisteme veya başka bir forma tekrar girer
- son dokümanı temizleyip paylaşır

Bu akışın maliyeti:
- tekrar eden operasyon yükü
- insan hatası
- düşük izlenebilirlik
- review süreçlerinde görünmez risk
- özellikle hassas veride tooling seçimi baskısı

FormAI'nin önerdiği yaklaşım, bu süreci "tek platforma zorlamak" değil, **mevcut form dünyasının üstüne daha iyi bir intake ve assembly katmanı koymaktır**.

## Ürün olarak ne yapmak istiyor?

FormAI'nin asıl amacı bir OCR demosu olmak değildir.

Daha doğru tanım:
- kurumların mevcut form ekosistemini bozmadan
- mevcut PDF ve görsel dünyasıyla uyumlu kalarak
- daha hızlı ve daha yönetilebilir bir form işlem hattı kurmak

Bu yüzden sistem üç farklı şeyi birlikte ele alır:
- belge analizi
- veri çıkarımı ve eşleme
- çıktı üretimi ve doğrulama

## Hangi senaryolarda anlamlı?

- sigorta hasar ve incident intake
- eğitim ve üniversite başvuru/dilekçe akışları
- HR onboarding ve consent benzeri formlar
- operasyon ve back-office veri toplama süreçleri
- hassas evrak akışlarında local/private deployment ihtiyacı olan işler

## Ne değildir?

- genel amaçlı doküman yönetim sistemi değildir
- baştan sona BPM ürünü değildir
- tam otomatik, review'süz, "her belgeyi her zaman kusursuz çözer" iddiasında değildir
- şu an için production-scale, tüm form ailelerinde kanıtlanmış bir sistem değildir

## Bugünkü ürün resmi

FormAI bugün şu bileşenlerden oluşur:
- Python çekirdek pipeline
- benchmark ve validation altyapısı
- FastAPI job servisi
- Next.js marketing site + internal workbench

Bugünkü en önemli güçlü yön:
- pipeline düşüncesi artık modüler ve profile-aware

Bugünkü en önemli açık:
- coordinate/placement ve visual verification tarafı, özellikle zor gerçek Türkçe formlarda hâlâ sertleştiriliyor
