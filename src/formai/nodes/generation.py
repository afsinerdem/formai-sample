from __future__ import annotations

from formai.artifacts import FillablePdfArtifact, LayoutValidationArtifact, RenameArtifact


def normalize_field_names(analysis) -> RenameArtifact:
    rename_map = {
        review.current_name: review.recommended_name
        for review in getattr(analysis, "field_name_reviews", [])
        if not review.is_valid and review.current_name != review.recommended_name
    }
    return RenameArtifact(
        rename_map=rename_map,
        field_name_reviews=[review.__dict__ for review in getattr(analysis, "field_name_reviews", [])],
    )


def to_fillable_artifact(generation) -> FillablePdfArtifact:
    return FillablePdfArtifact(
        output_path=generation.output_path,
        acro_fields=list(generation.acro_fields),
        mappings=list(generation.mappings),
        rename_map=dict(generation.rename_map),
        confidence=generation.confidence,
        issues=list(generation.issues),
    )


def to_layout_validation_artifact(generation) -> LayoutValidationArtifact:
    issue_codes = [issue.code for issue in generation.issues]
    return LayoutValidationArtifact(
        summary={
            "issue_codes": issue_codes,
            "mapping_count": len(generation.mappings),
            "acro_field_count": len(generation.acro_fields),
        },
        issues=list(generation.issues),
        confidence=generation.confidence,
    )
