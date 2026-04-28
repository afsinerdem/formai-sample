# FormAI Sample

<div align="center">

**Document automation workbench for PDF templates, OCR/VLM extraction, rendering, and evaluation**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Web-Next.js-000000?logo=nextdotjs)](https://nextjs.org/)
[![Tests](https://img.shields.io/badge/tests-144%20passing%20%7C%209%20skipped-brightgreen)](#quality)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

[English](#english) · [Türkçe](#türkçe) · [Screenshots](#screenshots) · [Quick Start](#quick-start)

</div>

---

## English

FormAI Sample is a portfolio-grade document automation system that turns static PDF workflows into a more structured, testable, and product-like experience.

It combines a Python document pipeline, benchmark/evaluation utilities, an API surface, and a Next.js workbench into one monorepo. The project demonstrates how PDF template discovery, field extraction, fillable PDF generation, and final rendering can be handled as traceable engineering workflows instead of one-off scripts.

### What It Demonstrates

- Static PDF template analysis and field discovery
- Filled PDF/image extraction with OCR and VLM-oriented provider boundaries
- AcroForm generation and final PDF rendering flows
- Benchmark fixtures, quality reports, and reproducible evaluation notes
- Product-style Next.js workbench and marketing pages
- Local-first provider strategy with optional AI integrations

### Architecture Snapshot

```text
src/formai/     Core Python package, agents, pipeline, rendering, verification
tests/          Unit and integration-style test coverage
scripts/        Development, inspection, and verification utilities
web/            Next.js workbench and product-facing interface
docs/           Architecture, quality, API, release, and product notes
checkpoints/    Manifest-first historical project checkpoints
```

### Screenshots

| Marketing Site | Workbench |
|---|---|
| ![Landing page](docs/screenshots/landing.png) | ![Workbench](docs/screenshots/workbench.png) |

---

## Türkçe

FormAI Sample, statik PDF formlarını daha kullanılabilir ve otomasyon dostu bir akışa dönüştürmeyi gösteren portföy kalitesinde bir belge otomasyon projesidir.

Bu repo yalnızca bir demo script değil; Python tabanlı belge işleme pipeline'ı, benchmark araçları, API katmanı ve Next.js workbench arayüzünü tek bir monorepo içinde birleştirir. Amaç, PDF şablon keşfi, alan çıkarımı, doldurulabilir PDF üretimi ve nihai render süreçlerini izlenebilir ve test edilebilir bir yazılım mimarisi olarak göstermektir.

### Neyi Gösteriyor?

- Statik PDF şablon analizi ve alan keşfi
- Dolu PDF/görsel üzerinden OCR ve VLM odaklı veri çıkarımı
- AcroForm üretimi ve son kullanıcıya uygun PDF render akışı
- Benchmark fixture'ları, kalite raporları ve tekrar üretilebilir değerlendirme notları
- Next.js ile ürün hissi veren workbench ve tanıtım sayfaları
- Local-first provider yaklaşımı ve opsiyonel AI entegrasyonları

### Mimari Özeti

```text
src/formai/     Çekirdek Python paketleri, agent'lar, pipeline, render, doğrulama
tests/          Unit ve entegrasyon benzeri test kapsamı
scripts/        Geliştirme, inceleme ve doğrulama araçları
web/            Next.js workbench ve ürün arayüzü
docs/           Mimari, kalite, API, release ve ürün dokümantasyonu
checkpoints/    Manifest tabanlı tarihsel proje kayıtları
```

---

## Quick Start

### Python Core

```bash
python3.11 -m venv .venv311
source .venv311/bin/activate
pip install -e ".[vision,glm_ocr,commonforms,benchmarks,api,dev]"
```

### Web Workbench

```bash
cd web
npm install
npm run dev
```

### CLI Examples

```bash
PYTHONPATH=src ./.venv311/bin/python -m formai.cli analyze --template ./template.pdf
formai prepare-fillable --template ./template.pdf --output ./template.fillable.pdf
formai run --template ./template.pdf --filled ./filled-form.pdf --fillable-output ./template.fillable.pdf --final-output ./final.pdf
```

## Quality

The sample was verified in a clean Python 3.11 environment with:

```bash
env PYTHONPATH=src .venv311/bin/python -m unittest discover -s tests -q
```

Latest local verification result before publishing: `144 tests OK`, `9 skipped`.

## Documentation Map

- [Project overview](docs/overview.md)
- [Product vision](docs/product/vision.md)
- [System architecture](docs/architecture/system-overview.md)
- [PDF pipeline](docs/architecture/pdf-pipeline.md)
- [Current quality state](docs/quality/current-state.md)
- [Datasets and benchmarks](docs/quality/datasets-and-benchmarks.md)
- [API and jobs](docs/api-and-jobs.md)
- [Web overview](docs/web/overview.md)
- [Release and archive policy](docs/operations/release-and-archive.md)

## Runtime Notes

- Default provider behavior is `auto` and local-first.
- Optional AI providers require environment variables such as `OPENAI_API_KEY`.
- The web layer uses local fonts so builds are designed to stay deterministic without font network calls.
- For multilingual output, the interactive fillable PDF and final rendered PDF are treated as separate artifacts.

## Important Note

This repository is a public portfolio sample. It is designed to show architecture, product thinking, and automation workflows. Some real-world extraction scenarios still require careful human review and provider-specific tuning.
