import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from formai.cli import main
from tests.fixture_factory import create_reportlab_acroform_pdf


def _reportlab_available() -> bool:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        return False
    return True


@unittest.skipUnless(_reportlab_available(), "reportlab is required for CLI tests")
class CLITests(unittest.TestCase):
    def test_analyze_command_prints_json(self):
        with tempfile.TemporaryDirectory(prefix="formai_cli_") as temp_dir:
            pdf_path = Path(temp_dir) / "cli_fixture.pdf"
            create_reportlab_acroform_pdf(pdf_path)
            stdout = io.StringIO()

            with patch("sys.argv", ["formai", "analyze", "--template", str(pdf_path)]):
                with redirect_stdout(stdout):
                    main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["document_kind"], "acroform")
            self.assertEqual(len(payload["existing_fields"]), 3)


if __name__ == "__main__":
    unittest.main()
