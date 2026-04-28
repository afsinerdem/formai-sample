# API ve Job Modeli

## Genel yaklaşım

FormAI'nin Python pipeline'ı yalnız CLI ile değil, FastAPI üzerinden job tabanlı servis olarak da çalışır.

Bu önemli çünkü ürün yalnız bir script değildir; artefact üretimi, review item takibi ve workbench entegrasyonu için servis katmanı gerekir.

## API sürümü

- API surface: `0.2.0`

Kaynak:
- `src/formai/api.py`

## İki yüzey var

### 1. Legacy sync endpoint'ler

İç uyumluluk ve basit kullanım için:
- `POST /analyze-template`
- `POST /prepare-fillable`
- `POST /extract-data`
- `POST /assemble`

### 2. Asenkron job endpoint'leri

Workbench ve operasyon için esas yüzey:
- `POST /jobs/analyze-template`
- `POST /jobs/prepare-fillable`
- `POST /jobs/extract-data`
- `POST /jobs/assemble`
- `POST /jobs/run-pipeline`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/artifacts`
- `GET /artifacts/{artifact_id}`

## Job modeli nasıl çalışır?

Her job için dosya tabanlı kayıt tutulur.

Ana parçalar:
- `job_id`
- `job_type`
- `status`
- `step_results`
- `artifacts`
- `issues`
- `review_items`
- `confidence`

Job depolama katmanı:
- `src/formai/api_jobs.py`

Varsayılan local dizin:
- `tmp/api_jobs`

## Artifact yaşam döngüsü

Her önemli ara veya final dosya artifact olarak kaydedilebilir:
- analysis JSON
- generation JSON
- fillable PDF
- extraction JSON
- final PDF
- self-check JSON

Bu yaklaşım workbench için önemlidir çünkü kullanıcı yalnız "başarılı/başarısız" değil, **çıktının kendisini** de görmek ister.

## Input güvenlik ve guardrail'ler

API yükleme katmanı şunları filtreler:
- template ve fillable için gerçek PDF zorunluluğu
- filled input için PDF veya raster image
- assemble için geçerli JSON object
- bozuk, boş, sahte uzantılı veya limit dışı input'lar `4xx`

Limitler env ile ayarlanabilir:
- upload size
- max image pixels

## Confidence ve review

Job yanıtları yalnız artefact vermez. Aynı zamanda:
- review items
- issues
- step confidence
taşır.

Bu, FormAI'nin "otomatik ama kör değil" tasarımının bir parçasıdır.

## Sağlık kontrolü

- `GET /health`

Bu endpoint, servis ayağa kalktı mı ve hangi working/runtime ayarlarıyla çalışıyor bilgisini döner.

## Web ile ilişkisi

Next.js workbench doğrudan bu job API'lerini kullanır.

Temel ilişki:
- frontend upload yapar
- API job oluşturur
- job status poll edilir
- artifact download/preview yapılır
