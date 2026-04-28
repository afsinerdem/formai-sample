from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List

from formai.agents.base import BaseAgent
from formai.errors import IntegrationUnavailable
from formai.models import (
    DocumentKind,
    FieldMapping,
    GenerationResult,
    InputAnalysis,
    IssueSeverity,
    ProcessingIssue,
)
from formai.pdf.commonforms_adapter import CommonFormsAdapter
from formai.pdf.inspector import inspect_pdf_fields, rename_pdf_fields
from formai.pdf.validation import validate_field_layout
from formai.utils import average_confidence, ensure_parent_directory


class AcroFormGeneratorAgent(BaseAgent):
    def __init__(self, config, commonforms_adapter: CommonFormsAdapter):
        super().__init__(config)
        self.commonforms_adapter = commonforms_adapter

    def generate(
        self, input_path: Path, analysis: InputAnalysis, output_path: Path
    ) -> GenerationResult:
        ensure_parent_directory(output_path)
        issues: List[ProcessingIssue] = []
        mappings: List[FieldMapping] = []
        rename_map: Dict[str, str] = {}

        if analysis.document_kind == DocumentKind.ACROFORM and analysis.existing_fields:
            rename_map = {
                review.current_name: review.recommended_name
                for review in analysis.field_name_reviews
                if not review.is_valid and review.current_name != review.recommended_name
            }
            try:
                if rename_map:
                    rename_pdf_fields(input_path, rename_map, output_path)
                    issues.append(
                        ProcessingIssue(
                            code="acroform.fields.renamed",
                            message=f"{len(rename_map)} field name(s) were normalized.",
                            severity=IssueSeverity.INFO,
                        )
                    )
                else:
                    shutil.copyfile(input_path, output_path)

                acro_fields = inspect_pdf_fields(output_path)
            except IntegrationUnavailable as exc:
                issues.append(
                    ProcessingIssue(
                        code="pdf.processing.unavailable",
                        message=str(exc),
                        severity=IssueSeverity.ERROR,
                    )
                )
                return GenerationResult(
                    output_path=output_path,
                    issues=issues,
                    confidence=0.0,
                )
            except Exception as exc:
                issues.append(
                    ProcessingIssue(
                        code="pdf.processing.failed",
                        message=f"PDF processing failed: {exc}",
                        severity=IssueSeverity.ERROR,
                    )
                )
                return GenerationResult(
                    output_path=output_path,
                    issues=issues,
                    confidence=0.0,
                )
            return GenerationResult(
                output_path=output_path,
                acro_fields=acro_fields,
                rename_map=rename_map,
                mappings=mappings,
                issues=issues,
                confidence=average_confidence([analysis.confidence, 0.98]),
            )

        if analysis.document_kind != DocumentKind.FLAT:
            issues.append(
                ProcessingIssue(
                    code="acroform.generation.skipped",
                    message="Input document could not be classified as flat template or AcroForm.",
                    severity=IssueSeverity.ERROR,
                )
            )
            return GenerationResult(
                output_path=output_path,
                issues=issues,
                confidence=0.0,
            )

        try:
            acro_fields, mappings, rename_map, confidence = self.commonforms_adapter.prepare_fillable_pdf(
                input_path=input_path,
                output_path=output_path,
                detected_fields=analysis.detected_fields,
            )
        except IntegrationUnavailable as exc:
            issues.append(
                ProcessingIssue(
                    code="commonforms.unavailable",
                    message=str(exc),
                    severity=IssueSeverity.ERROR,
                )
            )
            return GenerationResult(
                output_path=output_path,
                issues=issues,
                confidence=0.0,
            )
        except Exception as exc:
            issues.append(
                ProcessingIssue(
                    code="commonforms.failed",
                    message=f"AcroForm generation failed: {exc}",
                    severity=IssueSeverity.ERROR,
                )
            )
            return GenerationResult(
                output_path=output_path,
                issues=issues,
                confidence=0.0,
            )

        layout_validation = validate_field_layout(analysis.detected_fields, acro_fields, mappings)
        if layout_validation.low_alignment_fields:
            issues.append(
                ProcessingIssue(
                    code="acroform.layout.low_alignment",
                    message=(
                        f"{len(layout_validation.low_alignment_fields)} field(s) have weak widget alignment."
                    ),
                    severity=IssueSeverity.WARNING,
                    context={
                        "fields": ", ".join(layout_validation.low_alignment_fields[:8]),
                        "mean_iou": f"{layout_validation.mean_iou:.3f}",
                    },
                )
            )
        if layout_validation.overlap_pair_count:
            issues.append(
                ProcessingIssue(
                    code="acroform.layout.overlap_detected",
                    message="Generated widget rectangles overlap and should be reviewed.",
                    severity=IssueSeverity.WARNING,
                    context={"overlap_pair_count": str(layout_validation.overlap_pair_count)},
                )
            )
        if layout_validation.tiny_fields:
            issues.append(
                ProcessingIssue(
                    code="acroform.layout.tiny_fields",
                    message="Some generated widgets are too small for reliable interaction.",
                    severity=IssueSeverity.WARNING,
                    context={"fields": ", ".join(layout_validation.tiny_fields[:8])},
                )
            )
        if layout_validation.row_misaligned_fields:
            issues.append(
                ProcessingIssue(
                    code="acroform.layout.row_misaligned",
                    message="Some generated widgets drift onto the wrong text row.",
                    severity=IssueSeverity.WARNING,
                    context={"fields": ", ".join(layout_validation.row_misaligned_fields[:8])},
                )
            )
        if layout_validation.early_start_fields:
            issues.append(
                ProcessingIssue(
                    code="acroform.layout.anchor_overlap_risk",
                    message="Some generated widgets start before the expected anchor and may overlap labels.",
                    severity=IssueSeverity.WARNING,
                    context={"fields": ", ".join(layout_validation.early_start_fields[:8])},
                )
            )
        if layout_validation.table_overflow_fields:
            issues.append(
                ProcessingIssue(
                    code="acroform.layout.table_overflow",
                    message="Some generated widgets extend beyond the detected region bounds.",
                    severity=IssueSeverity.WARNING,
                    context={"fields": ", ".join(layout_validation.table_overflow_fields[:8])},
                )
            )

        return GenerationResult(
            output_path=output_path,
            acro_fields=acro_fields,
            rename_map=rename_map,
            mappings=mappings,
            issues=issues,
            confidence=average_confidence(
                [analysis.confidence, confidence, layout_validation.geometry_score]
            ),
        )
