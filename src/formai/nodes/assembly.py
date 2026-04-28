from __future__ import annotations

from formai.artifacts import RenderPlanArtifact


def build_render_plan_artifact(render_plan) -> RenderPlanArtifact:
    return RenderPlanArtifact(
        items=list(getattr(render_plan, "items", []) or []),
        summary=render_plan.to_dict() if hasattr(render_plan, "to_dict") else {},
    )
