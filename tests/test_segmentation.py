import unittest

from formai.models import AcroField, BoundingBox, FieldKind
from formai.segmentation import (
    coalesce_segmented_field_values,
    continuation_field_name,
    expand_values_for_template_fields,
    fit_text_to_boxes,
)
from formai.utils import normalize_text


class SegmentationTests(unittest.TestCase):
    def test_coalesces_body_field_into_logical_value(self):
        combined = coalesce_segmented_field_values(
            {
                "describe_the_incident": "Vehicle slipped on wet floor",
                "describe_the_incident__body": "No other party was involved.",
            }
        )

        self.assertEqual(
            combined["describe_the_incident"],
            "Vehicle slipped on wet floor\nNo other party was involved.",
        )

    def test_coalesces_multiple_body_segments_in_order(self):
        combined = coalesce_segmented_field_values(
            {
                "describe_the_incident": "Vehicle slipped on wet floor",
                "describe_the_incident__body_2": "Witness called emergency services.",
                "describe_the_incident__body": "No other party was involved.",
            }
        )

        self.assertEqual(
            combined["describe_the_incident"],
            "Vehicle slipped on wet floor\nNo other party was involved.\nWitness called emergency services.",
        )

    def test_expands_logical_value_into_lead_and_body_fields(self):
        fields = [
            AcroField(
                name="describe_the_incident",
                field_kind=FieldKind.TEXT,
                box=BoundingBox(page_number=1, left=150, top=100, right=360, bottom=122),
                page_number=1,
                label="describe_the_incident",
            ),
            AcroField(
                name="describe_the_incident__body",
                field_kind=FieldKind.TEXT,
                box=BoundingBox(page_number=1, left=50, top=124, right=360, bottom=220),
                page_number=1,
                label="describe_the_incident__body",
            ),
        ]
        source_text = (
            "The driver reported that the vehicle slipped on a wet floor while turning "
            "into the loading bay and lightly struck the wall."
        )

        result = expand_values_for_template_fields(
            {"describe_the_incident": source_text},
            fields,
        )

        self.assertIn("describe_the_incident__body", result.filled_values)
        self.assertTrue(result.filled_values["describe_the_incident"])
        self.assertTrue(result.filled_values["describe_the_incident__body"])
        recombined = coalesce_segmented_field_values(result.filled_values)
        self.assertEqual(
            normalize_text(recombined["describe_the_incident"]),
            normalize_text(source_text),
        )
        self.assertFalse(result.overflow)

    def test_expands_logical_value_into_multiple_continuation_segments(self):
        fields = [
            AcroField(
                name="describe_the_incident",
                field_kind=FieldKind.TEXT,
                box=BoundingBox(page_number=1, left=200, top=100, right=360, bottom=122),
                page_number=1,
                label="describe_the_incident",
            ),
            AcroField(
                name=continuation_field_name("describe_the_incident", 1),
                field_kind=FieldKind.TEXT,
                box=BoundingBox(page_number=1, left=50, top=124, right=360, bottom=146),
                page_number=1,
                label=continuation_field_name("describe_the_incident", 1),
            ),
            AcroField(
                name=continuation_field_name("describe_the_incident", 2),
                field_kind=FieldKind.TEXT,
                box=BoundingBox(page_number=1, left=50, top=148, right=360, bottom=170),
                page_number=1,
                label=continuation_field_name("describe_the_incident", 2),
            ),
        ]
        source_text = (
            "The driver reported that the vehicle slipped on a wet floor while turning "
            "into the loading bay and lightly struck the wall before coming to a stop."
        )

        result = expand_values_for_template_fields(
            {"describe_the_incident": source_text},
            fields,
        )

        self.assertTrue(result.filled_values["describe_the_incident"])
        self.assertTrue(result.filled_values["describe_the_incident__body"])
        self.assertTrue(result.filled_values["describe_the_incident__body_2"])
        recombined = coalesce_segmented_field_values(result.filled_values)
        self.assertEqual(
            normalize_text(recombined["describe_the_incident"]),
            normalize_text(source_text),
        )
        self.assertFalse(result.overflow)

    def test_rewraps_remainder_for_wider_body_segment(self):
        fields = [
            AcroField(
                name="if_yes_enter_the_witnesses_names_and_contact_info",
                field_kind=FieldKind.TEXT,
                box=BoundingBox(page_number=1, left=283, top=564, right=562, bottom=586),
                page_number=1,
                label="if_yes_enter_the_witnesses_names_and_contact_info",
            ),
            AcroField(
                name="if_yes_enter_the_witnesses_names_and_contact_info__body",
                field_kind=FieldKind.TEXT,
                box=BoundingBox(page_number=1, left=50, top=582, right=562, bottom=622),
                page_number=1,
                label="if_yes_enter_the_witnesses_names_and_contact_info__body",
            ),
        ]
        source_text = (
            "Yes, an elderly man named Arthur Pendelton was standing at the corner. "
            "He can be reached at 555-021-0099. He saw the white sedan run the red light."
        )

        result = expand_values_for_template_fields(
            {"if_yes_enter_the_witnesses_names_and_contact_info": source_text},
            fields,
        )

        recombined = coalesce_segmented_field_values(result.filled_values)
        self.assertEqual(
            normalize_text(recombined["if_yes_enter_the_witnesses_names_and_contact_info"]),
            normalize_text(source_text),
        )
        self.assertFalse(result.overflow)

    def test_truncates_with_ellipsis_when_multiline_text_still_overflows(self):
        fields = [
            AcroField(
                name="describe_the_incident",
                field_kind=FieldKind.TEXT,
                box=BoundingBox(page_number=1, left=220, top=160, right=330, bottom=182),
                page_number=1,
                label="describe_the_incident",
            ),
            AcroField(
                name="describe_the_incident__body",
                field_kind=FieldKind.TEXT,
                box=BoundingBox(page_number=1, left=72, top=188, right=330, bottom=224),
                page_number=1,
                label="describe_the_incident__body",
            ),
        ]
        source_text = (
            "This is a deliberately long multiline description that cannot fit into the narrow "
            "lead box and short body box without truncation, so the final line should end with ellipsis."
        )

        result = expand_values_for_template_fields(
            {"describe_the_incident": source_text},
            fields,
        )

        self.assertIn("describe_the_incident", result.overflow)
        self.assertIn("...", result.overflow["describe_the_incident"].written_text)
        self.assertTrue(result.overflow["describe_the_incident"].overflow_text)
        body_lines = result.filled_values["describe_the_incident__body"].splitlines()
        self.assertLessEqual(len(body_lines), 2)

    def test_same_page_compact_strategy_reduces_overflow(self):
        boxes = [
            BoundingBox(page_number=1, left=220, top=160, right=330, bottom=182),
            BoundingBox(page_number=1, left=72, top=188, right=330, bottom=206),
            BoundingBox(page_number=1, left=72, top=208, right=330, bottom=226),
        ]
        source_text = (
            "This is a deliberately long multiline description that should fit more naturally "
            "when the same-page compact strategy is selected, even if the default readable mode "
            "still needs to truncate the end of the paragraph."
        )

        readable_segments, readable_overflow = fit_text_to_boxes(
            source_text,
            boxes,
            fitting_strategy="readable_cut",
        )
        compact_segments, compact_overflow = fit_text_to_boxes(
            source_text,
            boxes,
            fitting_strategy="same_page_compact",
        )

        self.assertTrue(readable_overflow)
        self.assertLessEqual(len(compact_overflow), len(readable_overflow))
        self.assertGreaterEqual(
            len("\n".join(compact_segments)),
            len("\n".join(readable_segments)),
        )


if __name__ == "__main__":
    unittest.main()
