# Ürün Vizyonu

## Ana fikir

FormAI'nin hedefi "formları ortadan kaldırmak" değil, form kullanan ekiplerin mevcut çalışma biçimini daha sakin, daha hızlı ve daha görünür hale getirmektir.

Bu nedenle FormAI bir `add-on` yaklaşımı seçer:
- ekip mevcut şablonunu korur
- FormAI o şablon etrafında daha iyi bir akış kurar
- review ve confidence görünür kalır

## Neden bu yaklaşım?

Gerçek dünyada ekipler şunları kolay kolay değiştiremez:
- resmi PDF şablonları
- kurumsal form tasarımları
- regulator veya üniversite/kurum kaynaklı belge formatları
- üçüncü taraflarla paylaşılan standart dokümanlar

Bu yüzden daha gerçekçi ürün stratejisi şudur:
- formu yeniden tasarlamak yerine formu "çalıştırılabilir" hale getirmek

## Ürün ilkeleri

### 1. Orijinal form dünyasına saygı

Kullanıcıyı yeni bir form sistemine taşımaya zorlamaz.

### 2. Review görünür kalır

Sistem low-confidence veya ambiguous sonuçları sessizce "başarılı" diye sunmaz.

### 3. Cloud ve local birlikte düşünülür

Bazı ekipler hız ister, bazıları veri kontrolü. FormAI her iki hikâyeyi de taşır:
- managed cloud
- private local / Ollama / GLM / OCR odaklı yol

### 4. Çıktı kadar geometri de önemlidir

FormAI için başarı sadece doğru text extraction değildir. Şu da önemlidir:
- field doğru yerde mi?
- fillable PDF gerçekten kullanılabilir mi?
- final PDF doğal görünüyor mu?

### 5. Form aileleri üzerinden ölçeklenme

Her belgeye tek tek hack yazmak yerine:
- document identity
- profile-driven routing
- verification
mantığıyla ölçeklenmek hedeflenir.

## Hedef kullanıcılar

- operasyon ekipleri
- compliance/back-office ekipleri
- sigorta intake ekipleri
- eğitim kurumu idari iş akışları
- hassas veriyle çalışan ekipler

## Ürün yüzeyleri

### Python core

Gerçek iş mantığı burada yaşar:
- template analizi
- fillable üretimi
- extraction
- final assembly
- verification

### API

Pipeline'ı asenkron job modeli ile servisleştirir.

### Web

İki işlev taşır:
- vitrin / marketing
- operasyon yüzeyi / workbench

## Bugün neden Turkish petition önemli?

Türkçe üniversite petition/form ailesi şu an ürün için önemli bir proving ground'dur çünkü:
- gerçek hayatta dağınık ve zor bir layout gösterir
- Türkçe karakter, multiline, tablo ve imza bloklarını birlikte taşır
- sistemin yalnız OCR değil, geometri ve çıktı kalitesini de zorlar

Bu case iyi hale gelirse, FormAI'nin genel mimarisinin gerçekten işe yaradığı daha anlamlı biçimde görülür.
