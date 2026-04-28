from __future__ import annotations

from dataclasses import dataclass

from formai.models import BoundingBox
from formai.profiles import STUDENT_PETITION_PROFILE


@dataclass(frozen=True)
class RenderSpec:
    box: tuple[float, float, float, float]
    font_size: float | None = None
    multiline_font_size: float | None = None
    horizontal_inset: float = 1.5
    baseline_inset: float = 0.8
    top_inset: float = 1.8
    background_padding: float = 1.0


_STUDENT_PETITION_RENDER_SPECS: dict[str, RenderSpec] = {
    "tarih": RenderSpec((430.0, 118.0, 526.0, 134.0), font_size=9.2, baseline_inset=0.2, background_padding=0.0),
    "fakulte_birim": RenderSpec((178.0, 169.0, 314.0, 185.0), font_size=10.6, baseline_inset=0.0, background_padding=0.0),
    "ogrenci_no": RenderSpec((42.0, 200.0, 136.0, 213.0), font_size=8.7, baseline_inset=0.0, background_padding=0.0),
    "egitim_yili": RenderSpec((239.0, 201.0, 294.0, 214.0), font_size=8.4, baseline_inset=0.0, background_padding=0.0),
    "yariyil": RenderSpec((340.0, 201.0, 372.0, 214.0), font_size=8.4, baseline_inset=0.0, background_padding=0.0),
    "bolum_program": RenderSpec((318.0, 183.0, 446.0, 198.0), font_size=9.5, baseline_inset=0.0, background_padding=0.0),
    "ad_soyad": RenderSpec((150.0, 278.0, 290.0, 294.0), font_size=11.3, baseline_inset=0.1, background_padding=0.0),
    "telefon": RenderSpec((150.0, 297.0, 273.0, 312.0), font_size=10.5, baseline_inset=0.1, background_padding=0.0),
    "e_posta": RenderSpec((316.0, 297.0, 481.0, 312.0), font_size=9.7, baseline_inset=0.1, background_padding=0.0),
    "adres": RenderSpec((150.0, 317.0, 500.0, 332.0), font_size=9.9, baseline_inset=0.1, background_padding=0.0),
    "ders_kodu": RenderSpec((99.0, 388.0, 160.0, 408.0), font_size=10.8, baseline_inset=0.7, background_padding=0.0),
    "ders_adi": RenderSpec((153.0, 388.0, 360.0, 408.0), font_size=9.4, baseline_inset=0.7, background_padding=0.0),
    "ders_kredisi": RenderSpec((392.0, 388.0, 421.0, 408.0), font_size=10.8, baseline_inset=0.7, background_padding=0.0),
    "akts": RenderSpec((455.0, 388.0, 482.0, 408.0), font_size=10.8, baseline_inset=0.7, background_padding=0.0),
    "ders_notu": RenderSpec((520.0, 388.0, 540.0, 408.0), font_size=11.6, baseline_inset=0.7, background_padding=0.0),
    "danisman_adi": RenderSpec((160.0, 433.0, 305.0, 449.0), font_size=10.4, baseline_inset=0.1, background_padding=0.0),
    "danisman_gorusu": RenderSpec((164.0, 450.0, 433.0, 478.0), font_size=9.2, multiline_font_size=8.9, top_inset=1.0, background_padding=0.0),
    "gno": RenderSpec((105.0, 473.0, 144.0, 488.0), font_size=11.3, baseline_inset=0.0, background_padding=0.0),
    "donem_sayisi": RenderSpec((143.0, 494.0, 168.0, 508.0), font_size=11.3, baseline_inset=0.0, background_padding=0.0),
    "danisman_tarih_imza": RenderSpec((76.0, 536.0, 314.0, 552.0), font_size=10.3, baseline_inset=0.0, background_padding=0.0),
    "mali_onay_ders_akts": RenderSpec((437.0, 584.0, 517.0, 601.0), font_size=10.5, baseline_inset=0.1, background_padding=0.0),
    "mali_onay_ad_soyad": RenderSpec((356.0, 605.0, 507.0, 621.0), font_size=10.2, baseline_inset=0.1, background_padding=0.0),
    "mali_onay_tarih_imza": RenderSpec((355.0, 633.0, 542.0, 649.0), font_size=9.6, baseline_inset=0.0, background_padding=0.0),
}


def resolve_render_box(profile: str, field_name: str, original_box: BoundingBox | None) -> BoundingBox | None:
    if original_box is None:
        return None
    return original_box


def resolve_render_spec(profile: str, field_name: str) -> RenderSpec | None:
    if profile == STUDENT_PETITION_PROFILE:
        return _STUDENT_PETITION_RENDER_SPECS.get(field_name)
    return None
