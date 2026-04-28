# Release, Sürümleme ve Arşiv Politikası

## Ana karar

FormAI için artık tek bir monorepo sürüm hattı kullanılır.

### Hedef baseline

- `FormAI 0.2.0`

Bu sürüm şu yüzeylerde hizalı olmalıdır:
- Python package
- API surface
- Web package

## Neden tek sürüm?

Bu hizalamadan önce repo'da farklı yüzeylerin farklı numara taşıması kafa karıştırıcıydı:
- Python package `0.1.0`
- API `0.2.0`
- Web `0.1.0`

Ürün perspektifinde bunlar ayrı ürünler değil; aynı sistemin bileşenleridir.

Bu yüzden tercih edilen model:
- tek ana sürüm
- bileşen durumu dokümanda ayrıca belirtilir

## Release manifest mantığı

Her release için en az şu bilgiler tutulmalı:
- ürün sürümü
- commit
- test baseline
- web build durumu
- aktif benchmark snapshot'ı
- önemli bilinen riskler
- artefact pointer'ları

Bu bilgi repoda hafif metin olarak tutulmalı; büyük binary dosya olarak değil.

Bu repo için ilk hizalı örnek:
- [0.2.0 release manifest](../releases/0.2.0/manifest.md)

## Checkpoint politikası

`checkpoints/` klasörü tarihsel hafıza için değerlidir, ama ağır artefact deposuna dönüşmemelidir.

Yeni politika:
- repoda `MANIFEST.md` kalır
- küçük pointer dosyası olarak `artifacts.json` kalır
- büyük `project_snapshot.tar.gz`, preview image ve ağır benchmark output'ları dış arşiv veya lokal artefact deposuna taşınır

Bu geçişi kolaylaştırmak için yardımcı script:
- `scripts/dev/archive_local_artifacts.py`

Bugün repo hâlâ geçmişten gelen ağır checkpoint içeriği barındırıyor. Bu politika ileriye dönük normalleştirme hedefidir.
Bu repo'da ilk normalizasyon turu sonrası checkpoint klasörleri manifest-first hale getirilmiş, ağır payload'lar `tmp/archive/<timestamp>/checkpoints/` altına taşınmıştır.

Kullanılan yardımcı script:
- `scripts/dev/archive_local_artifacts.py`

## Generated artefact sınıfları

Dokümanda şu ayrım korunmalıdır:

### Source of truth

Repo içindeki version-controlled kod ve manifestler.

### Generated artifact

Pipeline veya build sonucu üretilen dosyalar:
- fillable PDF
- final PDF
- preview image
- benchmark summary

### Benchmark evidence

Karar destekleyen, ama source of truth olmayan kalite çıktıları.

### Local scratch output

`tmp/` altındaki geçici çalışma ürünleri.

## Bugünkü repo yükü

Normalizasyon sonrası yerel snapshot'ta görülen tablo:
- `checkpoints/`: yaklaşık `108K`
- `tmp/archive/`: yaklaşık `226M`
- `web/`: yaklaşık `335M`

Yorum:
- checkpoint'ler artık hafif manifest-first kayıtlar halinde
- ağır checkpoint payload'ları local archive alanına taşınmış durumda
- `web/` boyutunun önemli kısmı `node_modules` kaynaklıdır

## Repo temizliği için pratik kural

### Repoda kalmalı

- `src/`
- `tests/`
- `scripts/`
- `docs/`
- küçük manifest tabanlı checkpoint kayıtları

### Repoda kalmamalı

- geçici build çıktıları
- büyük preview setleri
- eski `.next` restart/broken klasörleri
- büyük local benchmark dump'ları
- ağır tar arşivleri

Pratikte:
- stale `.next.broken.*` ve `.next.cleanrestart.*` klasörleri archive veya cleanup hedefidir
- aktif `.next` de istenirse aynı script ile arşivlenebilir
- checkpoint payload'ları repoda tutulmamalı, pointer ile dış arşive taşınmalıdır

Pratik cleanup örneği:

```bash
PYTHONPATH=src ./.venv311/bin/python scripts/dev/archive_local_artifacts.py
```

## Runtime matrisi

### Core

- Python `>= 3.10`
- doğrulanan ana local yol: Python `3.11`

### Core dependency highlights

- `pypdf >= 5.3.0`
- `PyMuPDF >= 1.24.0`
- `Pillow >= 10.0.0`
- opsiyonel `openai >= 1.30.0`

### Web

- Next.js `15.5.14`
- React `19.1.1`
- TypeScript `5.9.3`

## Release dili

FormAI için release notu yazarken şu hata yapılmamalı:
- "testler geçiyor" ile "ürün hazır" eşitlenmemeli

Doğru dil:
- hangi belge ailelerinde güven yüksek
- hangilerinde review gerekli
- hangi gerçek case'ler hâlâ blocker

Özellikle Turkish petition hattı, bu dürüstlük gereğinin ana örneğidir.
