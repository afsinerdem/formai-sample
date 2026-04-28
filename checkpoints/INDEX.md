# Checkpoint Index

Bu dosya, `checkpoints/` klasöründeki tarihsel kayıtları hızlıca anlamak için hazırlanmıştır.

Not:
- Her checkpoint bir ürün kararı, kalite sıçraması veya yüzey genişlemesini temsil eder.
- Uzun vadeli politika manifest-first arşiv modelidir; ağır artefact'lar repoda kalıcı kayıt olarak görülmemelidir.
- Bugün checkpoint klasörlerinde `MANIFEST.md` ve `artifacts.json` kalır; büyük payload'lar `tmp/archive/<timestamp>/checkpoints/` altına taşınır.

## Çekirdek pipeline evrimi

### 2026-03-17 01:01:38

- Klasör: `20260317_010138_formai_field_detection_checkpoint`
- Tema: ilk field detection checkpoint
- Öne çıkanlar:
  - scaffold ve temel pipeline
  - textbox / checkbox detection iyileştirmeleri
  - ilk generated fillable PDF

### 2026-03-17 01:20:14

- Klasör: `20260317_012014_formai_multiline_split_v2_checkpoint`
- Tema: multiline segmentation
- Öne çıkanlar:
  - `lead + body` widget segmentation
  - continuation alan düzeltmesi

### 2026-03-17 17:03:26

- Klasör: `20260317_170326_formai_real_pipeline_demo_checkpoint`
- Tema: gerçek pipeline demo baseline
- Öne çıkanlar:
  - gerçek template + gerçek filled image ile end-to-end demo
  - Ollama + GLM-OCR yolu

### 2026-03-17 18:53:21

- Klasör: `20260317_185321_formai_readable_fit_checkpoint`
- Tema: readable fit ve benchmark kalite artışı

### 2026-03-17 20:16:44

- Klasör: `20260317_201644_formai_multiline_v17_checkpoint`
- Tema: multiline readability ve phone-tail cleanup

### 2026-03-17 21:53:10

- Klasör: `20260317_215310_formai_same_page_note_v22_checkpoint`
- Tema: same-page overflow note davranışı

### 2026-03-17 23:25:12

- Klasör: `20260317_232512_formai_natural_form_polish_v23_checkpoint`
- Tema: doğal görünümlü tek sayfa output polish

### 2026-03-18 19:21:07

- Klasör: `20260318_192107_formai_pre_api_release_ready_checkpoint`
- Tema: API öncesi validation-first sertleştirme

## API ve web evrimi

### 2026-03-23 23:02:30

- Klasör: `20260323_230230_formai_api_workbench_checkpoint`
- Tema: job tabanlı API + internal workbench

### 2026-03-24 00:28:26

- Klasör: `20260324_002826_formai_onepage_octolabs_footer_checkpoint`
- Tema: one-page marketing site + refined footer + atomic job metadata writes

### 2026-03-24 18:26:53

- Klasör: `20260324_182653_formai_ui_polish_checkpoint`
- Tema: marketing/workbench UI polish

## Bugünkü yorum

Checkpoint zinciri şunu gösteriyor:
- proje önce form pipeline problemi olarak başladı
- sonra extraction/readability ve benchmark odaklı güçlendi
- ardından API ve web yüzeyi eklendi
- bugün artık tek script değil, ürün adayı bir sistem haline geldi

Detaylı teknik bağlam için:
- [docs/quality/current-state.md](../docs/quality/current-state.md)
- [docs/web/overview.md](../docs/web/overview.md)
- [docs/operations/release-and-archive.md](../docs/operations/release-and-archive.md)
