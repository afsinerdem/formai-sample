# Repo Layout

Bu belge, repo içinde hangi klasörün ne işe yaradığını ve yeni bir mühendisin nereden başlaması gerektiğini anlatır.

## Kök klasör

### `src/`

Python ürün kodunun kaynağıdır.

Ana alt alanlar:
- `src/formai/agents/`
  - pipeline ajanları
- `src/formai/pdf/`
  - PDF structure, geometry, routing, detector, widget üretimi
- `src/formai/benchmarks/`
  - dataset adapter'ları, scoring, validation matrix
- `src/formai/verification/`
  - self-check ve verification engine
- `src/formai/llm/`
  - OpenAI, Ollama, GLM-OCR adapter'ları
- `src/formai/ocr/`
  - deterministic OCR yardımcıları
- `src/formai/rendering/`
  - final render layout/styling

### `tests/`

Unit ve integration test yüzeyidir.

Önemli test kümeleri:
- benchmark adapter ve scoring testleri
- pipeline integration testleri
- API smoke testleri
- roadmap/feature regression testleri
- segmentation testleri

### `scripts/`

Operasyon ve doğrulama script'leri:
- fillable field kontrolü
- field metadata çıkarma
- PDF -> image dönüşümü
- structure dump
- bounding box validasyonu
- dev/load recovery
- Turkish petition gold report

### `web/`

Next.js uygulaması.

İki rol:
- marketing site
- workbench / job inspection

Ana alt alanlar:
- `web/app/`
- `web/components/`
- `web/lib/`

### `docs/`

Projenin ana bilgi kaynağı.

### `checkpoints/`

Tarihsel checkpoint kayıtları.

Kalıcı kaynak kod alanı değildir; manifest-first tarihçe alanıdır.

### `tmp/`

Yerel scratch ve artifact alanı.

Source of truth değildir.

## Python core içinde nereden başlanır?

Yeni bir mühendis için önerilen okuma sırası:

1. `src/formai/pipeline.py`
2. `src/formai/models.py`
3. `src/formai/agents/input_evaluator.py`
4. `src/formai/agents/acroform_generator.py`
5. `src/formai/agents/data_extractor.py`
6. `src/formai/agents/final_assembler.py`
7. `src/formai/document_identity.py`
8. `src/formai/profiles.py`
9. `src/formai/verification/engine.py`

## Web tarafında nereden başlanır?

1. `web/app/page.tsx`
2. `web/components/marketing-home.tsx`
3. `web/app/workbench/page.tsx`
4. `web/components/workbench.tsx`
5. `web/components/job-detail.tsx`
6. `web/lib/api.ts`

## Benchmark tarafında nereden başlanır?

1. `src/formai/benchmarks/runner.py`
2. `src/formai/benchmarks/models.py`
3. `src/formai/benchmarks/scoring.py`
4. ilgili dataset adapter'ları

## Bu repo nasıl okunmalı?

Bu repo'yu "bir OCR demosu" gibi değil, şu dört katman olarak okumak daha doğrudur:
- ürün niyeti
- pipeline mantığı
- kalite ve benchmark sistemi
- sunum/operasyon yüzeyi

Bu yüzden teknik okuma öncesi şu belgeleri okumak önerilir:
- [Genel Bakış](../overview.md)
- [Sistem Mimarisi](system-overview.md)
- [Güncel Kalite Durumu](../quality/current-state.md)
