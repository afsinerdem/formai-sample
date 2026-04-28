import unittest
from pathlib import Path

from formai.agents.input_evaluator import InputEvaluatorAgent
from formai.config import FormAIConfig
from formai.llm.base import NullVisionLLMClient
from formai.mapping import map_extracted_values_to_fields, resolve_filled_values
from formai.models import AcroField, BoundingBox, FieldKind, FieldValue, MappingStatus
from formai.profiles import infer_profile_from_target_fields


class MappingTests(unittest.TestCase):
    def test_extracted_values_map_to_best_matching_acro_fields(self):
        acro_fields = [
            AcroField(
                name="policy_number",
                field_kind=FieldKind.TEXT,
                box=BoundingBox(1, 0, 0, 10, 10),
                page_number=1,
                label="Policy Number",
            ),
            AcroField(
                name="insured_name",
                field_kind=FieldKind.TEXT,
                box=BoundingBox(1, 10, 10, 20, 20),
                page_number=1,
                label="Insured Name",
            ),
        ]
        structured_data = {
            "policy_number": FieldValue(
                value="PN-42",
                confidence=0.91,
                source_key="policy_number",
            ),
            "insured_name": FieldValue(
                value="Ada Lovelace",
                confidence=0.88,
                source_key="insured_name",
            ),
        }

        mappings = map_extracted_values_to_fields(structured_data, acro_fields, 0.55)

        self.assertEqual([mapping.target_field for mapping in mappings], ["policy_number", "insured_name"])
        self.assertTrue(all(mapping.status == MappingStatus.MAPPED for mapping in mappings))

    def test_resolve_filled_values_keeps_only_mapped_targets(self):
        structured_data = {
            "policy_number": FieldValue(
                value="PN-42",
                confidence=0.91,
                source_key="policy_number",
            )
        }
        mappings = [
            map_extracted_values_to_fields(
                structured_data,
                [
                    AcroField(
                        name="policy_number",
                        field_kind=FieldKind.TEXT,
                        box=None,
                        page_number=1,
                    )
                ],
                0.55,
            )[0]
        ]

        resolved, confidence = resolve_filled_values(structured_data, mappings)

        self.assertEqual(resolved, {"policy_number": "PN-42"})
        self.assertGreater(confidence, 0.8)

    def test_profile_aware_mapping_uses_turkish_aliases(self):
        acro_fields = [
            AcroField(
                name="ogrenci_no",
                field_kind=FieldKind.TEXT,
                box=None,
                page_number=1,
                label="Öğrenci No",
            ),
            AcroField(
                name="ad_soyad",
                field_kind=FieldKind.TEXT,
                box=None,
                page_number=1,
                label="Ad Soyad",
            ),
            AcroField(
                name="e_posta",
                field_kind=FieldKind.TEXT,
                box=None,
                page_number=1,
                label="E-Posta Adresi",
            ),
        ]
        structured_data = {
            "Student Number": FieldValue("20241001", 0.88, "Student Number"),
            "First & Last Name": FieldValue("Ahmet Yilmaz", 0.84, "First & Last Name"),
            "Email Address": FieldValue("a.yilmaz@email.com", 0.91, "Email Address"),
        }

        mappings = map_extracted_values_to_fields(
            structured_data,
            acro_fields,
            0.55,
            profile="student_petition_tr",
        )

        self.assertEqual(
            [mapping.target_field for mapping in mappings],
            ["ogrenci_no", "ad_soyad", "e_posta"],
        )
        self.assertTrue(all(mapping.status == MappingStatus.MAPPED for mapping in mappings))

    def test_profile_inference_detects_student_petition_target_family(self):
        target_fields = [
            AcroField("ogrenci_no", FieldKind.TEXT, None, 1, label="Öğrenci No"),
            AcroField("ad_soyad", FieldKind.TEXT, None, 1, label="Ad Soyad"),
            AcroField("bolum_program", FieldKind.TEXT, None, 1, label="Bölüm/Program"),
            AcroField("telefon", FieldKind.TEXT, None, 1, label="Cep Telefon No"),
            AcroField("ogrenci_aciklamasi", FieldKind.MULTILINE, None, 1, label="Öğrencinin Açıklaması"),
        ]

        self.assertEqual(infer_profile_from_target_fields(target_fields), "student_petition_tr")


class InputEvaluatorReviewTests(unittest.TestCase):
    def test_field_reviews_flag_non_semantic_names(self):
        agent = InputEvaluatorAgent(
            FormAIConfig.from_env(Path(".")),
            NullVisionLLMClient(),
        )
        reviews = agent._review_existing_fields(
            [
                AcroField(
                    name="Field1",
                    field_kind=FieldKind.TEXT,
                    box=None,
                    page_number=1,
                    label="Policy Number",
                ),
                AcroField(
                    name="insured_name",
                    field_kind=FieldKind.TEXT,
                    box=None,
                    page_number=1,
                    label="Insured Name",
                ),
            ]
        )

        self.assertFalse(reviews[0].is_valid)
        self.assertEqual(reviews[0].recommended_name, "policy_number")
        self.assertTrue(reviews[1].is_valid)


if __name__ == "__main__":
    unittest.main()
