# Statik PDF -> AcroForm Pipeline

## Neden bu pipeline kritik?

FormAI'nin en zor teknik problemi yalnız extraction değildir. Asıl zorluklardan biri, düz bir PDF'de doldurulabilir alanları **doğru yerde** üretmektir.

Bu yüzden coordinate/placement çözümü, profile-specific box yamalarıyla değil, genel bir `layout-to-widget` yaklaşımıyla ele alınır.

## Hedef akış

1. mevcut AcroForm kontrolü
2. PDF routing analizi
3. structure extraction veya visual extraction
4. form element classification
5. anchor-to-rect geometry generation
6. visual refinement
7. AcroForm widget creation
8. layout validation
9. output verification

## 1. Ön analiz ve routing

İlk soru:
- bu belgeye gerçekten dokunmamız gerekiyor mu?

Kararlar:
- belge zaten AcroForm ise yeniden field üretmeyiz
- dijital/metin bazlı ise `structure_first`
- taranmış/görüntü bazlı ise `vision_first`
- karışık ise `hybrid`

Kullanılan sinyaller:
- page text density
- sayfa boyutları
- embedded text durumu
- document identity
- bilinen profile / family eşleşmesi

## 2. Structure extraction

Dijital PDF'lerde ana kaynak `pdfplumber + PyMuPDF` yapısıdır.

Çıkarılan öğeler:
- text spans / labels
- lines
- rects
- tables
- checkbox-like boxes
- placeholder segments

Amaç:
- henüz field yaratmak değil
- önce belge layout'unu `FormStructure` gibi ortak bir temsile dökmek

## 3. Field classification ve anchor engine

Formlar aynı şeyi farklı görsel anchor'larla gösterir:
- `colon + dots`
- `colon + underline`
- `bare dots`
- `underline`
- `rect/box`
- `table cell`
- `placeholder text`
- `small square / checkbox`

FormAI'nin coordinate engine'i bu anchor'ları tanıyıp deterministik bir rect üretmelidir.

Precedence:
1. profile-specific semantic hints
2. language-specific hints
3. generic geometry inference

## 4. Canonical geometry

Önemli tasarım kararı:
- tüm field geometri hesapları önce top-based canonical space'te yapılır
- PDF widget yazımı sırasında bottom-based PDF koordinatına çevrilir

Bu sayede:
- raster/image space
- OCR crop space
- structure space
- PDF widget space
arasındaki karışıklık azalır

Genel kurallar:
- canonical box: `left, top, right, bottom`
- min width / min height clamp
- merkezi padding sabitleri
- font size: `field_height * 0.75` etrafında normalize edilmiş aralık

## 5. Hybrid refinement

Structure extraction çoğu alan için doğru başlangıç verir, ama kritik hatalar genelde küçük alanlarda çıkar:
- kısa tarih alanları
- tablo hücreleri
- küçük kod alanları
- anchor'a çok yakın satırlar

Bu yüzden ikinci aşama refinement gerekir:
- page rasterize edilir
- sorunlu alan crop'lanır
- görsel sanity check yapılır
- gerekirse küçük delta düzeltmesi uygulanır

Kural:
- dijital PDF'de structure ana kaynaktır
- görsel analiz düzeltici sinyaldir
- taranmış PDF'de roller tersine dönebilir

## 6. Widget creation

AcroForm widget üretimi tek yerde standartlaştırılmalıdır.

Her widget için zorunlu kayıtlar:
- object
- page `/Annots`
- root `/AcroForm /Fields`

Varsayılan görünüm:
- border yok
- background yok
- print flag açık
- Helvetica tabanlı appearance
- `NeedAppearances = true`

Buradaki amaç:
- orijinal form görünümünü bozmadan interaktif yapı eklemek

## 7. Fillable vs final ayrımı

FormAI iki farklı çıktı üretir:

### Fillable PDF

Makine ve operasyon için:
- interaktif
- field inspect edilebilir
- downstream otomasyon için uygun

### Final PDF

İnsan için:
- görsel olarak doğal
- çok dilli metin için daha güvenli
- gerektiğinde overlay render kullanır

Bu ayrım özellikle Türkçe karakterler ve kullanıcıya gösterilen nihai dosya için kritiktir.

## 8. Validation ve verification

Field count tek başına başarı değildir.

Bakılan ek sinyaller:
- overlap pair count
- tiny field count
- alignment quality
- output verification score
- review_required

Bu sayede "alan üretildi" ile "doğru yerde kullanılır halde üretildi" arasındaki fark görünür olur.

## Bugünkü açık alan

Bu pipeline'ın ana prensipleri artık kod tabanında mevcut olsa da, özellikle gerçek Türkçe petition gibi zor layout'larda coordinate/placement konusu hâlâ sertleştirilmektedir.

Yani mimari doğru yönde; fakat production-grade yerleşim kalitesi bütün form ailelerinde henüz tamamlanmış değildir.
