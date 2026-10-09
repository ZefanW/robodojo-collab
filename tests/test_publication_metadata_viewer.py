"""Run the portable, dependency-free viewer contract tests when Node is available."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MetadataViewerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is optional for Python-only installations")
    def test_metadata_correction_display_contract(self):
        result = subprocess.run(
            [shutil.which("node"), "--test", "tests/test_publication_metadata_corrections.cjs"],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
