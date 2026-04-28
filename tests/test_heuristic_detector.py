import tempfile
import unittest
from pathlib import Path

from formai.pdf.heuristic_detector import detect_fields_from_pdf_layout
from tests.fixture_factory import create_flat_template_pdf


class HeuristicDetectorTests(unittest.TestCase):
    def test_detect_fields_from_line_based_pdf_layout(self):
        with tempfile.TemporaryDirectory(prefix="formai_heuristic_") as temp_dir:
            pdf_path = Path(temp_dir) / "template.pdf"
            create_flat_template_pdf(pdf_path)

            detected_fields = detect_fields_from_pdf_layout(pdf_path)
            labels = {field.label for field in detected_fields}

            self.assertGreaterEqual(len(detected_fields), 3)
            self.assertIn("Policy Number", labels)
            self.assertIn("Insured Name", labels)
            self.assertIn("Incident Date", labels)

    def test_detects_missing_real_world_boxes_and_checkboxes(self):
        pdf_path = Path("ornek/input.pdf")
        detected_fields = detect_fields_from_pdf_layout(pdf_path)
        labels = {field.label for field in detected_fields}

        self.assertIn("Report Year", labels)
        self.assertIn("Time AM", labels)
        self.assertIn("Time PM", labels)
        self.assertIn("Was anyone injured Yes", labels)
        self.assertIn("Was anyone injured No", labels)
        incident_field = next(
            field for field in detected_fields if field.label == "Describe the Incident"
        )
        self.assertIsNotNone(incident_field.continuation_box)
        self.assertLess(incident_field.continuation_box.left, incident_field.box.left)


if __name__ == "__main__":
    unittest.main()
