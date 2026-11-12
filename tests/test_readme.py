import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ReadmeTests(unittest.TestCase):
    def test_readme_tables_match_the_code(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import make_readme
        self.assertEqual((ROOT / "README.md").read_text(), make_readme.build(),
                         "README.md is out of date: run python3 tools/make_readme.py")

    def test_every_reject_code_the_code_can_raise_is_documented(self):
        import re
        from legacy_wms.codes import REJECTS
        src = "".join((ROOT / "legacy_wms" / n).read_text()
                      for n in ("ops.py", "batch.py", "fixed.py"))
        used = set(re.findall(r'"([FRB]\d\d)"', src))
        self.assertEqual(used - set(REJECTS), set())
        self.assertEqual(set(REJECTS) - used, set())

    def test_no_forbidden_modern_machinery(self):
        src = "".join(p.read_text() for p in (ROOT / "legacy_wms").glob("*.py"))
        for word in ("uuid", "http", "socket", "asyncio", "websocket", "flask"):
            self.assertNotIn("import " + word, src)
        self.assertNotIn("microsecond", src)


if __name__ == "__main__":
    unittest.main()
