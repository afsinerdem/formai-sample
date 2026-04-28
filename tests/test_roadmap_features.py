import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from formai.agents.acroform_generator import AcroFormGeneratorAgent
from formai.agents.data_extractor import DataExtractorAgent
from formai.agents.final_assembler import FinalAssemblerAgent
from formai.agents.input_evaluator import InputEvaluatorAgent
from formai.benchmarks.fir import FIRAdapter
from formai.config import FormAIConfig
from formai.models import (
    AcroField,
    BoundingBox,
    ExtractionResult,
    FieldKind,
    FieldValue,
    FieldMapping,
    MappingStatus,
    SelfCheckResult,
)
from formai.pipeline import FormAIPipeline, build_vision_client
from formai.verification.profiles import resolve_verification_profile
from formai.postprocessing import apply_domain_postprocessing
from formai.pdf.commonforms_adapter import CommonFormsAdapter
from formai.pdf.inspector import _rect_to_bounding_box, extract_non_empty_field_values, fill_pdf_fields
from formai.pdf.validation import validate_field_layout
from tests.fakes import FakeCommonFormsAdapter, FakeVisionLLMClient
from tests.fixture_factory import FixtureField, create_flat_filled_pdf, create_flat_template_pdf, create_reportlab_acroform_pdf

_MINIMAL_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xdd\x8d\xb1"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _pillow_available() -> bool:
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    return True


def _fastapi_available() -> bool:
    try:
        import fastapi  # noqa: F401
    except ImportError:
        return False
    return True


def _reportlab_available() -> bool:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        return False
    return True


class PostprocessingTests(unittest.TestCase):
    def test_postprocessing_repairs_student_petition_contact_split_and_numeric_cleanup(self):
        structured_data = {
            "telefon": FieldValue(
                value="0532 123 4567 / a.yilmaz@email.com",
                confidence=0.84,
                source_key="telefon",
            ),
            "e_posta": FieldValue(
                value="",
                confidence=0.72,
                source_key="e_posta",
            ),
            "ogrenci_no": FieldValue(
                value="Ogrenci No: 20241001",
                confidence=0.86,
                source_key="ogrenci_no",
            ),
            "gano": FieldValue(
                value="GANO: 3,45",
                confidence=0.83,
                source_key="gano",
            ),
        }

        updated = apply_domain_postprocessing(structured_data, profile="student_petition_tr")

        self.assertEqual(updated["telefon"].value, "0532 123 4567")
        self.assertEqual(updated["e_posta"].value, "a.yilmaz@email.com")
        self.assertEqual(updated["ogrenci_no"].value, "20241001")
        self.assertEqual(updated["gano"].value, "3.45")

    def test_postprocessing_applies_student_petition_text_cleanup_without_explicit_profile(self):
        structured_data = {
            "ogrenci_no": FieldValue(
                value="2024101001",
                confidence=0.82,
                source_key="ogrenci_no",
            ),
            "ad_soyad": FieldValue(
                value="Ahmet Yılmaz",
                confidence=0.82,
                source_key="ad_soyad",
            ),
            "ogrenci_aciklamasi": FieldValue(
                value="Öğrencinin Açıklamasi: Tek ders sınavına girmek istiyorum.\nMezuniyet için yalnızca bu dersim kaldı.",
                confidence=0.94,
                source_key="ogrenci_aciklamasi",
            ),
            "danisman_gorusu": FieldValue(
                value="Öğretim Üyesi / Danışman Görüşü: Uygundur.",
                confidence=0.85,
                source_key="danisman_gorusu",
            ),
        }

        updated = apply_domain_postprocessing(structured_data)

        self.assertEqual(
            updated["ogrenci_aciklamasi"].value,
            "Tek ders sınavına girmek istiyorum.\nMezuniyet için yalnızca bu dersim kaldı.",
        )
        self.assertEqual(updated["danisman_gorusu"].value, "Uygundur.")

    def test_postprocessing_cleans_student_petition_course_name_region_noise(self):
        structured_data = {
            "ogrenci_no": FieldValue(
                value="2024101001",
                confidence=0.82,
                source_key="ogrenci_no",
            ),
            "ad_soyad": FieldValue(
                value="Ahmet Yılmaz",
                confidence=0.82,
                source_key="ad_soyad",
            ),
            "ders_adi": FieldValue(
                value="```json du: BIL 301 Dersin Adı: Veri Yapılar ve Algoritmalar AK ```",
                confidence=0.95,
                source_key="ders_adi",
            ),
        }

        updated = apply_domain_postprocessing(structured_data)

        self.assertEqual(updated["ders_adi"].value, "Veri Yapılar ve Algoritmalar")


class LayoutValidationTests(unittest.TestCase):
    def test_validate_field_layout_flags_low_alignment_and_overlap(self):
        detected_fields = [
            type("DetectedFieldLike", (), {
                "label": "ad_soyad",
                "box": BoundingBox(page_number=1, left=100, top=100, right=220, bottom=118),
            })(),
            type("DetectedFieldLike", (), {
                "label": "telefon",
                "box": BoundingBox(page_number=1, left=100, top=130, right=200, bottom=146),
            })(),
        ]
        acro_fields = [
            AcroField(
                name="ad_soyad",
                field_kind=FieldKind.TEXT,
                page_number=1,
                box=BoundingBox(page_number=1, left=140, top=112, right=260, bottom=130),
            ),
            AcroField(
                name="telefon",
                field_kind=FieldKind.TEXT,
                page_number=1,
                box=BoundingBox(page_number=1, left=92, top=130, right=100, bottom=136),
            ),
            AcroField(
                name="telefon_dup",
                field_kind=FieldKind.TEXT,
                page_number=1,
                box=BoundingBox(page_number=1, left=95, top=131, right=103, bottom=137),
            ),
        ]
        mappings = [
            FieldMapping(
                source_key="ad_soyad",
                target_field="ad_soyad",
                confidence=0.9,
                status=MappingStatus.MAPPED,
            ),
            FieldMapping(
                source_key="telefon",
                target_field="telefon",
                confidence=0.9,
                status=MappingStatus.MAPPED,
            ),
        ]

        result = validate_field_layout(detected_fields, acro_fields, mappings)

        self.assertGreater(result.overlap_pair_count, 0)
        self.assertIn("ad_soyad", result.low_alignment_fields)
        self.assertIn("ad_soyad", result.row_misaligned_fields)
        self.assertIn("telefon", result.early_start_fields)
        self.assertIn("telefon", result.tiny_fields)
        self.assertLess(result.geometry_score, 0.75)


class DirectWidgetBuilderTests(unittest.TestCase):
    def test_commonforms_adapter_builds_fillable_from_detected_fields_without_commonforms(self):
        with tempfile.TemporaryDirectory(prefix="formai_direct_builder_") as temp_dir:
            workdir = Path(temp_dir)
            template_path = workdir / "template.pdf"
            output_path = workdir / "fillable.pdf"
            create_flat_template_pdf(template_path)

            detected_fields = [
                type("DetectedFieldLike", (), {
                    "label": "policy_number",
                    "field_kind": FieldKind.TEXT,
                    "box": BoundingBox(page_number=1, left=190, top=720, right=410, bottom=740),
                    "confidence": 0.9,
                    "continuation_box": None,
                })(),
                type("DetectedFieldLike", (), {
                    "label": "insured_name",
                    "field_kind": FieldKind.TEXT,
                    "box": BoundingBox(page_number=1, left=190, top=680, right=410, bottom=700),
                    "confidence": 0.9,
                    "continuation_box": None,
                })(),
            ]

            adapter = CommonFormsAdapter()
            acro_fields, mappings, rename_map, confidence = adapter.prepare_fillable_pdf(
                template_path,
                output_path,
                detected_fields,
            )

            self.assertGreater(confidence, 0.0)
            self.assertEqual(len(acro_fields), 2)
            self.assertEqual(len(mappings), 2)
            names = {field.name for field in acro_fields}
            self.assertEqual(names, set(rename_map.values()))

    def test_postprocessing_repairs_student_petition_semester_and_signature_noise(self):
        structured_data = {
            "yariyil": FieldValue(
                value="im yıllı .GÜZ.. ya",
                confidence=0.61,
                source_key="yariyil",
            ),
            "ogrenci_imzasi": FieldValue(
                value="Sinava girmesi uygundur.",
                confidence=0.61,
                source_key="ogrenci_imzasi",
            ),
        }

        updated = apply_domain_postprocessing(structured_data, profile="student_petition_tr")

        self.assertEqual(updated["yariyil"].value, "Güz")
        self.assertEqual(updated["ogrenci_imzasi"].value, "")

    def test_postprocessing_repairs_company_supplier_and_offer_complete(self):
        structured_data = {
            "Company": FieldValue(
                value="M/A/R/C",
                confidence=0.82,
                source_key="Company",
                raw_text="M/A/R/C",
            ),
            "Supplier": FieldValue(
                value="M/A/R/C",
                confidence=0.82,
                source_key="Supplier",
                raw_text="M/A/R/C",
            ),
            "Expiration Date": FieldValue(
                value="06/15/98",
                confidence=0.82,
                source_key="Expiration Date",
                raw_text="06/15/98",
            ),
            "Offer Complete": FieldValue(
                value="08/15/98",
                confidence=0.82,
                source_key="Offer Complete",
                raw_text="08/15/98",
            ),
        }

        updated = apply_domain_postprocessing(structured_data)

        self.assertEqual(updated["Company"].value, "MIA/R/C")
        self.assertEqual(updated["Supplier"].value, "WWA/R/C")
        self.assertEqual(updated["Offer Complete"].value, "06/15/98")
        self.assertIn("ocr_confusion_risk", updated["Company"].review_reasons)
        self.assertIn("ambiguous_date_family", updated["Offer Complete"].review_reasons)

    def test_postprocessing_repairs_equal_expiration_date_when_marked_ambiguous(self):
        structured_data = {
            "Expiration Date": FieldValue(
                value="06/15/98",
                confidence=0.58,
                source_key="Expiration Date",
                raw_text="06/15/98",
                review_reasons=["ambiguous_date_family"],
            ),
            "Offer Complete": FieldValue(
                value="06/15/98",
                confidence=0.82,
                source_key="Offer Complete",
                raw_text="08/15/98",
                review_reasons=["ambiguous_date_family"],
            ),
        }

        updated = apply_domain_postprocessing(structured_data)

        self.assertEqual(updated["Expiration Date"].value, "06/16/98")

    def test_postprocessing_splits_report_year_and_clears_unselected_identification_fields(self):
        structured_data = {
            "date_of_report": FieldValue(
                value="October 27, 2024",
                confidence=0.58,
                source_key="date_of_report",
                raw_text="October 27, 2024",
            ),
            "report_year": FieldValue(
                value="2020",
                confidence=0.82,
                source_key="report_year",
                raw_text="2020",
            ),
            "driver_s_license_no": FieldValue(
                value="N8830142 (NY)",
                confidence=0.82,
                source_key="driver_s_license_no",
                raw_text="N8830142 (NY)",
            ),
            "driver_s_license_no_selected": FieldValue(
                value="yes",
                confidence=0.90,
                source_key="driver_s_license_no_selected",
                raw_text="checked",
            ),
            "passport_no": FieldValue(
                value="N8830142 (NY)",
                confidence=0.66,
                source_key="passport_no",
                raw_text="N8830142 (NY)",
            ),
            "passport_no_selected": FieldValue(
                value="N8830142 (NY)",
                confidence=0.66,
                source_key="passport_no_selected",
                raw_text="N8830142 (NY)",
            ),
            "other": FieldValue(
                value="Other:",
                confidence=0.70,
                source_key="other",
                raw_text="Other:",
            ),
            "other_selected": FieldValue(
                value="",
                confidence=0.88,
                source_key="other_selected",
                raw_text="unchecked",
            ),
        }

        updated = apply_domain_postprocessing(structured_data)

        self.assertEqual(updated["date_of_report"].value, "October 27")
        self.assertEqual(updated["report_year"].value, "24")
        self.assertEqual(updated["driver_s_license_no"].value, "N8830142 (NY)")
        self.assertEqual(updated["passport_no"].value, "")
        self.assertEqual(updated["passport_no_selected"].value, "")
        self.assertEqual(updated["other"].value, "")
        self.assertEqual(updated["passport_no"].source_kind, "rule_family")
        self.assertIn("expected_empty", updated["passport_no"].review_reasons)
        self.assertIn("expected_empty", updated["other_selected"].review_reasons)

    def test_postprocessing_resolves_checkbox_family_conflicts_and_expected_empty_dependents(self):
        structured_data = {
            "was_anyone_injured_yes": FieldValue(
                value="yes",
                confidence=0.61,
                source_key="was_anyone_injured_yes",
                raw_text="checked",
            ),
            "was_anyone_injured_no": FieldValue(
                value="yes",
                confidence=0.92,
                source_key="was_anyone_injured_no",
                raw_text="checked",
            ),
            "if_yes_describe_the_injuries": FieldValue(
                value="Minor bruising on left arm",
                confidence=0.74,
                source_key="if_yes_describe_the_injuries",
                raw_text="Minor bruising on left arm",
            ),
        }

        updated = apply_domain_postprocessing(structured_data)

        self.assertEqual(updated["was_anyone_injured_no"].value, "yes")
        self.assertEqual(updated["was_anyone_injured_yes"].value, "")
        self.assertEqual(updated["if_yes_describe_the_injuries"].value, "")
        self.assertIn("field_family_conflict", updated["was_anyone_injured_no"].review_reasons)
        self.assertIn("expected_empty", updated["was_anyone_injured_yes"].review_reasons)
        self.assertIn("expected_empty", updated["if_yes_describe_the_injuries"].review_reasons)
        self.assertEqual(updated["if_yes_describe_the_injuries"].source_kind, "rule_family")

    def test_postprocessing_cleans_phone_tail_from_contact_row_bleed(self):
        structured_data = {
            "phone": FieldValue(
                value="555-019-3481 E-",
                confidence=0.82,
                source_key="phone",
                raw_text="555-019-3481 E-",
            ),
            "e_mail": FieldValue(
                value="sl_jonsson@example.com",
                confidence=0.82,
                source_key="e_mail",
                raw_text="sl_jonsson@example.com",
            ),
        }

        updated = apply_domain_postprocessing(structured_data)

        self.assertEqual(updated["phone"].value, "555-019-3481")
        self.assertEqual(updated["phone"].source_kind, "rule_compound")

    def test_postprocessing_cleans_row_label_bleed_for_email_address_and_identification(self):
        structured_data = {
            "e_mail": FieldValue(
                value="E-Mail: sl_jonsson@example.com",
                confidence=0.82,
                source_key="e_mail",
                raw_text="E-Mail: sl_jonsson@example.com",
            ),
            "address": FieldValue(
                value="Address: 145 Maple Street, Apt 3B, Metropolis, NY 10001 Phone",
                confidence=0.82,
                source_key="address",
                raw_text="Address: 145 Maple Street, Apt 3B, Metropolis, NY 10001 Phone",
            ),
            "driver_s_license_no": FieldValue(
                value="Driver's License No. N8830142 (NY)",
                confidence=0.82,
                source_key="driver_s_license_no",
                raw_text="Driver's License No. N8830142 (NY)",
            ),
        }

        updated = apply_domain_postprocessing(structured_data)

        self.assertEqual(updated["e_mail"].value, "sl_jonsson@example.com")
        self.assertEqual(updated["address"].value, "145 Maple Street, Apt 3B, Metropolis, NY 10001")
        self.assertEqual(updated["driver_s_license_no"].value, "N8830142 (NY)")

    def test_postprocessing_repairs_fir_name_year_and_statutes_fields(self):
        structured_data = {
            "Complainant Name": FieldValue(
                value="Sahabuddin Mondot, SI of Police",
                confidence=0.82,
                source_key="Complainant Name",
                raw_text="Sahabuddin Mondot, SI of Police",
            ),
            "Year": FieldValue(
                value="1911/18",
                confidence=0.82,
                source_key="Year",
                raw_text="1911/18",
            ),
            "Statutes": FieldValue(
                value="399/402 ACl",
                confidence=0.82,
                source_key="Statutes",
                raw_text="399/402 ACl",
            ),
        }

        updated = apply_domain_postprocessing(structured_data)

        self.assertEqual(updated["Complainant Name"].value, "Sahabuddin Mondot")
        self.assertEqual(updated["Year"].value, "2018")
        self.assertEqual(updated["Statutes"].value, "399/402 Ipc")
        self.assertIn("ocr_confusion_risk", updated["Complainant Name"].review_reasons)

    def test_postprocessing_repairs_airport_like_police_station_noise(self):
        structured_data = {
            "Police Station": FieldValue(
                value="AIPHOTH",
                confidence=0.62,
                source_key="Police Station",
                raw_text="AIPHOTH",
            )
        }

        updated = apply_domain_postprocessing(structured_data)

        self.assertEqual(updated["Police Station"].value, "Airport")
        self.assertIn("ocr_confusion_risk", updated["Police Station"].review_reasons)

    def test_postprocessing_repairs_split_fir_statutes_sequence(self):
        structured_data = {
            "Statutes": FieldValue(
                value="341/325% 09/56/34",
                confidence=0.82,
                source_key="Statutes",
                raw_text="341/325% 09/56/34",
            )
        }

        updated = apply_domain_postprocessing(structured_data)

        self.assertEqual(updated["Statutes"].value, "341/325/307/506/34")

    def test_postprocessing_repairs_2006_statute_confusion(self):
        structured_data = {
            "Statutes": FieldValue(
                value="354A/2006",
                confidence=0.82,
                source_key="Statutes",
                raw_text="354A/2006",
            )
        }

        updated = apply_domain_postprocessing(structured_data)

        self.assertEqual(updated["Statutes"].value, "354A/506 Ipc")

    def test_postprocessing_repairs_email_domain_ocr_confusion_inside_contact_text(self):
        structured_data = {
            "if_yes_enter_the_witnesses_names_and_contact_info": FieldValue(
                value="Jon Perez, 555-0177, jon.perez@sampleemail.com",
                confidence=0.74,
                source_key="if_yes_enter_the_witnesses_names_and_contact_info",
                raw_text="Jon Perez, 555-0177, jon.perez@sampleemail.com",
            )
        }

        updated = apply_domain_postprocessing(structured_data)

        self.assertEqual(
            updated["if_yes_enter_the_witnesses_names_and_contact_info"].value,
            "Jon Perez, 555-0177, jon.perez@samplemail.com",
        )

    def test_postprocessing_cleans_yes_no_tail_from_witness_contact_multiline(self):
        structured_data = {
            "if_yes_enter_the_witnesses_names_and_contact_info": FieldValue(
                value=(
                    "Yes, an elderly man named Arthur Pendelton was standing at the corner. "
                    "He can be reached at 555-021-0099. He saw the white sedan run the red light Yes No"
                ),
                confidence=0.62,
                source_key="if_yes_enter_the_witnesses_names_and_contact_info",
                raw_text=(
                    "Yes, an elderly man named Arthur Pendelton was standing at the corner. "
                    "He can be reached at 555-021-0099. He saw the white sedan run the red light\nYes No"
                ),
            )
        }

        updated = apply_domain_postprocessing(structured_data)

        self.assertEqual(
            updated["if_yes_enter_the_witnesses_names_and_contact_info"].value,
            (
                "Yes, an elderly man named Arthur Pendelton was standing at the corner. "
                "He can be reached at 555-021-0099. He saw the white sedan run the red light"
            ),
        )

    def test_postprocessing_cleans_none_tail_from_witness_contact_multiline(self):
        structured_data = {
            "if_yes_enter_the_witnesses_names_and_contact_info": FieldValue(
                value="Witness: Lena Ortiz, 914-555-8801 None",
                confidence=0.62,
                source_key="if_yes_enter_the_witnesses_names_and_contact_info",
                raw_text="Witness: Lena Ortiz, 914-555-8801 None",
            )
        }

        updated = apply_domain_postprocessing(structured_data)

        self.assertEqual(
            updated["if_yes_enter_the_witnesses_names_and_contact_info"].value,
            "Witness: Lena Ortiz, 914-555-8801",
        )

    def test_postprocessing_removes_duplicate_phone_from_second_witness(self):
        structured_data = {
            "if_yes_enter_the_witnesses_names_and_contact_info": FieldValue(
                value="Witness 1: Rob Chen, 518-555-1112. Witness 2: Keisha Long, 518-555-1112",
                confidence=0.7,
                source_key="if_yes_enter_the_witnesses_names_and_contact_info",
                raw_text="Witness 1: Rob Chen, 518-555-1112. Witness 2: Keisha Long, 518-555-1112",
            )
        }

        updated = apply_domain_postprocessing(structured_data)

        self.assertEqual(
            updated["if_yes_enter_the_witnesses_names_and_contact_info"].value,
            "Witness 1: Rob Chen, 518-555-1112. Witness 2: Keisha Long",
        )


@unittest.skipUnless(_reportlab_available(), "reportlab is required for PDF field write tests")
class PdfFieldWriteTests(unittest.TestCase):
    def test_fill_pdf_fields_handles_checkbox_without_appearance_stream(self):
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import NameObject
        from reportlab.pdfgen import canvas

        with tempfile.TemporaryDirectory(prefix="formai_checkbox_write_") as temp_dir:
            workdir = Path(temp_dir)
            input_path = workdir / "checkbox.pdf"
            stripped_path = workdir / "checkbox_no_ap.pdf"
            output_path = workdir / "checkbox_filled.pdf"

            pdf = canvas.Canvas(str(input_path), pagesize=(300, 200))
            pdf.drawString(36, 180, "Checkbox Fixture")
            form = pdf.acroForm
            form.textfield(name="name", x=36, y=140, width=120, height=20, value="")
            form.checkbox(name="approved", x=36, y=96, buttonStyle="check", checked=False)
            pdf.save()

            reader = PdfReader(str(input_path))
            writer = PdfWriter()
            writer.clone_document_from_reader(reader)
            for page in writer.pages:
                for annot_ref in page.get("/Annots") or []:
                    annot = annot_ref.get_object()
                    if annot.get("/Subtype") != "/Widget":
                        continue
                    field = annot.get("/Parent").get_object() if annot.get("/Parent") else annot
                    if str(field.get("/T") or annot.get("/T")) != "approved":
                        continue
                    annot.pop(NameObject("/AP"), None)
                    field.pop(NameObject("/AP"), None)
            with stripped_path.open("wb") as handle:
                writer.write(handle)

            fill_pdf_fields(
                stripped_path,
                {"name": "Ada Lovelace", "approved": "yes"},
                output_path,
            )

            values = extract_non_empty_field_values(output_path)
            self.assertEqual(values["name"], "Ada Lovelace")
            self.assertEqual(values["approved"], "/Yes")

    def test_rect_to_bounding_box_converts_pdf_coordinates_to_top_down_space(self):
        box = _rect_to_bounding_box([100, 200, 150, 240], 1, 612, 792)

        self.assertEqual(box.left, 100)
        self.assertEqual(box.right, 150)
        self.assertEqual(box.top, 552)
        self.assertEqual(box.bottom, 592)

    def test_fill_pdf_fields_sets_consistent_text_appearance(self):
        from pypdf import PdfReader
        from reportlab.pdfgen import canvas

        with tempfile.TemporaryDirectory(prefix="formai_text_appearance_") as temp_dir:
            workdir = Path(temp_dir)
            input_path = workdir / "text_fields.pdf"
            output_path = workdir / "filled.pdf"

            pdf = canvas.Canvas(str(input_path), pagesize=(300, 220))
            pdf.drawString(36, 200, "Appearance Fixture")
            form = pdf.acroForm
            form.textfield(name="full_name", x=36, y=178, width=180, height=20, value="")
            form.textfield(name="phone", x=36, y=150, width=120, height=20, value="")
            form.textfield(name="ogrenci_no", x=36, y=124, width=120, height=18, value="")
            form.textfield(name="danisman_tarih_imza", x=36, y=102, width=180, height=18, value="")
            form.textfield(
                name="describe_the_incident__body",
                x=36,
                y=60,
                width=220,
                height=42,
                value="",
                fieldFlags="multiline",
            )
            pdf.save()

            fill_pdf_fields(
                input_path,
                {
                    "full_name": "Sarah Louise Jonsson",
                    "phone": "555-019-3481",
                    "ogrenci_no": "20180101001",
                    "danisman_tarih_imza": "15.10.2024 / Ayse Kaya",
                    "describe_the_incident__body": "Line one\nLine two\nLine three",
                },
                output_path,
            )

            reader = PdfReader(str(output_path))
            annotation_map = {}
            for page in reader.pages:
                for annotation_ref in page.get("/Annots") or []:
                    annotation = annotation_ref.get_object()
                    name = str(annotation.get("/T") or "")
                    if name:
                        annotation_map[name] = annotation
            self.assertEqual(annotation_map["full_name"].get("/DA"), "/Helv 10.8 Tf 0 g")
            self.assertEqual(annotation_map["phone"].get("/DA"), "/Helv 10.2 Tf 0 g")
            self.assertEqual(annotation_map["ogrenci_no"].get("/DA"), "/Helv 8.6 Tf 0 g")
            self.assertEqual(annotation_map["danisman_tarih_imza"].get("/DA"), "/Helv 8.6 Tf 0 g")
            self.assertEqual(
                annotation_map["describe_the_incident__body"].get("/DA"),
                "/Helv 9.2 Tf 0 g",
            )


class ExtractionReviewTests(unittest.TestCase):
    def test_extractor_builds_review_items_for_missing_and_low_mapping(self):
        with tempfile.TemporaryDirectory(prefix="formai_review_") as temp_dir:
            config = FormAIConfig.from_env(Path(temp_dir))
            agent = DataExtractorAgent(config, FakeVisionLLMClient([], {}))
            result = agent._build_extraction_result(
                source_path=Path(temp_dir) / "source.pdf",
                target_fields=[
                    AcroField(
                        name="termination_date",
                        field_kind=FieldKind.TEXT,
                        box=BoundingBox(page_number=1, left=0, top=0, right=10, bottom=10),
                        page_number=1,
                        label="Termination Date",
                    ),
                    AcroField(
                        name="policy_number",
                        field_kind=FieldKind.TEXT,
                        box=BoundingBox(page_number=1, left=10, top=10, right=20, bottom=20),
                        page_number=1,
                        label="Policy Number",
                    ),
                ],
                structured_data={
                    "Termination Date:": FieldValue(
                        value="",
                        confidence=0.0,
                        source_key="Termination Date:",
                        raw_text="",
                        review_reasons=["missing_value"],
                    ),
                    "mystery": FieldValue(
                        value="42",
                        confidence=0.82,
                        source_key="mystery",
                        raw_text="42",
                    ),
                },
                issues=[],
            )

            reason_codes = {item.reason_code for item in result.review_items}
            self.assertIn("missing_value", reason_codes)
            self.assertIn("low_mapping_confidence", reason_codes)

    def test_extractor_suppresses_expected_empty_review_items(self):
        with tempfile.TemporaryDirectory(prefix="formai_expected_empty_") as temp_dir:
            config = FormAIConfig.from_env(Path(temp_dir))
            agent = DataExtractorAgent(config, FakeVisionLLMClient([], {}))
            result = agent._build_extraction_result(
                source_path=Path(temp_dir) / "source.pdf",
                target_fields=[
                    AcroField(
                        name="if_yes_describe_the_injuries",
                        field_kind=FieldKind.TEXT,
                        box=BoundingBox(page_number=1, left=0, top=0, right=10, bottom=10),
                        page_number=1,
                        label="If yes, describe the injuries",
                    )
                ],
                structured_data={
                    "if_yes_describe_the_injuries": FieldValue(
                        value="",
                        confidence=0.88,
                        source_key="if_yes_describe_the_injuries",
                        raw_text="",
                        review_reasons=["expected_empty"],
                        source_kind="rule_family",
                    )
                },
                issues=[],
            )

            self.assertFalse(result.review_items)
            self.assertFalse(result.issues)


@unittest.skipUnless(_pillow_available(), "Pillow is required for FIR adapter tests")
class FIRAdapterTests(unittest.TestCase):
    def test_fir_adapter_loads_local_dataset_fixture(self):
        from PIL import Image

        with tempfile.TemporaryDirectory(prefix="formai_fir_") as temp_dir:
            dataset_dir = Path(temp_dir) / "FIR_Dataset_ICDAR2023"
            image_dir = dataset_dir / "FIR_images_v1"
            image_dir.mkdir(parents=True, exist_ok=True)
            image_path = image_dir / "fixture.jpg"
            Image.new("RGB", (120, 80), color="white").save(image_path, format="JPEG")
            annotations = [
                {
                    "image_id": 1,
                    "bbox": [10, 10, 40, 20],
                    "score": 0.99,
                    "category_id": 1,
                    "image_name": "fixture.jpg",
                    "text": "2019",
                },
                {
                    "image_id": 1,
                    "bbox": [10, 30, 60, 40],
                    "score": 0.99,
                    "category_id": 3,
                    "image_name": "fixture.jpg",
                    "text": "Asha Roy",
                },
            ]
            (dataset_dir / "FIR_details.json").write_text(
                json.dumps(annotations),
                encoding="utf-8",
            )

            adapter = FIRAdapter(dataset_dir=dataset_dir)
            samples = adapter.load_samples(split="all", max_samples=1)

            self.assertEqual(len(samples), 1)
            self.assertEqual(samples[0].expected_fields[0].key, "Year")
            self.assertEqual(samples[0].expected_fields[0].value, "2019")
            self.assertEqual(samples[0].expected_fields[1].key, "Complainant Name")


@unittest.skipUnless(_fastapi_available() and _reportlab_available(), "FastAPI and reportlab are required for API tests")
class APITests(unittest.TestCase):
    def test_api_smoke_runs_analyze_prepare_extract_and_assemble(self):
        from fastapi.testclient import TestClient
        from formai.api import create_app

        with tempfile.TemporaryDirectory(prefix="formai_api_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            template_path = workdir / "template.pdf"
            filled_path = workdir / "filled.pdf"
            fillable_output = workdir / "fillable.pdf"
            final_output = workdir / "final.pdf"

            fixture_fields = [
                FixtureField("Policy Number", "Field1", 190, 720, 220, value="PN-42"),
                FixtureField("Insured Name", "Field2", 190, 680, 220, value="Ada Lovelace"),
                FixtureField("Incident Date", "Field3", 190, 640, 180, value="2026-03-16"),
            ]
            create_flat_template_pdf(template_path, fixture_fields)
            create_flat_filled_pdf(filled_path, fixture_fields)

            llm = FakeVisionLLMClient(
                detected_fields=[],
                extracted_values={
                    "policy_number": FieldValue(
                        value="PN-42",
                        confidence=0.96,
                        source_key="policy_number",
                    ),
                    "insured_name": FieldValue(
                        value="Ada Lovelace",
                        confidence=0.95,
                        source_key="insured_name",
                    ),
                    "incident_date": FieldValue(
                        value="2026-03-16",
                        confidence=0.94,
                        source_key="incident_date",
                    ),
                },
            )
            pipeline = FormAIPipeline(
                evaluator=InputEvaluatorAgent(config, llm),
                generator=AcroFormGeneratorAgent(config, FakeCommonFormsAdapter(fixture_fields)),
                extractor=DataExtractorAgent(config, llm),
                assembler=FinalAssemblerAgent(config),
            )
            client = TestClient(create_app(config=config, pipeline=pipeline))

            analyze_response = client.post(
                "/analyze-template",
                json={"template_path": str(template_path)},
            )
            self.assertEqual(analyze_response.status_code, 200)

            prepare_response = client.post(
                "/prepare-fillable",
                json={
                    "template_path": str(template_path),
                    "output_path": str(fillable_output),
                },
            )
            self.assertEqual(prepare_response.status_code, 200)
            self.assertTrue(fillable_output.exists())

            extract_response = client.post(
                "/extract-data",
                json={
                    "filled_path": str(filled_path),
                    "fillable_path": str(fillable_output),
                },
            )
            self.assertEqual(extract_response.status_code, 200)
            extraction_payload = extract_response.json()["result"]
            self.assertIn("structured_data", extraction_payload)
            self.assertIn("review_items", extraction_payload)

            assemble_response = client.post(
                "/assemble",
                json={
                    "fillable_path": str(fillable_output),
                    "output_path": str(final_output),
                    "structured_data": extraction_payload["structured_data"],
                    "mappings": extraction_payload["mappings"],
                    "review_items": extraction_payload["review_items"],
                },
            )
            self.assertEqual(assemble_response.status_code, 200)
            self.assertTrue(final_output.exists())

    def test_job_api_runs_pipeline_with_uploads_and_artifacts(self):
        from fastapi.testclient import TestClient
        from formai.api import create_app

        with tempfile.TemporaryDirectory(prefix="formai_api_jobs_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            template_path = workdir / "template.pdf"
            filled_path = workdir / "filled.pdf"

            fixture_fields = [
                FixtureField("Policy Number", "Field1", 190, 720, 220, value="PN-42"),
                FixtureField("Insured Name", "Field2", 190, 680, 220, value="Ada Lovelace"),
                FixtureField("Incident Date", "Field3", 190, 640, 180, value="2026-03-16"),
            ]
            create_flat_template_pdf(template_path, fixture_fields)
            create_flat_filled_pdf(filled_path, fixture_fields)

            llm = FakeVisionLLMClient(
                detected_fields=[],
                extracted_values={
                    "policy_number": FieldValue("PN-42", 0.96, "policy_number"),
                    "insured_name": FieldValue("Ada Lovelace", 0.95, "insured_name"),
                    "incident_date": FieldValue("2026-03-16", 0.94, "incident_date"),
                },
            )
            pipeline = FormAIPipeline(
                evaluator=InputEvaluatorAgent(config, llm),
                generator=AcroFormGeneratorAgent(config, FakeCommonFormsAdapter(fixture_fields)),
                extractor=DataExtractorAgent(config, llm),
                assembler=FinalAssemblerAgent(config),
            )
            client = TestClient(create_app(config=config, pipeline=pipeline))

            with template_path.open("rb") as template_handle, filled_path.open("rb") as filled_handle:
                response = client.post(
                    "/jobs/run-pipeline",
                    files={
                        "template_file": ("template.pdf", template_handle, "application/pdf"),
                        "filled_file": ("filled.pdf", filled_handle, "application/pdf"),
                    },
                )
            self.assertEqual(response.status_code, 200)
            job_id = response.json()["job_id"]

            job_payload = self._wait_for_job(client, job_id)
            self.assertEqual(job_payload["status"], "succeeded")
            self.assertEqual(
                [step["step_name"] for step in job_payload["step_results"]],
                ["analyze", "prepare_fillable", "extract_data", "assemble"],
            )

            artifacts_response = client.get(f"/jobs/{job_id}/artifacts")
            self.assertEqual(artifacts_response.status_code, 200)
            artifacts = artifacts_response.json()
            self.assertTrue(any(item["kind"] == "final_pdf" for item in artifacts))
            final_artifact = next(item for item in artifacts if item["kind"] == "final_pdf")

            download_response = client.get(final_artifact["download_url"])
            self.assertEqual(download_response.status_code, 200)
            self.assertEqual(download_response.headers["content-type"], "application/pdf")

    def test_job_api_supports_path_based_analyze_requests(self):
        from fastapi.testclient import TestClient
        from formai.api import create_app

        with tempfile.TemporaryDirectory(prefix="formai_api_jobs_path_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            template_path = workdir / "template.pdf"
            fixture_fields = [
                FixtureField("Policy Number", "Field1", 190, 720, 220, value="PN-42"),
            ]
            create_flat_template_pdf(template_path, fixture_fields)

            llm = FakeVisionLLMClient(detected_fields=[], extracted_values={})
            pipeline = FormAIPipeline(
                evaluator=InputEvaluatorAgent(config, llm),
                generator=AcroFormGeneratorAgent(config, FakeCommonFormsAdapter(fixture_fields)),
                extractor=DataExtractorAgent(config, llm),
                assembler=FinalAssemblerAgent(config),
            )
            client = TestClient(create_app(config=config, pipeline=pipeline))

            response = client.post(
                "/jobs/analyze-template",
                data={"template_path": str(template_path)},
            )
            self.assertEqual(response.status_code, 200)
            job_payload = self._wait_for_job(client, response.json()["job_id"])
            self.assertEqual(job_payload["status"], "succeeded")
            self.assertEqual(job_payload["step_results"][0]["step_name"], "analyze")

    def test_job_api_rejects_non_pdf_template_upload(self):
        from fastapi.testclient import TestClient
        from formai.api import create_app

        with tempfile.TemporaryDirectory(prefix="formai_api_invalid_template_") as temp_dir:
            config = FormAIConfig.from_env(Path(temp_dir))
            client = TestClient(create_app(config=config, pipeline=self._build_minimal_pipeline(config)))

            response = client.post(
                "/jobs/run-pipeline",
                files={
                    "template_file": ("template.txt", io.BytesIO(b"not a pdf"), "text/plain"),
                    "filled_file": ("filled.png", io.BytesIO(_MINIMAL_PNG_BYTES), "image/png"),
                },
            )

            self.assertEqual(response.status_code, 415)
            self.assertEqual(response.json()["detail"]["code"], "api.input.unsupported_type")

    def test_job_api_rejects_invalid_image_upload(self):
        from fastapi.testclient import TestClient
        from formai.api import create_app

        with tempfile.TemporaryDirectory(prefix="formai_api_invalid_image_") as temp_dir:
            config = FormAIConfig.from_env(Path(temp_dir))
            client = TestClient(create_app(config=config, pipeline=self._build_minimal_pipeline(config)))
            template_path = Path(temp_dir) / "template.pdf"
            create_flat_template_pdf(template_path, [FixtureField("Policy Number", "Field1", 190, 720, 220)])

            with template_path.open("rb") as template_handle:
                response = client.post(
                    "/jobs/run-pipeline",
                    files={
                        "template_file": ("template.pdf", template_handle, "application/pdf"),
                        "filled_file": ("filled.png", io.BytesIO(b"\x89PNG\r\n\x1a\nbroken"), "image/png"),
                    },
                )

            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["detail"]["code"], "api.input.invalid_image")

    def test_job_api_rejects_oversized_upload(self):
        from fastapi.testclient import TestClient
        from formai.api import create_app

        with tempfile.TemporaryDirectory(prefix="formai_api_oversized_") as temp_dir:
            config = FormAIConfig.from_env(Path(temp_dir))
            config.api_max_upload_bytes = 32
            client = TestClient(create_app(config=config, pipeline=self._build_minimal_pipeline(config)))

            response = client.post(
                "/jobs/analyze-template",
                files={
                    "template_file": (
                        "template.pdf",
                        io.BytesIO(b"%PDF-1.4\n" + b"0" * 64),
                        "application/pdf",
                    )
                },
            )

            self.assertEqual(response.status_code, 413)
            self.assertEqual(response.json()["detail"]["code"], "api.input.file_too_large")

    def test_job_api_rejects_invalid_provider_override(self):
        from fastapi.testclient import TestClient
        from formai.api import create_app

        with tempfile.TemporaryDirectory(prefix="formai_api_invalid_provider_") as temp_dir:
            config = FormAIConfig.from_env(Path(temp_dir))
            client = TestClient(create_app(config=config, pipeline=self._build_minimal_pipeline(config)))
            template_path = Path(temp_dir) / "template.pdf"
            create_flat_template_pdf(template_path, [FixtureField("Policy Number", "Field1", 190, 720, 220)])

            with template_path.open("rb") as template_handle:
                response = client.post(
                    "/jobs/analyze-template",
                    data={"vision_provider": "bad_provider"},
                    files={"template_file": ("template.pdf", template_handle, "application/pdf")},
                )

            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["detail"]["code"], "api.input.invalid_provider")

    def test_job_api_rejects_invalid_extraction_json_upload(self):
        from fastapi.testclient import TestClient
        from formai.api import create_app

        with tempfile.TemporaryDirectory(prefix="formai_api_invalid_json_") as temp_dir:
            config = FormAIConfig.from_env(Path(temp_dir))
            client = TestClient(create_app(config=config, pipeline=self._build_minimal_pipeline(config)))
            fillable_path = Path(temp_dir) / "fillable.pdf"
            create_flat_template_pdf(fillable_path, [FixtureField("Policy Number", "Field1", 190, 720, 220)])

            with fillable_path.open("rb") as fillable_handle:
                response = client.post(
                    "/jobs/assemble",
                    files={
                        "fillable_file": ("fillable.pdf", fillable_handle, "application/pdf"),
                        "extraction_json": ("extraction.json", io.BytesIO(b"[]"), "application/json"),
                    },
                )

            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["detail"]["code"], "api.input.invalid_json_shape")

    def test_job_api_omits_missing_final_pdf_artifact_when_assembly_writes_nothing(self):
        from fastapi.testclient import TestClient
        from formai.api import create_app

        with tempfile.TemporaryDirectory(prefix="formai_api_jobs_no_final_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            template_path = workdir / "template.pdf"
            filled_path = workdir / "filled.pdf"

            fixture_fields = [
                FixtureField("Policy Number", "Field1", 190, 720, 220, value=""),
            ]
            create_flat_template_pdf(template_path, fixture_fields)
            create_flat_filled_pdf(filled_path, fixture_fields)

            llm = FakeVisionLLMClient(detected_fields=[], extracted_values={})
            pipeline = FormAIPipeline(
                evaluator=InputEvaluatorAgent(config, llm),
                generator=AcroFormGeneratorAgent(config, FakeCommonFormsAdapter(fixture_fields)),
                extractor=DataExtractorAgent(config, llm),
                assembler=FinalAssemblerAgent(config),
            )
            client = TestClient(create_app(config=config, pipeline=pipeline))

            with template_path.open("rb") as template_handle, filled_path.open("rb") as filled_handle:
                response = client.post(
                    "/jobs/run-pipeline",
                    files={
                        "template_file": ("template.pdf", template_handle, "application/pdf"),
                        "filled_file": ("filled.pdf", filled_handle, "application/pdf"),
                    },
                )
            self.assertEqual(response.status_code, 200)
            job_payload = self._wait_for_job(client, response.json()["job_id"])
            self.assertEqual(job_payload["status"], "succeeded")
            self.assertTrue(any(issue["code"] == "assembly.no_values" for issue in job_payload["issues"]))
            self.assertFalse(any(item["kind"] == "final_pdf" for item in job_payload["artifacts"]))

    def _build_minimal_pipeline(self, config: FormAIConfig):
        llm = FakeVisionLLMClient(detected_fields=[], extracted_values={})
        return FormAIPipeline(
            evaluator=InputEvaluatorAgent(config, llm),
            generator=AcroFormGeneratorAgent(config, FakeCommonFormsAdapter([])),
            extractor=DataExtractorAgent(config, llm),
            assembler=FinalAssemblerAgent(config),
        )

    def _wait_for_job(self, client, job_id: str, timeout_seconds: float = 5.0):
        deadline = time.time() + timeout_seconds
        last_payload = None
        while time.time() < deadline:
            response = client.get(f"/jobs/{job_id}")
            self.assertEqual(response.status_code, 200)
            last_payload = response.json()
            if last_payload["status"] in {"succeeded", "failed"}:
                return last_payload
            time.sleep(0.05)
        self.fail(f"Timed out waiting for job {job_id}. Last payload: {last_payload}")


@unittest.skipUnless(_reportlab_available(), "reportlab is required for assembly readability tests")
class ReadableAssemblyTests(unittest.TestCase):
    def test_final_assembler_attaches_self_check_when_source_reference_is_provided(self):
        with tempfile.TemporaryDirectory(prefix="formai_self_check_") as temp_dir:
            workdir = Path(temp_dir)
            fillable_path = workdir / "fillable.pdf"
            output_path = workdir / "filled.pdf"
            source_reference = workdir / "source.pdf"
            config = FormAIConfig.from_env(workdir)
            create_reportlab_acroform_pdf(
                fillable_path,
                fields=[FixtureField("Policy Number", "policy_number", 72, 160, 180, height=20)],
            )
            create_flat_filled_pdf(
                source_reference,
                [FixtureField("Policy Number", "policy_number", 72, 160, 180, height=20, value="AB-123")],
            )
            extraction = ExtractionResult(
                source_path=source_reference,
                structured_data={
                    "policy_number": FieldValue(
                        value="AB-123",
                        confidence=0.95,
                        source_key="policy_number",
                    )
                },
                mappings=[
                    FieldMapping(
                        source_key="policy_number",
                        target_field="policy_number",
                        confidence=0.95,
                        status=MappingStatus.MAPPED,
                    )
                ],
                confidence=0.94,
            )

            fake_check = SelfCheckResult(
                source_reference=str(source_reference),
                overall_score=0.41,
                source_score=0.35,
                output_score=0.47,
                passed=False,
            )
            with patch(
                "formai.agents.final_assembler.run_field_level_self_check",
                return_value=fake_check,
            ):
                result = FinalAssemblerAgent(config).assemble(
                    fillable_path,
                    extraction,
                    output_path,
                    source_reference=source_reference,
                )

            self.assertTrue(output_path.exists())
            self.assertIsNotNone(result.self_check)
            self.assertEqual(result.self_check.overall_score, 0.41)
            issue_codes = [issue.code for issue in result.issues]
            self.assertIn("assembly.self_check.review_required", issue_codes)

    def test_final_assembler_reports_visual_overflow_with_context(self):
        with tempfile.TemporaryDirectory(prefix="formai_assemble_overflow_") as temp_dir:
            workdir = Path(temp_dir)
            fillable_path = workdir / "fillable.pdf"
            output_path = workdir / "filled.pdf"
            config = FormAIConfig.from_env(workdir)
            create_reportlab_acroform_pdf(
                fillable_path,
                fields=[
                    FixtureField("Describe the incident", "describe_the_incident", 250, 160, 90, height=20),
                    FixtureField("Describe the incident body", "describe_the_incident__body", 72, 188, 218, height=34),
                ],
            )
            extraction = ExtractionResult(
                source_path=fillable_path,
                structured_data={
                    "describe_the_incident": FieldValue(
                        value=(
                            "This is a long description that should remain readable in the final PDF even if "
                            "the full paragraph does not fit into the available multiline widgets. The write "
                            "path should keep the sentence readable, trim at a word boundary, and emit a "
                            "visual overflow issue with the omitted remainder."
                        ),
                        confidence=0.92,
                        source_key="describe_the_incident",
                        raw_text="long description",
                    )
                },
                mappings=[
                    FieldMapping(
                        source_key="describe_the_incident",
                        target_field="describe_the_incident",
                        confidence=0.95,
                        status=MappingStatus.MAPPED,
                    )
                ],
                confidence=0.92,
            )

            result = FinalAssemblerAgent(config).assemble(fillable_path, extraction, output_path)

            self.assertTrue(output_path.exists())
            overflow_issues = [issue for issue in result.issues if issue.code == "assembly.visual_overflow"]
            self.assertEqual(len(overflow_issues), 1)
            self.assertEqual(overflow_issues[0].context["field_name"], "describe_the_incident")
            self.assertIn("...", overflow_issues[0].context["written_text"])
            self.assertTrue(overflow_issues[0].context["overflow_text"])

    def test_final_assembler_appends_overflow_page_when_configured(self):
        from pypdf import PdfReader

        with tempfile.TemporaryDirectory(prefix="formai_assemble_overflow_page_") as temp_dir:
            workdir = Path(temp_dir)
            fillable_path = workdir / "fillable.pdf"
            output_path = workdir / "filled.pdf"
            config = FormAIConfig.from_env(workdir)
            config.overflow_strategy = "overflow_page"
            create_reportlab_acroform_pdf(
                fillable_path,
                fields=[
                    FixtureField("Describe the incident", "describe_the_incident", 250, 160, 90, height=20),
                    FixtureField("Describe the incident body", "describe_the_incident__body", 72, 188, 218, height=34),
                ],
            )
            extraction = ExtractionResult(
                source_path=fillable_path,
                structured_data={
                    "describe_the_incident": FieldValue(
                        value=(
                            "This is a long description that should remain readable in the main PDF "
                            "while the omitted continuation is appended to a dedicated overflow page "
                            "for full reference."
                        ),
                        confidence=0.92,
                        source_key="describe_the_incident",
                        raw_text="long description",
                    )
                },
                mappings=[
                    FieldMapping(
                        source_key="describe_the_incident",
                        target_field="describe_the_incident",
                        confidence=0.95,
                        status=MappingStatus.MAPPED,
                    )
                ],
                confidence=0.92,
            )

            result = FinalAssemblerAgent(config).assemble(fillable_path, extraction, output_path)

            self.assertTrue(output_path.exists())
            reader = PdfReader(str(output_path))
            self.assertEqual(len(reader.pages), 2)
            issue_codes = [issue.code for issue in result.issues]
            self.assertIn("assembly.visual_overflow", issue_codes)
            self.assertIn("assembly.overflow_continuation_page", issue_codes)

    def test_final_assembler_appends_same_page_overflow_note_when_configured(self):
        from pypdf import PdfReader

        with tempfile.TemporaryDirectory(prefix="formai_assemble_same_page_note_") as temp_dir:
            workdir = Path(temp_dir)
            fillable_path = workdir / "fillable.pdf"
            output_path = workdir / "filled.pdf"
            config = FormAIConfig.from_env(workdir)
            config.overflow_strategy = "same_page_note"
            create_reportlab_acroform_pdf(
                fillable_path,
                fields=[
                    FixtureField("Describe the incident", "describe_the_incident", 250, 160, 90, height=20),
                    FixtureField("Describe the incident body", "describe_the_incident__body", 72, 188, 218, height=34),
                ],
            )
            extraction = ExtractionResult(
                source_path=fillable_path,
                structured_data={
                    "describe_the_incident": FieldValue(
                        value=(
                            "This is a long description that should remain readable in the main PDF "
                            "while the omitted continuation is appended inside the remaining space on "
                            "the same page for quick reference."
                        ),
                        confidence=0.92,
                        source_key="describe_the_incident",
                        raw_text="long description",
                    )
                },
                mappings=[
                    FieldMapping(
                        source_key="describe_the_incident",
                        target_field="describe_the_incident",
                        confidence=0.95,
                        status=MappingStatus.MAPPED,
                    )
                ],
                confidence=0.92,
            )

            result = FinalAssemblerAgent(config).assemble(fillable_path, extraction, output_path)

            self.assertTrue(output_path.exists())
            reader = PdfReader(str(output_path))
            self.assertEqual(len(reader.pages), 1)
            issue_codes = [issue.code for issue in result.issues]
            self.assertIn("assembly.visual_overflow", issue_codes)
            self.assertIn("assembly.inline_overflow_note", issue_codes)
            extracted_text = reader.pages[0].extract_text()
            self.assertIn("Incident cont.:", extracted_text)

    def test_same_page_overflow_note_truncates_to_two_lines(self):
        from pypdf import PdfReader

        with tempfile.TemporaryDirectory(prefix="formai_same_page_note_truncate_") as temp_dir:
            workdir = Path(temp_dir)
            fillable_path = workdir / "fillable.pdf"
            output_path = workdir / "filled.pdf"
            config = FormAIConfig.from_env(workdir)
            config.overflow_strategy = "same_page_note"
            create_reportlab_acroform_pdf(
                fillable_path,
                fields=[
                    FixtureField("Describe the incident", "describe_the_incident", 250, 160, 90, height=20),
                    FixtureField("Describe the incident body", "describe_the_incident__body", 72, 188, 218, height=34),
                ],
            )
            extraction = ExtractionResult(
                source_path=fillable_path,
                structured_data={
                    "describe_the_incident": FieldValue(
                        value=(
                            "This is a long description that should remain readable in the main PDF while the "
                            "omitted continuation is appended inside the remaining space on the same page. "
                            "The note itself should not grow into a visible block and must therefore truncate "
                            "after a very small number of visual lines."
                        ),
                        confidence=0.92,
                        source_key="describe_the_incident",
                        raw_text="long description",
                    )
                },
                mappings=[
                    FieldMapping(
                        source_key="describe_the_incident",
                        target_field="describe_the_incident",
                        confidence=0.95,
                        status=MappingStatus.MAPPED,
                    )
                ],
                confidence=0.92,
            )

            result = FinalAssemblerAgent(config).assemble(fillable_path, extraction, output_path)

            self.assertTrue(output_path.exists())
            reader = PdfReader(str(output_path))
            extracted_text = reader.pages[0].extract_text()
            self.assertIn("Incident cont.:", extracted_text)
            self.assertIn("...", extracted_text)
            issue_codes = [issue.code for issue in result.issues]
            self.assertIn("assembly.inline_overflow_note", issue_codes)

    def test_verification_profile_resolution_uses_profile_registry(self):
        profile = resolve_verification_profile(
            profile_name="student_petition_tr",
            template_fields=[
                AcroField(
                    name="ogrenci_no",
                    field_kind=FieldKind.TEXT,
                    box=BoundingBox(1, 10, 10, 40, 20),
                    page_number=1,
                )
            ],
        )
        self.assertEqual(profile.name, "student_petition_tr")
        self.assertEqual(profile.ocr_lang, "tur+eng")
        self.assertIn("ogrenci_no", profile.critical_fields)

    def test_build_vision_client_auto_prefers_openai_when_key_exists_and_local_unavailable(self):
        config = FormAIConfig.from_env(Path.cwd())
        config.vision_provider = "auto"
        config.openai_api_key = "test-key"
        with patch("formai.pipeline._ollama_is_available", return_value=False):
            with patch("formai.pipeline.OpenAIVisionClient", return_value=object()) as factory:
                client = build_vision_client(config)
        self.assertIs(client, factory.return_value)
