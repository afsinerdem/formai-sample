# Web Katmanı

## Rolü

Web uygulaması FormAI'nin iki ayrı yüzünü taşır:

### 1. Vitrin / marketing

Amaç:
- ürünün ne yaptığını anlatmak
- managed vs local deployment hikâyesini göstermek
- demo talebi toplamak

### 2. Operasyon yüzeyi / workbench

Amaç:
- gerçek pipeline'ı job bazlı çalıştırmak
- artefact görmek
- extraction, review item ve issue durumunu incelemek

## Sürüm ve teknoloji matrisi

### Uygulama sürümü

- `formai-workbench 0.2.0`

### Framework sürümleri

- Next.js `15.5.14`
- React `19.1.1`
- React DOM `19.1.1`
- TypeScript `5.9.3`

### Son doğrulanmış durum

- `npm run build` başarılı
- build artık offline-safe; `next/font/google` yerine repo-local font yükleme kullanılıyor

## Route yapısı

Ana route'lar:
- `/`
- `/demo`
- `/platform`
- `/pricing`
- `/security`
- `/solutions`
- `/workbench`
- `/workbench/jobs/[jobId]`
- `/workbench/jobs/[jobId]/artifacts/[artifactId]`

Ayrıca iş detayları için parallel route yüzeyi de vardır:
- `/jobs/[jobId]`
- `/jobs/[jobId]/artifacts/[artifactId]`

## Ana ekranlar

### Marketing home

Dosya merkezleri:
- `web/app/page.tsx`
- `web/components/marketing-home.tsx`

Anlattığı şey:
- FormAI'nin blank form -> fillable -> extraction -> final packet akışı
- managed cloud vs private local positioning
- demo / workbench giriş noktaları

### Demo page

Dosya merkezleri:
- `web/app/demo/page.tsx`
- `web/app/api/demo-leads/route.ts`

Amaç:
- satış/demo talebi toplamak
- CRM yoksa bile structured lead verisini local olarak yazmak

Lead storage:
- `tmp/web_demo_leads/demo_requests.jsonl`

### Workbench

Dosya merkezleri:
- `web/app/workbench/page.tsx`
- `web/components/workbench.tsx`

Amaç:
- full pipeline çalıştırmak
- analyze / prepare / extract / assemble adımlarını ayrı ayrı tetiklemek
- provider seçmek:
  - OpenAI
  - local GLM / Ollama

### Job detail

Dosya merkezleri:
- `web/app/workbench/jobs/[jobId]/page.tsx`
- `web/components/job-detail.tsx`

Amaç:
- job durumunu poll etmek
- step-level status görmek
- artifact indirmek veya preview etmek
- review item ve issue listesine bakmak

## Backend bağımlılığı

Web uygulaması, backend'e şu env ile bağlanır:
- `NEXT_PUBLIC_FORMAI_API_BASE_URL`

Default:
- `http://127.0.0.1:8000`

Kod merkezi:
- `web/lib/api.ts`

Bu da şunu gösterir:
- web tek başına tam ürün değildir
- esas operasyon yüzeyi API job servisine bağlıdır

## Build determinism

Web katmanında font yükleme artık dış ağa bağımlı değildir.

Bu kararın nedeni:
- CI ve yerel offline geliştirme akışını kırmamak
- PR doğrulamasını ağ erişimine bağımlı bırakmamak
- workbench doğrulamasını backend kalitesinden ayırabilmek

## UI checkpoint hikâyesi

Web tarafında önemli checkpoint'ler:
- API workbench checkpoint
- one-page site / Octolabs footer checkpoint
- UI polish checkpoint

Bu checkpoint'ler, web'in evrimini üç ana fazda anlatır:
- backend/workbench entegrasyonu
- marketing site kimliği
- mobil ve görsel polish

## Bugünkü dürüst durum

Web build stabil.

Ancak web'in gösterdiği ürün kalitesi, backend'in gerçek extraction/render kalitesine bağlıdır. Yani workbench'in güzel görünmesi, Türkçe petition hattının release-ready olduğu anlamına gelmez.
