# FormAI 0.2.0 Release Manifest

## Kimlik

- Ürün sürümü: `0.2.0`
- Working tree base commit: `585e7b0830b7d88ffbceaa0771ddb92a8e512ea7`
- Short commit: `585e7b0`
- Branch: `codex/formai-checkpoint-20260317`
- Not: Bu manifest, hizalama ve dokümantasyon/arsiv normalizasyonu sonrası working-tree release kaydıdır; temiz bir release tag'i değildir.

## Bileşen sürümleri

### Core

- Python package `formai`: `0.2.0`
- API surface: `0.2.0`

### Web

- `formai-workbench`: `0.2.0`
- Next.js `15.5.14`
- React `19.1.1`
- React DOM `19.1.1`
- TypeScript `5.9.3`

## Doğrulama

### Python testleri

Komut:

```bash
env PYTHONPATH=src ./.venv311/bin/python -m unittest discover -s tests -v
```

Sonuç:
- `Ran 126 tests ... OK`

### Web build

Komut:

```bash
cd web
npm run build
```

Sonuç:
- `Next.js build OK` (offline-safe)

## Kalite snapshot'ı

### FIR smoke

Kaynak:
- `tmp/benchmarks/fir_smoke_v9/summary.json`

Özet:
- `field_normalized_exact_match = 0.7368`
- `field_coverage = 1.0`

### template_e2e smoke

Kaynak:
- `tmp/benchmarks/template_e2e_smoke_v4/summary.json`

Özet:
- `field_match_rate = 0.9048`
- `case_success_rate = 0.6667`

### Turkish petition gold case

Kaynak:
- `tmp/turkish_petition_gold_report_v26/summary.json`

Özet:
- `profile = student_petition_tr`
- `detected_field_count = 23`
- `generated_field_count = 23`
- `fillable_overlap_pair_count = 0`
- `extraction_confidence = 0.8415`
- `review_item_count = 0`
- `self_check_passed = false`
- `self_check_overall_score = 0.7011`

## Bilinen riskler

- Coordinate/placement ve visual alignment hâlâ ürünün birincil teknik riski
- Turkish petition hattı ilerlemiş olsa da production-ready diye sunulmamalı
- `turkish_handwritten` benchmark sonucu çok güçlü görünüyor; fixture zorluğu ayrıca gözden geçirilmeli
- Benchmark manifest sözleşmesi çok sayfayı destekleyecek şekilde genişletildi; eski tek sayfalı fixture'lar backward-compatible kaldı

## Arşiv ve kayıt notu

- Checkpoint klasörleri manifest-first hale getirildi
- Ağır checkpoint payload'ları `tmp/archive/20260326_154321/` altına taşındı
- Aktif `.next` build output'u ayrıca `tmp/archive/20260326_154803/` altına arşivlendi

## Referans belgeler

- [Genel Bakış](../../overview.md)
- [Sistem Mimarisi](../../architecture/system-overview.md)
- [Güncel Kalite Durumu](../../quality/current-state.md)
- [Web Katmanı](../../web/overview.md)
- [Release ve Arşiv Politikası](../../operations/release-and-archive.md)
