# Güncel Kalite Durumu

Bu belge, repo'nun bugünkü gerçek durumunu dürüstçe özetler.

## Doğrulanmış baseline

2026-03-30 itibarıyla yerel doğrulama:

- Python testleri: `126 tests OK`
- Web build: `Next.js build OK` (offline-safe)

Bu, projenin dağılmadığını ve temel yüzeylerin birlikte çalıştığını gösterir. Ancak bu sonuçlar tek başına ürün güveni anlamına gelmez.

## Güçlü alanlar

### 1. Mimari artık daha olgun

Projede artık şu kavramlar gerçekten var:
- document identity
- profile-driven routing
- structure-first / vision-first / hybrid routing
- benchmark ve validation matrix
- verification / self-check
- job tabanlı API
- Next.js workbench

### 2. Benchmark altyapısı genişledi

Aktif dataset ailesi:
- `FUNSD+`
- `FIR`
- `template_e2e`
- `turkish_printed`
- `turkish_handwritten`
- `turkish_petitions`

Ek olarak benchmark manifest sözleşmesi artık backward-compatible şekilde hem tek sayfa `page` hem çok sayfalı `pages[]` taşıyabiliyor. Bu özellikle `turkish_petitions` ve benzeri form aileleri için önemli.

### 3. Local-first yol gerçek

Kod tarafında default artık `auto` provider resolution. Sistem OpenAI key varmış gibi davranmıyor.

Bu önemli çünkü repo, managed cloud'a mecbur olmayan bir mimariye doğru ilerliyor.

## Kayıtlı benchmark snapshot'ları

Not: Bunlar aynı dakika içinde yeniden sertifikalanmış release paketleri değil, mevcut local snapshot'larda kayıtlı son anlamlı sonuçlardır.

### FIR smoke

Kaynak snapshot:
- `tmp/benchmarks/fir_smoke_v9/summary.json`

Durum:
- `field_normalized_exact_match = 0.7368`
- `field_coverage = 1.0`

Yorum:
- FIR hattı bir blocker olmaktan çıktı ama hâlâ mükemmel değil.

### template_e2e smoke

Kaynak snapshot:
- `tmp/benchmarks/template_e2e_smoke_v4/summary.json`

Durum:
- `field_match_rate = 0.9048`
- `case_success_rate = 0.6667`

Yorum:
- ürün davranışı kabul edilebilir seviyede ama zor case'ler hâlâ var.

### turkish_printed smoke

Kaynak snapshot:
- `tmp/benchmarks/turkish_printed_smoke_v3/summary.json`

Durum:
- `field_normalized_exact_match = 0.9286`
- `field_coverage = 1.0`

Yorum:
- printed Türkçe taraf umut verici.

### turkish_handwritten smoke

Kaynak snapshot:
- `tmp/benchmarks/turkish_handwritten_smoke_v3/summary.json`

Durum:
- `field_normalized_exact_match = 1.0`
- `field_coverage = 1.0`

Yorum:
- bu skor tek başına "tamam" demek için yeterli değil
- mevcut fixture setinin fazla temiz olma riski var

## En kritik gerçek case: Turkish petition

Referans local artefact seti:
- `tmp/turkish_petition_gold_report_v26/summary.json`
- `tmp/turkish_petition_gold_report_v26/extraction.json`
- `tmp/turkish_petition_gold_report_v26/self_check.json`

### Güçlü taraflar

- `profile = student_petition_tr`
- `document_family = student_petition`
- `detected_field_count = 23`
- `generated_field_count = 23`
- `fillable_overlap_pair_count = 0`

Bu, sistemin belgeyi tanıdığını ve teknik olarak fillable üretmeyi başardığını gösterir.

### Extraction tarafında toparlanan alanlar

Aşağıdaki alanlar anlamlı biçimde geliyor:
- `tarih`
- `ogrenci_no`
- `fakulte_birim`
- `ad_soyad`
- `bolum_program`
- `telefon`
- `e_posta`
- `ders_kodu`
- `ders_adi`
- `ders_kredisi`
- `akts`
- `ders_notu`
- `danisman_adi`
- `gno`
- `mali_onay_ad_soyad`

### Neden hâlâ release-ready değil?

Kaynak metrikler:
- `extraction_confidence = 0.8415`
- `review_item_count = 0`
- `self_check_passed = false`
- `self_check_overall_score = 0.7011`
- `geometry_score = 0.9989`
- `evidence_score = 0.3045`
- `llm_score = 0.8`

Ana sorun:
- route, fillable geometry ve local extraction artık aynı gerçek case üzerinde birlikte çalışıyor
- ama final visual alignment ve field-level OCR evidence hâlâ tam güvenilir değil

Özellikle zor alanlar:
- küçük tarih alanları
- üst paragraf içi inline alanlar
- tablo hücre okunabilirliği
- date + signature karışımı bloklar
- compound satırlar: `Tel No / E-posta`

Son `self_check` uyarı kümeleri:
- `critical:ad_soyad`
- `critical:ogrenci_no`
- `critical:telefon`
- `critical:e_posta`
- `critical:ders_kodu`
- `critical:ders_adi`
- `critical:danisman_gorusu`

### Dürüst sonuç

Turkish petition hattı artık "çalışmıyor" seviyesinde değil.
Ama hâlâ "production ready" de değil.

Bu ayrımı korumak önemli.

## İngilizce taraf için dürüst not

İngilizce akışların kod ve test seviyesi regression yüzeyi güçlü:
- API testleri
- pipeline integration
- mapping / postprocessing
- benchmark runner

Ancak her şey için aynı gün canlı provider-backed recertification yapılmış kabul edilmemeli. Mevcut kalite resmi, kod testleri ve kayıtlı benchmark snapshot'ları üzerinden okunmalıdır.

## Bugünkü ana riskler

### 1. Coordinate / placement güveni

En kritik ürün riski budur.

### 2. Visual verification hâlâ sertleştiriliyor

Self-check sistemi var, ama özellikle küçük alanlarda OCR evidence zayıf olabilir.

### 3. Fixture temsil gücü eşit değil

Özellikle `turkish_handwritten` çok iyi görünüyor; bu iyi olduğu kadar şüpheli de olabilir.

### 4. Repo operasyonal olarak ağır

Yerel çalışma alanında ciddi boyutta `tmp/` ve checkpoint birikimi bulunuyor.

## Bugünkü net okuma

FormAI:
- ürün fikri olarak güçlü
- mimari olarak anlamlı
- test ve benchmark açısından ciddi ilerlemiş
- API ve web yüzeyi olan bir ürün adayı

Ama:
- Türkçe zor gerçek formlarda tam güvenilir değil
- coordinate/placement problemi hâlâ ana teknik öncelik
- release dili dikkatli kurulmalı
