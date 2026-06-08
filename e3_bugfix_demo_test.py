"""E3.1 development_bug_fix demo — deterministic red→green oracle.

Self-contained (stdlib unittest, no repo imports, no pytest/venv): the "bug" is a
missing marker file. RED until the fix writes E3_BUGFIX_MARKER.txt with "fixed".
"""
import os
import unittest


class E3BugfixDemoTest(unittest.TestCase):
    def test_marker_present_and_fixed(self):
        self.assertTrue(
            os.path.exists("E3_BUGFIX_MARKER.txt"),
            "E3 demo bug: E3_BUGFIX_MARKER.txt missing — apply the fix",
        )
        with open("E3_BUGFIX_MARKER.txt", encoding="utf-8") as fh:
            self.assertEqual(fh.read().strip(), "fixed")


if __name__ == "__main__":
    unittest.main()
