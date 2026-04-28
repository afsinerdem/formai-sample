from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from formai.models import AcroField, BoundingBox, FieldKind
from formai.profiles import STUDENT_PETITION_PROFILE
from formai.rendering.contracts import (
    RenderContentRun,
    RenderPlan,
    RenderPlanItem,
    RenderPolicy,
    RenderWriterKind,
)
from formai.rendering.layouts import RenderSpec, resolve_render_spec
from formai.rendering.writers import get_render_writer


INLINE_HINTS = {
    "ad_soyad",
    "fakulte_birim",
    "ogrenci_no",
    "egitim_yili",
    "yariyil",
    "bolum_program",
    "danisman_adi",
    "gno",
    "donem_sayisi",
    "mali_onay_ad_soyad",
}

CONTACT_HINTS = {
    "telefon",
    "e_posta",
    "email",
    "e_mail",
    "contact",
    "fax",
}

TABLE_HINTS = {
    "ders_kodu",
    "ders_adi",
    "ders_kredisi",
    "akts",
    "ders_notu",
    "mali_onay_ders_akts",
}

DATE_SIGNATURE_HINTS = {
    "tarih",
    "date",
    "sign",
    "signature",
    "imza",
    "danisman_tarih_imza",
    "mali_onay_tarih_imza",
}

MULTILINE_HINTS = {
    "aciklama",
    "açiklama",
    "opinion",
    "gorusu",
    "görusu",
    "description",
    "notes",
    "adres",
    "witness",
    "incident",
}


class RenderPlanCompiler:
    def compile(
        self,
        template_fields: Sequence[AcroField],
        *,
        filled_values: Mapping[str, str] | None = None,
        profile: str = "generic_printed_form",
    ) -> RenderPlan:
        values = dict(filled_values or {})
        items: list[RenderPlanItem] = []
        warnings: list[str] = []

        for field in sorted(
            template_fields,
            key=lambda item: (
                item.page_number,
                item.box.top if item.box is not None else float("inf"),
                item.box.left if item.box is not None else float("inf"),
                item.name,
            ),
        ):
            value = (values.get(field.name) or "").strip()
            spec = resolve_render_spec(profile, field.name)
            writer_kind = select_render_writer_kind(field, profile=profile, spec=spec)
            writer = get_render_writer(writer_kind)
            detected_region = field.box
            target_region = _resolve_target_region(field, spec)
            policy = writer.build_policy(
                field_name=field.name,
                box=target_region or detected_region,
                font_size=_resolve_font_size(field, spec, writer_kind),
                multiline_font_size=_resolve_multiline_font_size(field, spec, writer_kind),
                horizontal_inset=_resolve_inset(field, spec, "horizontal_inset", 1.5),
                baseline_inset=_resolve_inset(field, spec, "baseline_inset", 0.8),
                top_inset=_resolve_inset(field, spec, "top_inset", 1.8),
                background_padding=_resolve_inset(field, spec, "background_padding", 1.0),
                source="profile_spec" if spec is not None else "heuristic",
            )
            content_runs = writer.build_runs(field.name, value)
            baseline_y = _resolve_baseline_y(target_region or detected_region, policy)
            container_type = _container_type(writer_kind)
            item = RenderPlanItem(
                field_name=field.name,
                page_number=field.page_number,
                writer_kind=writer_kind,
                detected_region=detected_region,
                target_region=target_region,
                value=value,
                field_kind=field.field_kind,
                content_runs=content_runs,
                policy=policy,
                anchor_ref=_anchor_ref(field.name, profile),
                baseline_y=baseline_y,
                container_type=container_type,
                warnings=_item_warnings(field, writer_kind, target_region or detected_region, spec),
            )
            if item.warnings:
                warnings.extend(item.warnings)
            items.append(item)

        return RenderPlan(profile=profile, items=items, warnings=sorted(set(warnings)))


def compile_render_plan(
    template_fields: Sequence[AcroField],
    *,
    filled_values: Mapping[str, str] | None = None,
    profile: str = "generic_printed_form",
) -> RenderPlan:
    return RenderPlanCompiler().compile(
        template_fields,
        filled_values=filled_values,
        profile=profile,
    )


def select_render_writer_kind(
    field: AcroField,
    *,
    profile: str,
    spec: RenderSpec | None = None,
) -> RenderWriterKind:
    field_name = field.name.lower().strip()

    if field.field_kind in {FieldKind.MULTILINE}:
        return RenderWriterKind.MULTILINE

    if field.field_kind in {FieldKind.DATE, FieldKind.SIGNATURE}:
        return RenderWriterKind.DATE_SIGNATURE

    if _matches_any(field_name, DATE_SIGNATURE_HINTS):
        return RenderWriterKind.DATE_SIGNATURE

    if _matches_any(field_name, CONTACT_HINTS):
        return RenderWriterKind.COMPOUND_CONTACT

    if _matches_any(field_name, TABLE_HINTS):
        return RenderWriterKind.TABLE_CELL

    if _matches_any(field_name, MULTILINE_HINTS):
        return RenderWriterKind.MULTILINE

    if profile == STUDENT_PETITION_PROFILE and _matches_any(field_name, INLINE_HINTS):
        return RenderWriterKind.INLINE

    if spec is not None and spec.multiline_font_size is not None:
        return RenderWriterKind.MULTILINE

    if spec is not None and spec.font_size is not None and field.box is not None:
        if field.box.height <= 18.0 and field.box.width <= 210.0:
            return RenderWriterKind.INLINE

    if field.box is not None and field.box.height >= 26.0:
        return RenderWriterKind.MULTILINE

    if field.box is not None and field.box.width <= 120.0 and field.box.height <= 22.0:
        return RenderWriterKind.SINGLE_LINE

    return RenderWriterKind.SINGLE_LINE


def _resolve_target_region(field: AcroField, spec: RenderSpec | None) -> BoundingBox | None:
    if spec is None:
        return field.box
    left, top, right, bottom = spec.box
    return BoundingBox(
        page_number=field.page_number,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        reference_width=field.box.reference_width if field.box is not None else None,
        reference_height=field.box.reference_height if field.box is not None else None,
    )


def _resolve_font_size(field: AcroField, spec: RenderSpec | None, writer_kind: RenderWriterKind) -> float | None:
    if spec is not None and spec.font_size is not None:
        return spec.font_size
    if field.box is None:
        return None
    if writer_kind == RenderWriterKind.MULTILINE:
        return max(6.0, min(12.0, round(field.box.height * 0.36, 1)))
    if writer_kind == RenderWriterKind.INLINE:
        return max(6.5, min(12.0, round(field.box.height * 0.68, 1)))
    return max(6.0, min(12.0, round(field.box.height * 0.75, 1)))


def _resolve_multiline_font_size(field: AcroField, spec: RenderSpec | None, writer_kind: RenderWriterKind) -> float | None:
    if spec is not None and spec.multiline_font_size is not None:
        return spec.multiline_font_size
    if writer_kind != RenderWriterKind.MULTILINE or field.box is None:
        return None
    return max(6.0, min(11.0, round(field.box.height * 0.30, 1)))


def _resolve_inset(field: AcroField, spec: RenderSpec | None, attr: str, default: float) -> float:
    if spec is None:
        return default
    return float(getattr(spec, attr, default))


def _resolve_baseline_y(box: BoundingBox | None, policy: RenderPolicy | None) -> float | None:
    if box is None:
        return None
    baseline_inset = policy.baseline_inset if policy is not None else 0.8
    return max(box.top, box.bottom - baseline_inset)


def _container_type(kind: RenderWriterKind) -> str:
    if kind == RenderWriterKind.TABLE_CELL:
        return "table_cell"
    if kind == RenderWriterKind.MULTILINE:
        return "multiline_block"
    if kind == RenderWriterKind.DATE_SIGNATURE:
        return "date_signature_block"
    if kind == RenderWriterKind.COMPOUND_CONTACT:
        return "compound_contact_row"
    if kind == RenderWriterKind.INLINE:
        return "inline_run"
    return "single_line_field"


def _anchor_ref(field_name: str, profile: str) -> str:
    normalized = field_name.lower().strip()
    return f"{profile}:{normalized}" if profile else normalized


def _item_warnings(
    field: AcroField,
    writer_kind: RenderWriterKind,
    target_region: BoundingBox,
    spec: RenderSpec | None,
) -> list[str]:
    warnings: list[str] = []
    if field.box is None:
        warnings.append("missing_detected_region")
        return warnings
    if target_region.width < 18.0 or target_region.height < 8.0:
        warnings.append("tiny_target_region")
    if spec is not None and spec.box != (
        target_region.left,
        target_region.top,
        target_region.right,
        target_region.bottom,
    ):
        warnings.append("profile_target_region_override")
    if writer_kind == RenderWriterKind.MULTILINE and field.box.height < 20.0:
        warnings.append("multiline_writer_on_short_region")
    return warnings


def _matches_any(field_name: str, names: Iterable[str]) -> bool:
    field_name = field_name.lower()
    return any(name in field_name for name in names)
