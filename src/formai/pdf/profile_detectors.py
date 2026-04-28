from __future__ import annotations

from pathlib import Path
from typing import List

from formai.models import DetectedField, DocumentFamily, DocumentIdentity, DocumentLanguage
from formai.pdf.student_petition_detector import detect_student_petition_fields


def detect_fields_for_identity(pdf_path: Path, identity: DocumentIdentity) -> List[DetectedField]:
    if identity.document_family == DocumentFamily.STUDENT_PETITION and identity.language in {
        DocumentLanguage.TR,
        DocumentLanguage.MIXED,
    }:
        return detect_student_petition_fields(pdf_path)
    return []
