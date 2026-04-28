# FormAI — Agent Implementation Guide

> **Hedef kitle:** Bu projeyi hiç görmemiş, sıfırdan başlayan bir agent.
> Bu belge; repo yapısını anlamaktan, her dosyayı tam olarak nasıl değiştireceğine kadar
> her adımı satır satır açıklar. Buradaki kodu aynen kopyalayarak uygula.

---

## 0. Repo Yapısı — Önce Bunu Anla

```
yeniP/
├── src/formai/                  ← Python ürün kodu (pip install -e ile kurulur)
│   ├── agents/                  ← 4 ana agent (pipeline'ın kalbi)
│   │   ├── input_evaluator.py
│   │   ├── acroform_generator.py
│   │   ├── data_extractor.py
│   │   └── final_assembler.py   ← ⚠️ DEĞIŞTIRILECEK
│   ├── benchmarks/              ← Kalite ölçüm sistemi
│   │   ├── base.py              ← DatasetAdapter ABC
│   │   ├── models.py            ← ⚠️ DEĞIŞTIRILECEK (BenchmarkAggregateMetrics)
│   │   ├── scoring.py           ← ⚠️ DEĞIŞTIRILECEK (compute_tcs eklenecek)
│   │   ├── runner.py            ← ⚠️ DEĞIŞTIRILECEK (TCS gates + OCRTurk adapter)
│   │   ├── fir.py
│   │   ├── funsd_plus.py
│   │   ├── turkish_petitions.py ← ÖRNEK ADAPTER (ocrturk.py için model al)
│   │   ├── turkish_printed.py
│   │   └── turkish_handwritten.py
│   ├── llm/                     ← Vision LLM istemcileri
│   │   ├── base.py              ← VisionLLMClient ABC
│   │   ├── glm_ocr.py           ← Mevcut GLM-OCR (Ollama/HF üzerinden)
│   │   ├── ollama_vision.py
│   │   └── openai_vision.py
│   ├── ocr/                     ← OCR okuyucular (duck-typed, ABC yok)
│   │   └── tesseract.py         ← ÖRNEK READER (paddleocr.py için model al)
│   ├── verification/
│   │   └── engine.py            ← ⚠️ DEĞIŞTIRILECEK (ocr_reader param)
│   ├── config.py                ← ⚠️ DEĞIŞTIRILECEK (8 yeni alan)
│   ├── pipeline.py              ← ⚠️ DEĞIŞTIRILECEK (2 yerde)
│   ├── self_check.py            ← Sadece re-export: run_verification_check
│   └── errors.py                ← IntegrationUnavailable buradan import edilir
├── tests/                       ← unittest tabanlı testler
├── pyproject.toml               ← ⚠️ DEĞIŞTIRILECEK (2 yeni optional-dep group)
└── docs/
```

### Pipeline Akışı (Kısaca)

```
template.pdf + filled.pdf
        │
        ▼
InputEvaluatorAgent.evaluate()      → form alanlarını tespit eder
        │
        ▼
AcroFormGeneratorAgent.generate()   → interaktif AcroForm PDF üretir
        │
        ▼
DataExtractorAgent.extract()        → filled.pdf'ten değerleri okur (LLM + OCR)
        │
        ▼
FinalAssemblerAgent.assemble()      → final.pdf üretir + self-check yapar
```

### OCR Arayüzü (Duck-typed)

`is_available() -> bool` ve `extract_text(page: RenderedPage, psm: int) -> str` metodları
olan her nesne OCR reader olarak kullanılabilir. Abstract base class yok.

### VisionLLMClient Arayüzü

`src/formai/llm/base.py`'deki `VisionLLMClient` ABC'den türetilir. Zorunlu metodlar:
- `detect_template_fields(pages) -> Sequence[DetectedField]`
- `extract_structured_data(pages, expected_keys) -> Dict[str, FieldValue]`

---

## Temel Kural: GitHub Push Yasağı

> ⚠️ Herhangi bir commit'i GitHub'a push etmeden önce kullanıcıdan **açık yazılı izin** al.
> Türkçe form fill kalitesi kabul edilebilir düzeye gelmeden push yapma:
> - `self_check_passed = true`
> - `evidence_score ≥ 0.58`
> - `TCS ≥ 0.78` (turkish_petitions smoke benchmark'ta)

---

## Commit 1 — P0-C: Config Default Doğrulama

### Ne Yapılıyor?

`ollama_model` default değerinin Ollama registry'deki gerçek GLM-OCR slug'ıyla uyumlu
olduğunu doğrula. Eğer `"glm-ocr"` değil farklı bir slug varsa güncelle.

### Kontrol Komutu

```bash
curl -s http://localhost:11434/api/tags | python3 -c "
import json, sys
data = json.load(sys.stdin)
for m in data.get('models', []):
    if 'glm' in m['name'].lower():
        print(m['name'])
"
```

Eğer Ollama çalışmıyorsa https://ollama.com/library/glm-ocr adresini kontrol et.
Model ismi `glm-ocr` olarak doğrulandı — **değişiklik gerekmiyor.**

`openai_model = "gpt-4.1-mini"` — GPT-4.1 mini gerçek bir model, değiştirme.

**Bu commit için kod değişikliği yok.** Sadece doğrulama yap, gerek olmadığına kanaat getir.

---

## Commit 2 — P0-A1: `src/formai/ocr/paddleocr.py` (Yeni Dosya)

### Ne Yapılıyor?

Tesseract'ın yetersiz kaldığı Türkçe karakterler (`ğ, ı, ş, ç, ö, ü`) için PaddleOCR
okuyucu oluştur. Duck-typed: `TesseractOCRReader` ile aynı arayüz.

### Referans: Mevcut `src/formai/ocr/tesseract.py` (model al)

```python
# tesseract.py'nin yapısı — PaddleOCR buna benzer olmalı:
class TesseractOCRReader:
    def __init__(self, binary_path: str = "tesseract", lang: str = "eng")
    def is_available(self) -> bool          # try: subprocess.run; except: False
    def extract_text(self, page: RenderedPage, psm: int = 6) -> str
```

### Yeni Dosya: `src/formai/ocr/paddleocr.py`

```python
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from formai.errors import IntegrationUnavailable
from formai.models import RenderedPage

_LANG_MAP = {
    "eng": "en",
    "tur": "tr",
    "tr": "tr",
    "en": "en",
}


class PaddleOCRReader:
    """Duck-typed OCR reader backed by PaddleOCR.

    Interface-compatible with TesseractOCRReader:
      - is_available() -> bool
      - extract_text(page: RenderedPage, psm: int) -> str
    """

    def __init__(
        self,
        lang: str = "tr",
        use_angle_cls: bool = True,
        use_gpu: bool = False,
    ) -> None:
        self._lang = _LANG_MAP.get(lang, lang)
        self._use_angle_cls = use_angle_cls
        self._use_gpu = use_gpu
        self._engine: Any = None

    def is_available(self) -> bool:
        """Return True if paddleocr package is importable. Never raises."""
        try:
            import paddleocr  # noqa: F401
            return True
        except ImportError:
            return False

    def extract_text(self, page: RenderedPage, psm: int = 6) -> str:  # noqa: ARG002
        """Extract text from a RenderedPage using PaddleOCR.

        ``psm`` is accepted for interface compatibility but ignored —
        PaddleOCR has no equivalent mode selector.
        """
        if not self.is_available():
            raise IntegrationUnavailable(
                "paddleocr is not installed. "
                "Run: pip install 'formai[paddleocr]'"
            )
        self._ensure_loaded()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(page.image_bytes)
            tmp_path = tmp.name
        try:
            result = self._engine.ocr(tmp_path, cls=self._use_angle_cls)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        return self._join_result(result)

    def _ensure_loaded(self) -> None:
        """Lazy-initialize PaddleOCR engine (expensive, cache after first call)."""
        if self._engine is not None:
            return
        from paddleocr import PaddleOCR
        self._engine = PaddleOCR(
            use_angle_cls=self._use_angle_cls,
            lang=self._lang,
            use_gpu=self._use_gpu,
            show_log=False,
        )

    @staticmethod
    def _join_result(result: Any) -> str:
        """Flatten PaddleOCR result list into a single string."""
        if not result:
            return ""
        lines = []
        # result is list[list[tuple[box, (text, confidence)]]]
        for page_result in result:
            if not page_result:
                continue
            for line in page_result:
                if isinstance(line, (list, tuple)) and len(line) >= 2:
                    text_conf = line[1]
                    if isinstance(text_conf, (list, tuple)) and len(text_conf) >= 1:
                        lines.append(str(text_conf[0]))
        return " ".join(lines)
```

### Doğrulama

```bash
cd /Users/emirhanfirtina/Desktop/yeniP
# paddleocr kurulu değilse is_available() False döner, exception fırlatmaz
PYTHONPATH=src .venv311/bin/python -c "
from formai.ocr.paddleocr import PaddleOCRReader
r = PaddleOCRReader()
print('is_available:', r.is_available())
print('Import OK')
"
```

---

## Commit 3 — P0-A2,3: Config + Pipeline PaddleOCR Desteği

### Dosya 1: `src/formai/config.py`

**Nereye eklenecek:** `tesseract_lang: str = "eng"` satırından (line 23) hemen sonra.

**ÖNCE (line 22-23):**
```python
    tesseract_path: str = "tesseract"
    tesseract_lang: str = "eng"
```

**SONRA:**
```python
    tesseract_path: str = "tesseract"
    tesseract_lang: str = "eng"
    paddleocr_lang: str = "tr"
    paddleocr_use_angle_cls: bool = True
    paddleocr_use_gpu: bool = False
```

**`from_env()` metoduna da ekle.** `tesseract_lang=...` satırından (line ~64) sonra:

**ÖNCE (line 63-64):**
```python
            tesseract_path=os.getenv("FORMAI_TESSERACT_PATH", "tesseract"),
            tesseract_lang=os.getenv("FORMAI_TESSERACT_LANG", "eng"),
```

**SONRA:**
```python
            tesseract_path=os.getenv("FORMAI_TESSERACT_PATH", "tesseract"),
            tesseract_lang=os.getenv("FORMAI_TESSERACT_LANG", "eng"),
            paddleocr_lang=os.getenv("FORMAI_PADDLEOCR_LANG", "tr"),
            paddleocr_use_angle_cls=os.getenv(
                "FORMAI_PADDLEOCR_USE_ANGLE_CLS", "true"
            ).lower() in {"1", "true", "yes"},
            paddleocr_use_gpu=os.getenv(
                "FORMAI_PADDLEOCR_USE_GPU", "false"
            ).lower() in {"1", "true", "yes"},
```

---

### Dosya 2: `src/formai/pipeline.py`

**`build_crop_ocr_reader()` fonksiyonunu güncelle (line 127-141).**

**ÖNCE:**
```python
def build_crop_ocr_reader(config: FormAIConfig):
    provider = (config.crop_ocr_provider or "auto").strip().lower()
    if provider in {"", "none", "off", "disabled"}:
        return None
    if provider in {"auto", "tesseract"}:
        reader = TesseractOCRReader(
            binary_path=config.tesseract_path,
            lang=config.tesseract_lang,
        )
        if provider == "tesseract":
            return reader
        return reader if reader.is_available() else None
    raise IntegrationUnavailable(
        f"Unsupported crop OCR provider: {provider}. Supported providers: auto, tesseract, none."
    )
```

**SONRA:**
```python
def build_crop_ocr_reader(config: FormAIConfig):
    provider = (config.crop_ocr_provider or "auto").strip().lower()
    if provider in {"", "none", "off", "disabled"}:
        return None
    if provider == "paddleocr":
        from formai.ocr.paddleocr import PaddleOCRReader
        return PaddleOCRReader(
            lang=config.paddleocr_lang,
            use_angle_cls=config.paddleocr_use_angle_cls,
            use_gpu=config.paddleocr_use_gpu,
        )
    if provider in {"auto", "tesseract"}:
        reader = TesseractOCRReader(
            binary_path=config.tesseract_path,
            lang=config.tesseract_lang,
        )
        if provider == "tesseract":
            return reader
        if reader.is_available():
            return reader
        # auto fallback: tesseract yok → paddleocr dene
        from formai.ocr.paddleocr import PaddleOCRReader
        paddle_reader = PaddleOCRReader(
            lang=config.paddleocr_lang,
            use_angle_cls=config.paddleocr_use_angle_cls,
            use_gpu=config.paddleocr_use_gpu,
        )
        return paddle_reader if paddle_reader.is_available() else None
    raise IntegrationUnavailable(
        f"Unsupported crop OCR provider: {provider}. "
        "Supported providers: auto, tesseract, paddleocr, none."
    )
```

---

## Commit 4 — P0-A4,5: Verification Engine + Final Assembler Wire-Through

### Dosya 1: `src/formai/verification/engine.py`

**Problem:** `run_verification_check()` her zaman `TesseractOCRReader` oluşturuyor.
Biz PaddleOCR veya başka bir reader geçirebilmek istiyoruz.

**`run_verification_check()` fonksiyon imzasına yeni parametre ekle (line 21-34).**

**ÖNCE (imza ve ilk satırlar):**
```python
def run_verification_check(
    *,
    source_reference: Path,
    output_pdf_path: Path,
    template_fields: Iterable[AcroField],
    filled_values: Dict[str, str],
    tesseract_path: str = "tesseract",
    default_lang: str = "eng",
    min_source_similarity: float = 0.42,
    min_output_similarity: float = 0.58,
    raster_dpi: int = 180,
    profile_name: str | None = None,
    llm_client: VisionLLMClient | None = None,
) -> SelfCheckResult | None:
```

**SONRA (yeni `ocr_reader` parametresi sona eklendi):**
```python
def run_verification_check(
    *,
    source_reference: Path,
    output_pdf_path: Path,
    template_fields: Iterable[AcroField],
    filled_values: Dict[str, str],
    tesseract_path: str = "tesseract",
    default_lang: str = "eng",
    min_source_similarity: float = 0.42,
    min_output_similarity: float = 0.58,
    raster_dpi: int = 180,
    profile_name: str | None = None,
    llm_client: VisionLLMClient | None = None,
    ocr_reader: object | None = None,
) -> SelfCheckResult | None:
```

**`reader = TesseractOCRReader(...)` bloğunu değiştir (line 58-61).**

**ÖNCE:**
```python
    reader = TesseractOCRReader(
        binary_path=tesseract_path,
        lang=verification_profile.ocr_lang,
    )
    if reader.is_available():
```

**SONRA:**
```python
    if ocr_reader is None:
        ocr_reader = TesseractOCRReader(
            binary_path=tesseract_path,
            lang=verification_profile.ocr_lang,
        )
    reader = ocr_reader
    if reader.is_available():
```

**`_safe_extract_text` tip anotasyonunu güncelle (line 253).**

**ÖNCE:**
```python
def _safe_extract_text(reader: TesseractOCRReader, page: RenderedPage, *, psm: int) -> str:
```

**SONRA:**
```python
def _safe_extract_text(reader: object, page: RenderedPage, *, psm: int) -> str:
```

---

### Dosya 2: `src/formai/agents/final_assembler.py`

**`FinalAssemblerAgent.__init__()` imzasına `ocr_reader` ekle (line 23-25).**

**ÖNCE:**
```python
class FinalAssemblerAgent(BaseAgent):
    def __init__(self, config, llm_client: VisionLLMClient | None = None):
        super().__init__(config)
        self.llm_client = llm_client
```

**SONRA:**
```python
class FinalAssemblerAgent(BaseAgent):
    def __init__(self, config, llm_client: VisionLLMClient | None = None,
                 ocr_reader: object | None = None):
        super().__init__(config)
        self.llm_client = llm_client
        self.ocr_reader = ocr_reader
```

**`assemble()` içindeki `run_field_level_self_check(...)` çağrısına `ocr_reader=self.ocr_reader` ekle (line 181-192).**

**ÖNCE:**
```python
            self_check = run_field_level_self_check(
                source_reference=source_reference,
                output_pdf_path=output_path,
                template_fields=template_fields,
                filled_values=filled_values,
                tesseract_path=self.config.tesseract_path,
                default_lang=self.config.tesseract_lang,
                min_source_similarity=self.config.self_check_min_source_similarity,
                min_output_similarity=self.config.self_check_min_output_similarity,
                raster_dpi=self.config.raster_dpi,
                llm_client=self.llm_client,
            )
```

**SONRA:**
```python
            self_check = run_field_level_self_check(
                source_reference=source_reference,
                output_pdf_path=output_path,
                template_fields=template_fields,
                filled_values=filled_values,
                tesseract_path=self.config.tesseract_path,
                default_lang=self.config.tesseract_lang,
                min_source_similarity=self.config.self_check_min_source_similarity,
                min_output_similarity=self.config.self_check_min_output_similarity,
                raster_dpi=self.config.raster_dpi,
                llm_client=self.llm_client,
                ocr_reader=self.ocr_reader,
            )
```

---

## Commit 5 — P0-A5 (devam): Pipeline'da Assembler'a ocr_reader Geçir

### Dosya: `src/formai/pipeline.py`

**`build_default_pipeline()` içindeki assembler satırını güncelle (line 88).**

**ÖNCE:**
```python
        assembler=FinalAssemblerAgent(config, llm_client=llm_client),
```

**SONRA:**
```python
        assembler=FinalAssemblerAgent(config, llm_client=llm_client, ocr_reader=ocr_reader),
```

> **Not:** `ocr_reader` zaten line 75'te `build_crop_ocr_reader(config)` ile oluşturuluyor.
> Sadece bu satırı ekliyorsun.

---

## Commit 6 — P0-A6: pyproject.toml + Test Dosyası

### Dosya 1: `pyproject.toml`

**`dev = [...]` bloğundan (line 40-42) sonrasına ekle:**

**ÖNCE (son satırlar):**
```toml
dev = [
  "pytest>=8.0.0"
]
```

**SONRA:**
```toml
dev = [
  "pytest>=8.0.0"
]
paddleocr = [
  "paddleocr>=2.8.0",
  "paddlepaddle>=2.6.0"
]
```

> GPU kullanıcıları için not: `paddlepaddle` yerine `paddlepaddle-gpu` manuel kurulur +
> `FORMAI_PADDLEOCR_USE_GPU=true` set edilir. pyproject.toml'a GPU variant eklenmez.

---

### Dosya 2: `tests/test_ocr_paddleocr.py` (Yeni Dosya)

```python
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from formai.models import RenderedPage


def _make_page(content: bytes = b"fake-png-data") -> RenderedPage:
    return RenderedPage(
        page_number=1,
        mime_type="image/png",
        image_bytes=content,
        width=100,
        height=50,
    )


class TestPaddleOCRReaderAvailability(unittest.TestCase):
    def test_is_available_true_when_paddleocr_importable(self):
        with patch.dict("sys.modules", {"paddleocr": MagicMock()}):
            from importlib import reload
            import formai.ocr.paddleocr as mod
            reload(mod)
            reader = mod.PaddleOCRReader()
            self.assertTrue(reader.is_available())

    def test_is_available_false_when_paddleocr_missing(self):
        with patch.dict("sys.modules", {"paddleocr": None}):
            from importlib import reload
            import formai.ocr.paddleocr as mod
            reload(mod)
            reader = mod.PaddleOCRReader()
            self.assertFalse(reader.is_available())

    def test_is_available_never_raises(self):
        """is_available() must never propagate exceptions."""
        from formai.ocr.paddleocr import PaddleOCRReader
        reader = PaddleOCRReader()
        try:
            result = reader.is_available()
            self.assertIsInstance(result, bool)
        except Exception as exc:
            self.fail(f"is_available() raised {exc}")


class TestPaddleOCRReaderExtract(unittest.TestCase):
    def test_extract_text_joins_lines(self):
        fake_result = [
            [
                ([0, 0, 10, 10], ("Merhaba", 0.99)),
                ([0, 10, 10, 20], ("Dünya", 0.97)),
            ]
        ]
        mock_engine = MagicMock()
        mock_engine.ocr.return_value = fake_result

        fake_paddle_module = MagicMock()
        fake_paddle_module.PaddleOCR.return_value = mock_engine

        with patch.dict("sys.modules", {"paddleocr": fake_paddle_module}):
            from importlib import reload
            import formai.ocr.paddleocr as mod
            reload(mod)
            reader = mod.PaddleOCRReader(lang="tr")
            # Inject engine directly to skip _ensure_loaded
            reader._engine = mock_engine
            text = reader.extract_text(_make_page())
        self.assertIn("Merhaba", text)
        self.assertIn("Dünya", text)

    def test_extract_text_raises_integration_unavailable_when_missing(self):
        with patch.dict("sys.modules", {"paddleocr": None}):
            from importlib import reload
            import formai.ocr.paddleocr as mod
            reload(mod)
            from formai.errors import IntegrationUnavailable
            reader = mod.PaddleOCRReader()
            with self.assertRaises(IntegrationUnavailable):
                reader.extract_text(_make_page())

    def test_psm_param_accepted_silently(self):
        """psm parameter must be accepted but ignored (interface compat)."""
        fake_result = [[([0, 0, 5, 5], ("ok", 0.9))]]
        mock_engine = MagicMock()
        mock_engine.ocr.return_value = fake_result
        fake_paddle_module = MagicMock()
        fake_paddle_module.PaddleOCR.return_value = mock_engine

        with patch.dict("sys.modules", {"paddleocr": fake_paddle_module}):
            from importlib import reload
            import formai.ocr.paddleocr as mod
            reload(mod)
            reader = mod.PaddleOCRReader()
            reader._engine = mock_engine
            # psm=7 geçilse de exception fırlatmamalı
            text = reader.extract_text(_make_page(), psm=7)
        self.assertIsInstance(text, str)


class TestBuildCropOCRReaderPaddleOCR(unittest.TestCase):
    def test_build_paddleocr_provider(self):
        from formai.config import FormAIConfig
        from pathlib import Path
        config = FormAIConfig.from_env(Path("/tmp"))
        config.crop_ocr_provider = "paddleocr"

        fake_paddle_module = MagicMock()
        fake_paddle_module.PaddleOCR.return_value = MagicMock()
        with patch.dict("sys.modules", {"paddleocr": fake_paddle_module}):
            from formai.pipeline import build_crop_ocr_reader
            reader = build_crop_ocr_reader(config)
        from formai.ocr.paddleocr import PaddleOCRReader
        self.assertIsInstance(reader, PaddleOCRReader)


if __name__ == "__main__":
    unittest.main()
```

### Test Çalıştırma

```bash
cd /Users/emirhanfirtina/Desktop/yeniP
env PYTHONPATH=src .venv311/bin/python -m pytest tests/test_ocr_paddleocr.py -v
```

---

## Commit 7 — P0-B1: `src/formai/llm/glm_ocr_sdk.py` (Yeni Dosya)

### Ne Yapılıyor?

`detect_template_fields()` metodu mevcut `OllamaVisionClient` ve `GLMOCRVisionClient`'te
`IntegrationUnavailable` fırlatıyor. Yeni `GLMOCRSDKClient`, GLM-OCR SDK'nın
PP-DocLayout-V3 layout detection özelliğini kullanarak bu metodu gerçekten implement eder.

### Referanslar (import edilecek fonksiyonlar)

`src/formai/llm/glm_ocr.py` içindeki bu iki fonksiyon yeniden kullanılacak:
- `_extract_json_payload(text: str) -> dict`
- `_normalize_extraction_payload(payload: dict) -> Dict[str, dict]`

### Yeni Dosya: `src/formai/llm/glm_ocr_sdk.py`

```python
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Sequence

from formai.errors import IntegrationUnavailable
from formai.llm.base import VisionLLMClient
from formai.models import (
    BoundingBox,
    DetectedField,
    FieldKind,
    FieldValue,
    RenderedPage,
)

# Layout category → FieldKind mapping (PP-DocLayout-V3 label set)
_LAYOUT_LABEL_TO_KIND: Dict[str, FieldKind] = {
    "text_field": FieldKind.TEXT,
    "form_field": FieldKind.TEXT,
    "checkbox": FieldKind.CHECKBOX,
    "radio": FieldKind.RADIO,
    "table_cell": FieldKind.TEXT,
    "title": FieldKind.TEXT,
    "text": FieldKind.TEXT,
    "figure": FieldKind.TEXT,
    "table": FieldKind.TEXT,
}


class GLMOCRSDKClient(VisionLLMClient):
    """VisionLLMClient backed by the GLM-OCR Python SDK (local inference).

    Uses PP-DocLayout-V3 for ``detect_template_fields`` and GLM-OCR's
    JSON schema extraction for ``extract_structured_data``.

    Install: ``pip install 'formai[glm_ocr_sdk]'``
    Use: ``FORMAI_VISION_PROVIDER=glm_ocr_sdk``
    """

    def __init__(
        self,
        model: str = "zai-org/GLM-OCR",
        device_map: str = "auto",
        max_new_tokens: int = 1024,
        layout_confidence_threshold: float = 0.50,
    ) -> None:
        self._model = model
        self._device_map = device_map
        self._max_new_tokens = max_new_tokens
        self._layout_threshold = layout_confidence_threshold
        self._pipeline: Any = None

    # ------------------------------------------------------------------
    # VisionLLMClient interface
    # ------------------------------------------------------------------

    def detect_template_fields(self, pages: Sequence[RenderedPage]) -> Sequence[DetectedField]:
        """Detect form fields using PP-DocLayout-V3 layout detection."""
        self._ensure_pipeline_loaded()
        detected: List[DetectedField] = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_paths = self._pages_to_temp_images(pages, Path(tmp_dir))
            for page, image_path in zip(pages, tmp_paths):
                try:
                    layout_result = self._pipeline.detect_layout(str(image_path))
                except Exception:
                    continue
                detected.extend(
                    self._layout_result_to_detected_fields(layout_result, page)
                )
        return detected

    def extract_structured_data(
        self,
        pages: Sequence[RenderedPage],
        expected_keys: Sequence[str],
    ) -> Dict[str, FieldValue]:
        """Extract key-value pairs using GLM-OCR JSON schema extraction."""
        from formai.llm.glm_ocr import _extract_json_payload, _normalize_extraction_payload

        self._ensure_pipeline_loaded()
        schema = {key: "" for key in expected_keys}
        combined_payload: dict = {}
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_paths = self._pages_to_temp_images(pages, Path(tmp_dir))
            for image_path in tmp_paths:
                try:
                    raw = self._pipeline.extract(str(image_path), schema=schema)
                    payload = _extract_json_payload(raw if isinstance(raw, str) else str(raw))
                    combined_payload.update(payload)
                except Exception:
                    continue
        return {
            key: fv
            for key, fv in _normalize_extraction_payload(combined_payload).items()
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_pipeline_loaded(self) -> None:
        """Lazy-initialize GLMOCRPipeline (heavy load, cache after first call)."""
        if self._pipeline is not None:
            return
        try:
            from glm_ocr import GLMOCRPipeline
        except ImportError as exc:
            raise IntegrationUnavailable(
                "glm_ocr SDK is not installed. "
                "Run: pip install 'formai[glm_ocr_sdk]'"
            ) from exc
        self._pipeline = GLMOCRPipeline(
            model=self._model,
            device_map=self._device_map,
            max_new_tokens=self._max_new_tokens,
        )

    def _pages_to_temp_images(
        self, pages: Sequence[RenderedPage], tmp_dir: Path
    ) -> List[Path]:
        paths: List[Path] = []
        for i, page in enumerate(pages):
            ext = ".png" if "png" in page.mime_type else ".jpg"
            p = tmp_dir / f"page_{i:03d}{ext}"
            p.write_bytes(page.image_bytes)
            paths.append(p)
        return paths

    def _layout_result_to_detected_fields(
        self, layout_result: Any, page: RenderedPage
    ) -> List[DetectedField]:
        """Convert PP-DocLayout-V3 layout bboxes to DetectedField objects."""
        fields: List[DetectedField] = []
        if not layout_result:
            return fields
        # layout_result is expected to be a list of dicts:
        # [{"label": "text_field", "bbox": [x1, y1, x2, y2], "confidence": 0.92}, ...]
        items = layout_result if isinstance(layout_result, list) else [layout_result]
        for item in items:
            if not isinstance(item, dict):
                continue
            confidence = float(item.get("confidence", 0.0))
            if confidence < self._layout_threshold:
                continue
            bbox = item.get("bbox") or item.get("box")
            if not bbox or len(bbox) < 4:
                continue
            try:
                x1, y1, x2, y2 = (float(v) for v in bbox[:4])
            except (TypeError, ValueError):
                continue
            label = str(item.get("label", "text")).lower()
            kind = _LAYOUT_LABEL_TO_KIND.get(label, FieldKind.TEXT)
            fields.append(
                DetectedField(
                    box=BoundingBox(
                        page_number=page.page_number,
                        left=x1,
                        top=y1,
                        right=x2,
                        bottom=y2,
                        reference_width=float(page.width),
                        reference_height=float(page.height),
                    ),
                    field_kind=kind,
                    confidence=confidence,
                )
            )
        return fields
```

---

## Commit 8 — P0-B2: Config + Pipeline + pyproject GLM-OCR SDK + Test

### Dosya 1: `src/formai/config.py`

**`glm_ocr_max_new_tokens: int = 1024` satırından (line 16) sonra ekle:**

**ÖNCE (line 14-16):**
```python
    glm_ocr_model: str = "zai-org/GLM-OCR"
    glm_ocr_device_map: str = "auto"
    glm_ocr_max_new_tokens: int = 1024
```

**SONRA:**
```python
    glm_ocr_model: str = "zai-org/GLM-OCR"
    glm_ocr_device_map: str = "auto"
    glm_ocr_max_new_tokens: int = 1024
    glm_ocr_sdk_model: str = "zai-org/GLM-OCR"
    glm_ocr_sdk_device_map: str = "auto"
    glm_ocr_sdk_max_new_tokens: int = 1024
    glm_ocr_sdk_layout_threshold: float = 0.50
```

**`from_env()` metoduna ekle** — `glm_ocr_max_new_tokens=...` satırından (line ~57) sonra:

**ÖNCE (line 55-57):**
```python
            glm_ocr_model=os.getenv("FORMAI_GLM_OCR_MODEL", "zai-org/GLM-OCR"),
            glm_ocr_device_map=os.getenv("FORMAI_GLM_OCR_DEVICE_MAP", "auto"),
            glm_ocr_max_new_tokens=int(os.getenv("FORMAI_GLM_OCR_MAX_NEW_TOKENS", "1024")),
```

**SONRA:**
```python
            glm_ocr_model=os.getenv("FORMAI_GLM_OCR_MODEL", "zai-org/GLM-OCR"),
            glm_ocr_device_map=os.getenv("FORMAI_GLM_OCR_DEVICE_MAP", "auto"),
            glm_ocr_max_new_tokens=int(os.getenv("FORMAI_GLM_OCR_MAX_NEW_TOKENS", "1024")),
            glm_ocr_sdk_model=os.getenv("FORMAI_GLM_OCR_SDK_MODEL", "zai-org/GLM-OCR"),
            glm_ocr_sdk_device_map=os.getenv("FORMAI_GLM_OCR_SDK_DEVICE_MAP", "auto"),
            glm_ocr_sdk_max_new_tokens=int(
                os.getenv("FORMAI_GLM_OCR_SDK_MAX_NEW_TOKENS", "1024")
            ),
            glm_ocr_sdk_layout_threshold=float(
                os.getenv("FORMAI_GLM_OCR_SDK_LAYOUT_THRESHOLD", "0.50")
            ),
```

---

### Dosya 2: `src/formai/pipeline.py`

**`build_vision_client()` içinde `if provider == "glm_ocr":` satırından (line 101) önce ekle:**

**ÖNCE (line 101-106):**
```python
    if provider == "glm_ocr":
        return GLMOCRVisionClient(
            model=config.glm_ocr_model,
            device_map=config.glm_ocr_device_map,
            max_new_tokens=config.glm_ocr_max_new_tokens,
        )
```

**SONRA:**
```python
    if provider == "glm_ocr_sdk":
        from formai.llm.glm_ocr_sdk import GLMOCRSDKClient
        return GLMOCRSDKClient(
            model=config.glm_ocr_sdk_model,
            device_map=config.glm_ocr_sdk_device_map,
            max_new_tokens=config.glm_ocr_sdk_max_new_tokens,
            layout_confidence_threshold=config.glm_ocr_sdk_layout_threshold,
        )
    if provider == "glm_ocr":
        return GLMOCRVisionClient(
            model=config.glm_ocr_model,
            device_map=config.glm_ocr_device_map,
            max_new_tokens=config.glm_ocr_max_new_tokens,
        )
```

**Hata mesajını da güncelle (line 122-124):**

**ÖNCE:**
```python
    raise IntegrationUnavailable(
        f"Unsupported vision provider: {provider}. Supported providers: auto, openai, glm_ocr, ollama."
    )
```

**SONRA:**
```python
    raise IntegrationUnavailable(
        f"Unsupported vision provider: {provider}. "
        "Supported providers: auto, openai, glm_ocr, glm_ocr_sdk, ollama."
    )
```

---

### Dosya 3: `pyproject.toml`

**`paddleocr = [...]` bloğundan sonra ekle:**

**ÖNCE:**
```toml
paddleocr = [
  "paddleocr>=2.8.0",
  "paddlepaddle>=2.6.0"
]
```

**SONRA:**
```toml
paddleocr = [
  "paddleocr>=2.8.0",
  "paddlepaddle>=2.6.0"
]
glm_ocr_sdk = [
  "glm-ocr>=0.1.0"
]
```

> **Not:** `glm-ocr` SDK kendi PyTorch/transformers bağımlılıklarını bundle ediyor.
> Mevcut `glm_ocr` group'undan ayrı tutulur.

---

### Dosya 4: `tests/test_llm_glm_ocr_sdk.py` (Yeni Dosya)

```python
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from formai.models import RenderedPage


def _make_page(width: int = 800, height: int = 1100) -> RenderedPage:
    return RenderedPage(
        page_number=1,
        mime_type="image/png",
        image_bytes=b"fake-png",
        width=width,
        height=height,
    )


class TestGLMOCRSDKClientDetect(unittest.TestCase):
    def test_detect_template_fields_converts_bbox(self):
        fake_layout = [
            {"label": "form_field", "bbox": [10.0, 20.0, 200.0, 40.0], "confidence": 0.95},
            {"label": "checkbox", "bbox": [10.0, 50.0, 30.0, 70.0], "confidence": 0.88},
        ]
        mock_pipeline = MagicMock()
        mock_pipeline.detect_layout.return_value = fake_layout

        fake_glm_ocr_mod = MagicMock()
        fake_glm_ocr_mod.GLMOCRPipeline.return_value = mock_pipeline

        with patch.dict("sys.modules", {"glm_ocr": fake_glm_ocr_mod}):
            from importlib import reload
            import formai.llm.glm_ocr_sdk as mod
            reload(mod)
            client = mod.GLMOCRSDKClient(layout_confidence_threshold=0.50)
            client._pipeline = mock_pipeline
            fields = client.detect_template_fields([_make_page()])

        self.assertEqual(len(fields), 2)
        from formai.models import FieldKind
        self.assertEqual(fields[1].field_kind, FieldKind.CHECKBOX)
        self.assertAlmostEqual(fields[0].box.left, 10.0)

    def test_detect_filters_low_confidence(self):
        fake_layout = [
            {"label": "text", "bbox": [0, 0, 100, 20], "confidence": 0.30},  # below threshold
        ]
        mock_pipeline = MagicMock()
        mock_pipeline.detect_layout.return_value = fake_layout

        with patch.dict("sys.modules", {"glm_ocr": MagicMock()}):
            from importlib import reload
            import formai.llm.glm_ocr_sdk as mod
            reload(mod)
            client = mod.GLMOCRSDKClient(layout_confidence_threshold=0.50)
            client._pipeline = mock_pipeline
            fields = client.detect_template_fields([_make_page()])

        self.assertEqual(len(fields), 0)

    def test_integration_unavailable_when_sdk_missing(self):
        with patch.dict("sys.modules", {"glm_ocr": None}):
            from importlib import reload
            import formai.llm.glm_ocr_sdk as mod
            reload(mod)
            from formai.errors import IntegrationUnavailable
            client = mod.GLMOCRSDKClient()
            with self.assertRaises(IntegrationUnavailable):
                client.detect_template_fields([_make_page()])


class TestBuildVisionClientSDK(unittest.TestCase):
    def test_build_glm_ocr_sdk_provider(self):
        from formai.config import FormAIConfig
        from pathlib import Path
        config = FormAIConfig.from_env(Path("/tmp"))
        config.vision_provider = "glm_ocr_sdk"

        fake_glm_ocr_mod = MagicMock()
        fake_glm_ocr_mod.GLMOCRPipeline.return_value = MagicMock()
        with patch.dict("sys.modules", {"glm_ocr": fake_glm_ocr_mod}):
            from formai.pipeline import build_vision_client
            client = build_vision_client(config)
        from formai.llm.glm_ocr_sdk import GLMOCRSDKClient
        self.assertIsInstance(client, GLMOCRSDKClient)


if __name__ == "__main__":
    unittest.main()
```

---

## Commit 9 — P1-A1: TCS Metriği — `scoring.py` + `models.py`

### Ne Yapılıyor?

OCRTurk paper (SIGTURK 2026, Eq. 2) tanımlı TCS = 1 - E/N metriğini implement et.
E = Türkçe özel karakterlerdeki hata sayısı, N = toplam Türkçe özel karakter sayısı.

---

### Dosya 1: `src/formai/benchmarks/scoring.py`

**Dosyanın en üstüne (line 1 import'lardan sonra, `CONFIDENCE_BUCKETS` tanımından önce) ekle:**

**ÖNCE (line 22):**
```python
CONFIDENCE_BUCKETS = (
```

**SONRA — tüm bu bloğu `CONFIDENCE_BUCKETS`'tan önce ekle:**
```python
TURKISH_SPECIAL_CHARS: frozenset[str] = frozenset("çğıöşüÇĞİÖŞÜ")


def compute_tcs(expected: str, predicted: str) -> float:
    """Turkish Character Sensitivity (OCRTurk paper, Eq. 2): TCS = 1 - E/N.

    E = number of Turkish special character errors (positions where they differ).
    N = total Turkish special characters in the expected string.
    Returns 1.0 if there are no Turkish special characters (metric is N/A = perfect).
    """
    turkish_positions = [
        (i, ch)
        for i, ch in enumerate(expected)
        if ch in TURKISH_SPECIAL_CHARS
    ]
    if not turkish_positions:
        return 1.0
    correct = sum(
        1
        for i, ch in turkish_positions
        if i < len(predicted) and predicted[i] == ch
    )
    return correct / len(turkish_positions)


def compute_sample_tcs(result: BenchmarkSampleResult) -> float:
    """Compute average TCS across all field scores in a sample result."""
    tcs_values: list[float] = []
    for score in result.per_field_scores:
        tcs = compute_tcs(score.expected_value, score.predicted_value)
        tcs_values.append(tcs)
    if not tcs_values:
        return 1.0
    return sum(tcs_values) / len(tcs_values)


CONFIDENCE_BUCKETS = (
```

**`aggregate_results()` fonksiyonunu güncelle:** Dönüş değerini değiştir (line 161-173).

**ÖNCE:**
```python
    return BenchmarkAggregateMetrics(
        field_normalized_exact_match=(matched_fields / total_fields) if total_fields else 0.0,
        field_coverage=(covered_fields / total_fields) if total_fields else 0.0,
        document_success_rate=(document_successes / len(results)) if results else 0.0,
        normalized_document_success_rate=(
            normalized_document_successes / len(results)
        )
        if results
        else 0.0,
        confidence_average=average_confidence(confidence_values, default=0.0),
        confidence_vs_accuracy=confidence_vs_accuracy,
        review_reason_counts=dict(sorted(review_reason_counts.items())),
    )
```

**SONRA:**
```python
    tcs_values = [compute_sample_tcs(r) for r in results]
    aggregate_tcs = sum(tcs_values) / len(tcs_values) if tcs_values else 1.0

    return BenchmarkAggregateMetrics(
        field_normalized_exact_match=(matched_fields / total_fields) if total_fields else 0.0,
        field_coverage=(covered_fields / total_fields) if total_fields else 0.0,
        document_success_rate=(document_successes / len(results)) if results else 0.0,
        normalized_document_success_rate=(
            normalized_document_successes / len(results)
        )
        if results
        else 0.0,
        confidence_average=average_confidence(confidence_values, default=0.0),
        confidence_vs_accuracy=confidence_vs_accuracy,
        review_reason_counts=dict(sorted(review_reason_counts.items())),
        turkish_char_sensitivity=aggregate_tcs,
    )
```

---

### Dosya 2: `src/formai/benchmarks/models.py`

**`BenchmarkAggregateMetrics` dataclass'ına alan ekle (line 54-62).**

**ÖNCE:**
```python
@dataclass
class BenchmarkAggregateMetrics:
    field_normalized_exact_match: float = 0.0
    field_coverage: float = 0.0
    document_success_rate: float = 0.0
    normalized_document_success_rate: float = 0.0
    confidence_average: float = 0.0
    confidence_vs_accuracy: Dict[str, Dict[str, float]] = field(default_factory=dict)
    review_reason_counts: Dict[str, int] = field(default_factory=dict)
```

**SONRA:**
```python
@dataclass
class BenchmarkAggregateMetrics:
    field_normalized_exact_match: float = 0.0
    field_coverage: float = 0.0
    document_success_rate: float = 0.0
    normalized_document_success_rate: float = 0.0
    confidence_average: float = 0.0
    confidence_vs_accuracy: Dict[str, Dict[str, float]] = field(default_factory=dict)
    review_reason_counts: Dict[str, int] = field(default_factory=dict)
    turkish_char_sensitivity: float = 1.0  # OCRTurk TCS; 1.0 = N/A (no Turkish chars)
```

---

## Commit 10 — P1-A2: Runner TCS Gates + Test

### Dosya 1: `src/formai/benchmarks/runner.py`

**`VALIDATION_GATE_THRESHOLDS` dict'ine Türkçe dataset'ler için TCS gate'leri ekle (line 52-65).**

**ÖNCE (dict son kısmı):**
```python
    "template_e2e": {
        "field_match_rate": 0.97,
        "case_success_rate": 0.80,
    },
}
```

**SONRA:**
```python
    "template_e2e": {
        "field_match_rate": 0.97,
        "case_success_rate": 0.80,
    },
    "turkish_printed": {
        "field_normalized_exact_match": 0.75,
        "field_coverage": 0.90,
        "turkish_char_sensitivity": 0.80,
    },
    "turkish_handwritten": {
        "field_normalized_exact_match": 0.60,
        "field_coverage": 0.85,
        "turkish_char_sensitivity": 0.72,
    },
    "turkish_petitions": {
        "field_normalized_exact_match": 0.70,
        "field_coverage": 0.88,
        "turkish_char_sensitivity": 0.78,
    },
}
```

---

### Dosya 2: `tests/test_tcs_metric.py` (Yeni Dosya)

```python
from __future__ import annotations

import unittest

from formai.benchmarks.scoring import compute_tcs, compute_sample_tcs, aggregate_results
from formai.benchmarks.models import (
    BenchmarkSampleResult,
    PerFieldScore,
    BenchmarkAggregateMetrics,
)
from formai.models import FieldKind


def _make_score(expected: str, predicted: str) -> PerFieldScore:
    return PerFieldScore(
        key="test_field",
        expected_value=expected,
        predicted_value=predicted,
        field_kind=FieldKind.TEXT,
        normalized_exact_match=(expected == predicted),
        covered=bool(predicted.strip()),
        confidence=0.9,
        status="matched" if expected == predicted else "mismatch",
    )


def _make_result(scores: list[PerFieldScore]) -> BenchmarkSampleResult:
    return BenchmarkSampleResult(
        sample_id="test",
        per_field_scores=scores,
        confidence=0.9,
        field_normalized_exact_match=0.0,
        field_coverage=0.0,
    )


class TestComputeTCS(unittest.TestCase):
    def test_perfect_match_returns_1(self):
        self.assertAlmostEqual(compute_tcs("Ayşe", "Ayşe"), 1.0)

    def test_single_char_error_ş(self):
        # "ş" expected at index 2, "s" predicted → 0/1 correct
        self.assertAlmostEqual(compute_tcs("Ayşe", "Ayse"), 0.0)

    def test_multiple_turkish_chars_partial(self):
        # "Öğrenci": Ö at 0, ğ at 2 → both wrong in "Ogrenci" → 0/2
        self.assertAlmostEqual(compute_tcs("Öğrenci", "Ogrenci"), 0.0)

    def test_no_turkish_chars_returns_1(self):
        # "John" has no Turkish special chars
        self.assertAlmostEqual(compute_tcs("John", "Jon"), 1.0)

    def test_empty_strings(self):
        self.assertAlmostEqual(compute_tcs("", ""), 1.0)

    def test_predicted_shorter_than_expected(self):
        # "üç" → predicted is "" → 0/2
        self.assertAlmostEqual(compute_tcs("üç", ""), 0.0)

    def test_mixed_correct_and_wrong(self):
        # "çğ": ç at 0 correct, ğ at 1 wrong → 1/2 = 0.5
        self.assertAlmostEqual(compute_tcs("çğ", "çg"), 0.5)


class TestAggregateTCS(unittest.TestCase):
    def test_aggregate_results_includes_tcs(self):
        result = _make_result([
            _make_score("Ayşe", "Ayse"),   # TCS = 0.0
            _make_score("John", "Jon"),     # TCS = 1.0 (no Turkish chars)
        ])
        agg = aggregate_results([result])
        self.assertIsInstance(agg, BenchmarkAggregateMetrics)
        self.assertAlmostEqual(agg.turkish_char_sensitivity, 0.5)

    def test_aggregate_empty_results(self):
        agg = aggregate_results([])
        self.assertAlmostEqual(agg.turkish_char_sensitivity, 1.0)

    def test_aggregate_all_correct_turkish(self):
        result = _make_result([_make_score("Öğrenci", "Öğrenci")])
        agg = aggregate_results([result])
        self.assertAlmostEqual(agg.turkish_char_sensitivity, 1.0)


if __name__ == "__main__":
    unittest.main()
```

---

## Commit 11 — P1-B1: `src/formai/benchmarks/ocrturk.py` + Config

### Ne Yapılıyor?

OCRTurk benchmark'ı (METU + Roketsan, 180 Türkçe belge, 4 kategori) için
`DatasetAdapter` implement et. Gerçek dataset olmadan `IntegrationUnavailable` fırlatır.

### Referans: `src/formai/benchmarks/turkish_petitions.py`

OCRTurk adapter, `LocalManifestAdapter` yerine `DatasetAdapter`'dan doğrudan türer
çünkü OCRTurk farklı bir dizin yapısına sahip.

### OCRTurk Repo Yapısı (github.com/metunlp/ocrturk)

```
ocrturk/
├── images/
│   ├── academic/
│   ├── non_academic/
│   ├── theses/
│   └── slideshows/
└── ground_truth/
    ├── academic.json
    ├── non_academic.json
    ├── theses.json
    └── slideshows.json
```

Ground truth JSON formatı:
```json
[
  {"image": "img_0001.jpg", "text": "Türkçe metin içeriği..."},
  ...
]
```

### Yeni Dosya: `src/formai/benchmarks/ocrturk.py`

```python
from __future__ import annotations

import json
import io
from pathlib import Path
from typing import Dict, List, Sequence

from formai.benchmarks.base import DatasetAdapter
from formai.benchmarks.models import BenchmarkSample, ExpectedField
from formai.errors import IntegrationUnavailable
from formai.models import FieldKind, RenderedPage

_SPLIT_TO_CATEGORIES: Dict[str, List[str]] = {
    "test": ["non_academic"],
    "academic": ["academic"],
    "theses": ["theses"],
    "slideshows": ["slideshows"],
    "all": ["academic", "non_academic", "theses", "slideshows"],
}


class OCRTurkAdapter(DatasetAdapter):
    """Dataset adapter for the OCRTurk benchmark.

    Source: https://github.com/metunlp/ocrturk
    Paper: OCRTurk: A Comprehensive OCR Benchmark for Turkish (SIGTURK 2026)

    Requires ``FORMAI_OCRTURK_DATASET_DIR`` to be set to the local clone of the
    ocrturk repository. Raises ``IntegrationUnavailable`` otherwise.

    Directory layout expected::

        <dataset_dir>/
        ├── images/{academic,non_academic,theses,slideshows}/
        └── ground_truth/{academic,non_academic,theses,slideshows}.json
    """

    dataset_name = "ocrturk"

    def __init__(self, dataset_dir: Path | None = None) -> None:
        self._dataset_dir = dataset_dir

    def load_samples(
        self,
        split: str,
        max_samples: int | None = None,
    ) -> Sequence[BenchmarkSample]:
        if self._dataset_dir is None:
            raise IntegrationUnavailable(
                "OCRTurk dataset directory is not configured. "
                "Set FORMAI_OCRTURK_DATASET_DIR to the local path of the ocrturk repo."
            )
        root = self._resolve_dataset_root()
        categories = _SPLIT_TO_CATEGORIES.get(split)
        if categories is None:
            raise ValueError(
                f"Unknown split '{split}'. "
                f"Valid splits: {sorted(_SPLIT_TO_CATEGORIES.keys())}"
            )
        samples: List[BenchmarkSample] = []
        for category in categories:
            gt_path = root / "ground_truth" / f"{category}.json"
            img_dir = root / "images" / category
            if not gt_path.exists():
                continue
            ground_truth = self._load_ground_truth(gt_path)
            for img_name, text in ground_truth.items():
                if max_samples is not None and len(samples) >= max_samples:
                    break
                image_path = img_dir / img_name
                if not image_path.exists():
                    # Try common extensions
                    for ext in (".jpg", ".jpeg", ".png"):
                        candidate = img_dir / (Path(img_name).stem + ext)
                        if candidate.exists():
                            image_path = candidate
                            break
                    else:
                        continue
                try:
                    rendered = self._page_image_to_rendered_page(image_path)
                except Exception:
                    continue
                sample_id = f"ocrturk_{category}_{Path(img_name).stem}"
                samples.append(
                    BenchmarkSample(
                        sample_id=sample_id,
                        dataset=self.dataset_name,
                        split=split,
                        rendered_pages=[rendered],
                        expected_fields=[
                            ExpectedField(
                                key="full_text",
                                value=text,
                                field_kind=FieldKind.TEXT,
                            )
                        ],
                    )
                )
            if max_samples is not None and len(samples) >= max_samples:
                break
        return samples

    def _resolve_dataset_root(self) -> Path:
        assert self._dataset_dir is not None
        root = Path(self._dataset_dir)
        if not root.exists():
            raise IntegrationUnavailable(
                f"OCRTurk dataset directory does not exist: {root}"
            )
        return root

    def _load_ground_truth(self, gt_path: Path) -> Dict[str, str]:
        """Load ground truth JSON → {image_filename: text} dict."""
        with gt_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        result: Dict[str, str] = {}
        if isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict):
                    img = entry.get("image") or entry.get("filename") or ""
                    text = entry.get("text") or entry.get("ground_truth") or ""
                    if img:
                        result[str(img)] = str(text)
        elif isinstance(data, dict):
            for img, text in data.items():
                result[str(img)] = str(text) if not isinstance(text, str) else text
        return result

    def _page_image_to_rendered_page(self, image_path: Path) -> RenderedPage:
        """Convert an image file to a RenderedPage."""
        from PIL import Image
        with Image.open(image_path) as img:
            width, height = img.size
            buf = io.BytesIO()
            fmt = "PNG" if image_path.suffix.lower() == ".png" else "JPEG"
            img.save(buf, format=fmt)
            image_bytes = buf.getvalue()
        mime_type = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
        return RenderedPage(
            page_number=1,
            mime_type=mime_type,
            image_bytes=image_bytes,
            width=width,
            height=height,
        )
```

---

### Config Değişikliği: `src/formai/config.py`

**`turkish_petitions_dataset_dir` satırından (line 27) sonra ekle:**

**ÖNCE:**
```python
    turkish_petitions_dataset_dir: str = ""
    validation_template_path: str = ""
```

**SONRA:**
```python
    turkish_petitions_dataset_dir: str = ""
    ocrturk_dataset_dir: str = ""
    validation_template_path: str = ""
```

**`from_env()` metodunda `turkish_petitions_dataset_dir=...` satırından sonra ekle:**

**ÖNCE:**
```python
            turkish_petitions_dataset_dir=os.getenv(
                "FORMAI_TURKISH_PETITIONS_DATASET_DIR",
                "",
            ),
            validation_template_path=os.getenv("FORMAI_VALIDATION_TEMPLATE_PATH", ""),
```

**SONRA:**
```python
            turkish_petitions_dataset_dir=os.getenv(
                "FORMAI_TURKISH_PETITIONS_DATASET_DIR",
                "",
            ),
            ocrturk_dataset_dir=os.getenv("FORMAI_OCRTURK_DATASET_DIR", ""),
            validation_template_path=os.getenv("FORMAI_VALIDATION_TEMPLATE_PATH", ""),
```

---

## Commit 12 — P1-B2: Runner OCRTurk Kaydı + Test

### Dosya 1: `src/formai/benchmarks/runner.py`

**4 yerde değişiklik yapılır:**

**1) Import'a OCRTurkAdapter ekle (line 14 civarı, diğer adapter import'larının yanına):**

**ÖNCE:**
```python
from formai.benchmarks.turkish_handwritten import TurkishHandwrittenAdapter
from formai.benchmarks.turkish_petitions import TurkishPetitionsAdapter
from formai.benchmarks.turkish_printed import TurkishPrintedAdapter
```

**SONRA:**
```python
from formai.benchmarks.ocrturk import OCRTurkAdapter
from formai.benchmarks.turkish_handwritten import TurkishHandwrittenAdapter
from formai.benchmarks.turkish_petitions import TurkishPetitionsAdapter
from formai.benchmarks.turkish_printed import TurkishPrintedAdapter
```

**2) `PACK_SAMPLE_LIMITS` dict'e ocrturk ekle (line 44-51 arası, mevcut son entry'den sonra):**

**ÖNCE:**
```python
    "turkish_petitions": {"smoke": 3, "regression": 10, "tuning": 25, "release": 10},
}
```

**SONRA:**
```python
    "turkish_petitions": {"smoke": 3, "regression": 10, "tuning": 25, "release": 10},
    "ocrturk": {"smoke": 5, "regression": 20, "tuning": 45, "release": 45},
}
```

**3) `RELEASE_PROFILE_BY_DATASET` dict'e ocrturk ekle (line 30-36 arası):**

**ÖNCE:**
```python
RELEASE_PROFILE_BY_DATASET = {
    "funsd_plus": "general_forms",
    "fir": "handwriting",
    "turkish_printed": "turkish_printed",
    "turkish_handwritten": "turkish_handwritten",
    "turkish_petitions": "turkish_petitions",
}
```

**SONRA:**
```python
RELEASE_PROFILE_BY_DATASET = {
    "funsd_plus": "general_forms",
    "fir": "handwriting",
    "turkish_printed": "turkish_printed",
    "turkish_handwritten": "turkish_handwritten",
    "turkish_petitions": "turkish_petitions",
    "ocrturk": "turkish_printed",
}
```

**4) `BenchmarkRunner.__init__()` içinde `self.adapters` dict'ine OCRTurk ekle (line 78-101 arası).**
OCRTurk sadece `ocrturk_dataset_dir` doluysa eklenir:

**ÖNCE (adapters dict son satırı):**
```python
            TurkishPetitionsAdapter.dataset_name: TurkishPetitionsAdapter(
                dataset_dir=Path(self.extractor.config.turkish_petitions_dataset_dir)
                if self.extractor.config.turkish_petitions_dataset_dir
                else None
            ),
        }
```

**SONRA:**
```python
            TurkishPetitionsAdapter.dataset_name: TurkishPetitionsAdapter(
                dataset_dir=Path(self.extractor.config.turkish_petitions_dataset_dir)
                if self.extractor.config.turkish_petitions_dataset_dir
                else None
            ),
            **({
                OCRTurkAdapter.dataset_name: OCRTurkAdapter(
                    dataset_dir=Path(self.extractor.config.ocrturk_dataset_dir)
                )
            } if self.extractor.config.ocrturk_dataset_dir else {}),
        }
```

---

### Dosya 2: `tests/test_benchmarks_ocrturk.py` (Yeni Dosya)

```python
from __future__ import annotations

import json
import unittest
from pathlib import Path
import tempfile

from formai.errors import IntegrationUnavailable


class TestOCRTurkAdapterNoDir(unittest.TestCase):
    def test_none_dir_raises_integration_unavailable(self):
        from formai.benchmarks.ocrturk import OCRTurkAdapter
        adapter = OCRTurkAdapter(dataset_dir=None)
        with self.assertRaises(IntegrationUnavailable):
            adapter.load_samples("test")


class TestOCRTurkAdapterWithFakeData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        # Create directory structure
        (root / "ground_truth").mkdir()
        (root / "images" / "non_academic").mkdir(parents=True)
        # Create minimal PNG (1x1 white pixel)
        import struct, zlib
        def _minimal_png() -> bytes:
            sig = b"\x89PNG\r\n\x1a\n"
            def chunk(name, data):
                c = struct.pack(">I", len(data)) + name + data
                return c + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
            ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            idat_data = zlib.compress(b"\x00\xff\xff\xff")
            idat = chunk(b"IDAT", idat_data)
            iend = chunk(b"IEND", b"")
            return sig + ihdr + idat + iend

        img_bytes = _minimal_png()
        img_path = root / "images" / "non_academic" / "img_001.png"
        img_path.write_bytes(img_bytes)
        # Ground truth JSON
        gt = [{"image": "img_001.png", "text": "Türkçe metin içeriği"}]
        (root / "ground_truth" / "non_academic.json").write_text(
            json.dumps(gt), encoding="utf-8"
        )
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_samples_test_split(self):
        from formai.benchmarks.ocrturk import OCRTurkAdapter
        adapter = OCRTurkAdapter(dataset_dir=self.root)
        samples = adapter.load_samples("test", max_samples=1)
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].dataset, "ocrturk")
        self.assertEqual(len(samples[0].expected_fields), 1)
        self.assertEqual(samples[0].expected_fields[0].key, "full_text")
        self.assertIn("Türkçe", samples[0].expected_fields[0].value)

    def test_load_samples_max_samples(self):
        from formai.benchmarks.ocrturk import OCRTurkAdapter
        adapter = OCRTurkAdapter(dataset_dir=self.root)
        samples = adapter.load_samples("test", max_samples=0)
        # max_samples=0 → no samples loaded
        self.assertEqual(len(samples), 0)

    def test_unknown_split_raises_value_error(self):
        from formai.benchmarks.ocrturk import OCRTurkAdapter
        adapter = OCRTurkAdapter(dataset_dir=self.root)
        with self.assertRaises(ValueError):
            adapter.load_samples("invalid_split")


if __name__ == "__main__":
    unittest.main()
```

---

## Final Doğrulama — Tüm Adımlar Bittikten Sonra

### 1. Tüm testleri çalıştır

```bash
cd /Users/emirhanfirtina/Desktop/yeniP
env PYTHONPATH=src .venv311/bin/python -m unittest discover -s tests -v 2>&1 | tail -20
# Beklenen: 124+ tests OK, 0 failures
```

### 2. PaddleOCR ile pipeline test (PaddleOCR kuruluysa)

```bash
FORMAI_CROP_OCR_PROVIDER=paddleocr \
  env PYTHONPATH=src .venv311/bin/python -m pytest tests/test_ocr_paddleocr.py -v
```

### 3. GLM-OCR SDK provider test (SDK kuruluysa)

```bash
FORMAI_VISION_PROVIDER=glm_ocr_sdk \
  env PYTHONPATH=src .venv311/bin/python -m pytest tests/test_llm_glm_ocr_sdk.py -v
```

### 4. TCS metriği test

```bash
env PYTHONPATH=src .venv311/bin/python -m pytest tests/test_tcs_metric.py -v
# Beklenen: compute_tcs("Ayşe","Ayse") → 0.0, compute_tcs("John","Jon") → 1.0
```

### 5. OCRTurk adapter test

```bash
env PYTHONPATH=src .venv311/bin/python -m pytest tests/test_benchmarks_ocrturk.py -v
```

### 6. Gerçek Türkçe form kalite kontrolü (kalite gate'i)

```bash
# Aşağıdaki değerlerin karşılanması gerekiyor:
# self_check_passed = true
# evidence_score >= 0.58
# TCS >= 0.78 (turkish_petitions smoke benchmark)
FORMAI_CROP_OCR_PROVIDER=paddleocr \
  env PYTHONPATH=src .venv311/bin/python -m formai run \
    --template ./ornek/input.pdf \
    --filled ./tmp/demo/ornek_filled.pdf \
    --fillable-output ./tmp/demo/fillable.pdf \
    --final-output ./tmp/demo/final.pdf
```

---

## GitHub Push Kuralı (Tekrar Hatırlatma)

```
⛔ BU TAMAMLANMADAN PUSH YAPMA:
   □ self_check_passed = true (final_assembler çıktısında)
   □ evidence_score ≥ 0.58
   □ TCS ≥ 0.78 (turkish_petitions smoke benchmark)

✅ PUSH YAPILACAKSA:
   1. Kullanıcıya yaz: "Push yapmak istiyorum, onaylıyor musun?"
   2. Kullanıcının "evet" veya "onayla" demesini bekle
   3. Sadece o zaman: git push origin main
```

---

## Özet: Commit Sırası

| # | Commit | Değiştirilen / Oluşturulan Dosya(lar) |
|---|--------|--------------------------------------|
| 1 | P0-C | Doğrulama only, kod yok |
| 2 | P0-A1 | `src/formai/ocr/paddleocr.py` (YENİ) |
| 3 | P0-A2,3 | `config.py` (3 alan), `pipeline.py` (build_crop_ocr_reader) |
| 4 | P0-A4,5 | `verification/engine.py` (ocr_reader param), `final_assembler.py` (ocr_reader) |
| 5 | P0-A5b | `pipeline.py` (build_default_pipeline assembler satırı) |
| 6 | P0-A6 | `pyproject.toml` (paddleocr group), `tests/test_ocr_paddleocr.py` (YENİ) |
| 7 | P0-B1 | `src/formai/llm/glm_ocr_sdk.py` (YENİ) |
| 8 | P0-B2 | `config.py` (4 alan), `pipeline.py` (glm_ocr_sdk branch), `pyproject.toml`, `tests/test_llm_glm_ocr_sdk.py` (YENİ) |
| 9 | P1-A1 | `benchmarks/scoring.py` (compute_tcs), `benchmarks/models.py` (alan) |
| 10 | P1-A2 | `benchmarks/runner.py` (TCS gates), `tests/test_tcs_metric.py` (YENİ) |
| 11 | P1-B1 | `src/formai/benchmarks/ocrturk.py` (YENİ), `config.py` (1 alan) |
| 12 | P1-B2 | `benchmarks/runner.py` (OCRTurk adapter), `tests/test_benchmarks_ocrturk.py` (YENİ) |
