from __future__ import annotations

from formai.artifacts import FieldDetectionArtifact, TemplateIdentityArtifact, TemplateLayoutArtifact


def analyze_template_layout(pdf_path, layout_engine) -> TemplateLayoutArtifact:
    structure = layout_engine.analyze_template(pdf_path)
    summary = structure.summary() if hasattr(structure, "summary") else {}
    if getattr(layout_engine, "_load_error", None):
        summary = {
            **summary,
            "layout_backend_error": getattr(layout_engine, "_load_error", None),
        }
    return TemplateLayoutArtifact(
        source_path=pdf_path,
        template_structure=structure,
        summary=summary,
    )


def infer_template_identity(analysis) -> TemplateIdentityArtifact:
    summary = (
        f"{analysis.document_identity.document_family.value} | "
        f"{analysis.document_identity.profile}"
    )
    return TemplateIdentityArtifact(
        source_path=analysis.source_path,
        document_identity=analysis.document_identity,
        summary=summary,
    )


def detect_template_fields(analysis, layout: TemplateLayoutArtifact | None = None) -> FieldDetectionArtifact:
    confidence = analysis.confidence
    issues = list(analysis.issues)
    if layout is not None and layout.template_structure is not None:
        if getattr(layout.template_structure, "table_cells", None):
            confidence = min(1.0, confidence + 0.03)
        if layout.summary.get("layout_backend_error"):
            confidence = max(0.0, confidence - 0.05)
    return FieldDetectionArtifact(
        source_path=analysis.source_path,
        detected_fields=list(analysis.detected_fields),
        confidence=confidence,
        issues=issues,
    )
