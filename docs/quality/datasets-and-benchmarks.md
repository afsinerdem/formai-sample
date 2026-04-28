# Dataset ve Benchmark Mantığı

## Neden benchmark katmanı var?

FormAI sadece "bir örnekte çalıştı" seviyesinde kalmamalı. Bu yüzden benchmark katmanı üç iş yapar:
- gerçek kalite seviyesini ölçmek
- regressions yakalamak
- ürünün hangi belge ailelerinde güçlü veya zayıf olduğunu görünür kılmak

## Aktif dataset aileleri

### FUNSD+

Amaç:
- genel printed/scanned form extraction için temel guard rail

Ne ölçer?
- field extraction doğruluğu
- coverage
- confidence davranışı

### FIR

Amaç:
- handwriting / noisy extraction ve zor OCR senaryoları

Ne ölçer?
- özellikle hassas alanlarda robustness
- police station / complainant / statutes benzeri problemli alanlar

### template_e2e

Amaç:
- sentetik ama ürün akışını daha uçtan uca test eden regression hattı

Ne ölçer?
- extraction + mapping + final behavior
- özellikle multiline ve witness/contact merge gibi davranışsal açıkları

### turkish_printed

Amaç:
- Türkçe printed form extraction

Ne ölçer?
- Türkçe label ve field ailelerinde temel okunabilirlik

### turkish_handwritten

Amaç:
- Türkçe el yazısı benzeri mini-pack

Ne ölçer?
- Türkçe handwritten robustness

Not:
- şu an çok güçlü görünse de fixture setinin fazla temiz olması bir risk olarak izlenmelidir

### turkish_petitions

Amaç:
- Türkçe petition / başvuru / öğrenci dilekçesi ailesini ayrı bir proving ground olarak ölçmek

Ne ölçer?
- Türkçe multiline
- tablo benzeri alanlar
- compound contact alanları
- kurum/öğrenci/danışman blokları

## Pack mantığı

Her dataset teorik olarak şu pack'leri destekler:
- `smoke`
- `regression`
- `tuning`
- `release`

Pratik anlamı:

### smoke

Hızlı sağlık kontrolü.

### regression

Önceden sorun çıkaran case'leri tekrar koşturur.

### tuning

İyileştirme sprintlerinde daha fazla örnekle deneme alanıdır.

### release

Daha sıkı release görünümü için seçilmiş subset.

## Çıktı artefact'ları

Benchmark koşuları sadece tek bir skor üretmez.

Standart artefact seti:
- `summary.json`
- `samples.jsonl`
- `worst_cases.md`
- `showcase/`

Validation-first koşularda ek olarak:
- `validation_summary.json`
- `dataset_summaries/`
- `manual_review_queue.json`

Bu yaklaşımın nedeni:
- sadece aggregate metric yetmez
- insan gözüyle incelenebilir kötü örnekler de gerekir

## Bugünkü snapshot özeti

### FIR smoke

- `field_normalized_exact_match = 0.7368`
- `field_coverage = 1.0`

### template_e2e smoke

- `field_match_rate = 0.9048`
- `case_success_rate = 0.6667`

### turkish_printed smoke

- `field_normalized_exact_match = 0.9286`
- `field_coverage = 1.0`

### turkish_handwritten smoke

- `field_normalized_exact_match = 1.0`
- `field_coverage = 1.0`

### turkish_petitions

- local real gold report ve derived fixtures üzerinden aktif şekilde sertleştiriliyor
- henüz release-quality benchmark hattı olarak kabul edilmemeli

## Validation matrix

`validation_matrix`, tek bir dataset değil; bir release gate görünümüdür.

İçerdiği hatlar:
- `FUNSD+`
- `FIR`
- `template_e2e`
- `turkish_printed`
- `turkish_handwritten`
- `turkish_petitions`

Amaç:
- ürünün farklı ailelerde aynı anda düşüp düşmediğini görmek

## Doğru okuma biçimi

Yüksek skor = iyi sinyal

Ama tek başına yeterli değil.

Bir benchmark sonucu yorumlanırken birlikte bakılmalı:
- exact / match rate
- coverage
- confidence
- worst cases
- visual artifact kalitesi
- real-case verification
