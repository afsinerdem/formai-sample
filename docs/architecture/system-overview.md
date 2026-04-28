# Sistem Mimarisi

## Büyük resim

FormAI tek bir OCR çağrısından ibaret değildir. Sistem dört ana aşamalı bir pipeline ve onu destekleyen üç yardımcı katmandan oluşur.

Ana pipeline:
1. `InputEvaluatorAgent`
2. `AcroFormGeneratorAgent`
3. `DataExtractorAgent`
4. `FinalAssemblerAgent`

Yardımcı katmanlar:
- document identity + profile routing
- benchmark / validation
- verification / self-check

## Çekirdek akış

### 1. InputEvaluatorAgent

Görevi:
- PDF'in zaten AcroForm olup olmadığını anlamak
- formun flat mı acroform mu olduğunu belirlemek
- document identity çıkarmak
- hangi route ile ilerleyeceğine karar vermek:
  - `structure_first`
  - `vision_first`
  - `hybrid`
- gerekirse doldurulabilir alan adaylarını bulmak

İş karşılığı:
- sistemin "intake beyni"dir

Kaynak merkezleri:
- `src/formai/agents/input_evaluator.py`
- `src/formai/document_identity.py`
- `src/formai/pdf/routing.py`
- `src/formai/pdf/profile_detectors.py`

### 2. AcroFormGeneratorAgent

Görevi:
- tespit edilen alan adaylarını gerçek PDF widget'larına dönüştürmek
- mevcut field'ları yeniden adlandırmak veya sıfırdan üretmek
- layout validation ile alanların kabul edilebilir olup olmadığını kontrol etmek

İş karşılığı:
- statik formu programatik olarak kullanılabilir hale getirir

Kaynak merkezleri:
- `src/formai/agents/acroform_generator.py`
- `src/formai/pdf/widget_builder.py`
- `src/formai/pdf/geometry.py`
- `src/formai/pdf/validation.py`

### 3. DataExtractorAgent

Görevi:
- dolu formdan field-level veri okumak
- target field setine göre structured output üretmek
- mapping ve review item oluşturmak
- gerekiyorsa crop-level refinement uygulamak
- domain/profile-specific postprocessing yapmak

İş karşılığı:
- "dolu belgeyi okunabilir veri" haline getirir

Kaynak merkezleri:
- `src/formai/agents/data_extractor.py`
- `src/formai/mapping.py`
- `src/formai/postprocessing.py`
- `src/formai/profiles.py`

### 4. FinalAssemblerAgent

Görevi:
- structured data'yı fillable PDF'e yazmak
- kullanıcıya gösterilecek final PDF'i üretmek
- self-check / verification sonucu eklemek

İş karşılığı:
- operasyondaki son kullanıcı çıktısını üretir

Kaynak merkezleri:
- `src/formai/agents/final_assembler.py`
- `src/formai/verification/engine.py`

## Document identity ve profile sistemi

Bu katman FormAI'nin uzun vadeli ölçeklenme stratejisidir.

Kimlik eksenleri:
- document kind
- language
- script style
- layout style
- document family
- domain hint
- profile

Amaç:
- her form için ayrı hack yazmak yerine
- belgeyi önce tanıyıp
- sonra doğru extraction / mapping / verification davranışını seçmek

Bugün öne çıkan profile'lar:
- `generic_printed_form`
- `generic_handwritten_form`
- `student_petition_tr`
- `insurance_incident_en`

## Provider resolution

Vision/extraction tarafı tek bir sağlayıcıya kilitli değildir.

Kod tarafındaki yaklaşım:
- default `auto`
- Ollama uygunsa önce local
- OpenAI key varsa managed cloud yolunu da kullanabilir
- hiçbir sağlayıcı yoksa sistem bunu sessizce gizlemez; degrade olmuş davranış üretir

## Verification katmanı

Verification artık belgeye özel tek dosyalık prototip değil, profile-aware bir alt sistemdir.

Çalışma mantığı:
- geometry check
- OCR evidence check
- varsa LLM visual comparison
- warn + review kararı

Bu katmanın amacı:
- extraction doğru olsa bile final output bozulduysa bunu görmek
- coordinate/placement sorunlarını ölçülebilir hale getirmek

## API ve job modeli

Python pipeline, FastAPI üzerinden asenkron job servisi olarak da açılır.

Job modeli:
- input upload/path
- adım adım step result
- artifact kayıtları
- review items
- issue listesi

Artefact ve job durumu dosya tabanlı job store üzerinden tutulur.

## Web katmanı

Web uygulaması iki rol taşır:
- dış iletişim / marketing
- iç operasyon / workbench

Workbench, job tabanlı API yüzeyinin insan dostu arayüzüdür.
