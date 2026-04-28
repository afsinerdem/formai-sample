from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Tuple

from formai.errors import IntegrationUnavailable
from formai.mapping import match_detected_fields_to_acro_fields, propose_field_names
from formai.models import AcroField, DetectedField, FieldKind, FieldMapping, MappingStatus
from formai.pdf.inspector import (
    deduplicate_fields_by_geometry,
    inspect_pdf_fields,
    prune_pdf_fields,
    rename_pdf_fields,
)
from formai.pdf.widget_builder import WidgetDefinition, build_fillable_pdf
from formai.segmentation import continuation_field_name
from formai.utils import average_confidence, ensure_unique_slug


class CommonFormsAdapter:
    def __init__(
        self,
        *,
        model_or_path: str = "FFDNet-L",
        device: str = "cpu",
        fast: bool = True,
        confidence: float = 0.6,
        multiline: bool = True,
    ):
        self.model_or_path = model_or_path
        self.device = device
        self.fast = fast
        self.confidence = confidence
        self.multiline = multiline

    def prepare_fillable_pdf(
        self, input_path: Path, output_path: Path, detected_fields: List[DetectedField]
    ) -> Tuple[List[AcroField], List[FieldMapping], dict, float]:
        if detected_fields:
            return self._create_from_detected_fields(input_path, output_path, detected_fields)

        prepare_form = self._import_prepare_form()

        with TemporaryDirectory(prefix="formai_commonforms_") as temp_dir:
            temp_output = Path(temp_dir) / "prepared.pdf"
            pruned_output = Path(temp_dir) / "prepared_pruned.pdf"
            prepare_form(
                str(input_path),
                str(temp_output),
                model_or_path=self.model_or_path,
                device=self.device,
                fast=self.fast,
                confidence=self.confidence,
                multiline=self.multiline,
            )
            generated_fields = deduplicate_fields_by_geometry(inspect_pdf_fields(temp_output))
            mappings = match_detected_fields_to_acro_fields(detected_fields, generated_fields)
            keep_names = self._build_keep_names(generated_fields, mappings)
            prune_pdf_fields(temp_output, pruned_output, keep_names)
            rename_map = self._build_rename_map(mappings)
            rename_pdf_fields(pruned_output, rename_map, output_path)

        renamed_fields = inspect_pdf_fields(output_path)
        confidence = average_confidence([mapping.confidence for mapping in mappings], default=0.0)
        return renamed_fields, mappings, rename_map, confidence

    def _create_from_detected_fields(
        self, input_path: Path, output_path: Path, detected_fields: List[DetectedField]
    ) -> Tuple[List[AcroField], List[FieldMapping], dict, float]:
        rename_map = propose_field_names(detected_fields)
        mappings: List[FieldMapping] = []
        widgets: List[WidgetDefinition] = []

        for detected_field in detected_fields:
            field_name = rename_map[detected_field.label]
            page_index = max(0, detected_field.box.page_number - 1)

            if self._should_split_multiline_field(detected_field):
                widgets.append(
                    WidgetDefinition(
                        name=field_name,
                        field_kind=FieldKind.TEXT,
                        page_index=page_index,
                        box=detected_field.box,
                        tooltip=detected_field.label,
                        multiline=False,
                    )
                )
                for segment_index, continuation_box in enumerate(
                    self._split_continuation_box(detected_field.continuation_box),
                    start=1,
                ):
                    widgets.append(
                        WidgetDefinition(
                            name=continuation_field_name(field_name, segment_index),
                            field_kind=FieldKind.TEXT,
                            page_index=page_index,
                            box=continuation_box,
                            tooltip=detected_field.label,
                            multiline=False,
                        )
                    )
            else:
                widgets.append(
                    WidgetDefinition(
                        name=field_name,
                        field_kind=detected_field.field_kind,
                        page_index=page_index,
                        box=detected_field.box,
                        tooltip=detected_field.label,
                        multiline=detected_field.field_kind == FieldKind.MULTILINE,
                    )
                )

            mappings.append(
                FieldMapping(
                    source_key=detected_field.label,
                    target_field=field_name,
                    confidence=detected_field.confidence,
                    status=MappingStatus.MAPPED,
                    notes="Created directly from detected layout fields.",
                )
            )

        build_fillable_pdf(
            input_path=input_path,
            output_path=output_path,
            widgets=widgets,
        )

        acro_fields = inspect_pdf_fields(output_path)
        confidence = average_confidence([field.confidence for field in detected_fields], default=0.0)
        return acro_fields, mappings, rename_map, confidence

    def _should_split_multiline_field(self, detected_field: DetectedField) -> bool:
        continuation_box = detected_field.continuation_box
        if detected_field.field_kind != FieldKind.MULTILINE or continuation_box is None:
            return False
        return continuation_box.left + 12.0 < detected_field.box.left

    def _split_continuation_box(self, continuation_box):
        line_count = self._continuation_line_count(continuation_box.height)
        if line_count <= 1:
            return [continuation_box]
        segment_height = continuation_box.height / line_count
        boxes = []
        for index in range(line_count):
            top = continuation_box.top + (segment_height * index)
            bottom = continuation_box.top + (segment_height * (index + 1))
            boxes.append(
                type(continuation_box)(
                    page_number=continuation_box.page_number,
                    left=continuation_box.left,
                    top=top + 2.0,
                    right=continuation_box.right,
                    bottom=bottom - 2.0,
                    reference_width=continuation_box.reference_width,
                    reference_height=continuation_box.reference_height,
                )
            )
        return boxes

    def _continuation_line_count(self, height: float) -> int:
        if height <= 24.0:
            return 1
        if height <= 44.0:
            return 2
        return max(2, int((height + 2.0) // 20.0))

    def _import_prepare_form(self):
        try:
            from commonforms import prepare_form
        except ImportError as exc:
            raise IntegrationUnavailable(
                "commonforms is not installed. Install with: pip install -e '.[commonforms]'"
            ) from exc
        return prepare_form

    def _build_rename_map(self, mappings: List[FieldMapping]) -> dict:
        rename_map = {}
        used_names = set()
        for mapping in mappings:
            if not mapping.target_field:
                continue
            rename_map[mapping.target_field] = ensure_unique_slug(mapping.source_key, used_names)
        return rename_map

    def _build_keep_names(
        self, generated_fields: List[AcroField], mappings: List[FieldMapping]
    ) -> List[str]:
        matched_names = [mapping.target_field for mapping in mappings if mapping.target_field]
        if matched_names:
            return matched_names
        return [field.name for field in generated_fields]

    def _page_sizes(self, input_path: Path):
        try:
            import fitz
        except ImportError as exc:
            raise IntegrationUnavailable("PyMuPDF is required for geometry normalization.") from exc

        document = fitz.open(str(input_path))
        try:
            return [
                (
                    float(page.rect.width) or 1.0,
                    float(page.rect.height) or 1.0,
                )
                for page in document
            ]
        finally:
            document.close()
