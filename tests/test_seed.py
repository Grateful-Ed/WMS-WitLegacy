import json
import tempfile
import unittest
from pathlib import Path

from helpers import DATASET, HostCase
from legacy_wms.fixed import LAYOUTS
from legacy_wms.seed import seed, SeedError
from legacy_wms.store import Host


class SeedTests(HostCase):
    def test_determinism_byte_identical(self):
        with tempfile.TemporaryDirectory() as other:
            h2 = Host.open(other)
            from legacy_wms.seed import seed_from_file
            seed_from_file(h2, DATASET)
            for name in LAYOUTS:
                a = self.h.p("MASTER", name + ".DAT").read_bytes()
                b = h2.p("MASTER", name + ".DAT").read_bytes()
                self.assertEqual(a, b, name)

    def test_row_counts_match_dataset(self):
        ds = json.loads(Path(DATASET).read_text())
        t = self.h.t
        self.assertEqual(len(t["ITM"]), len(ds["items"]))
        self.assertEqual(len(t["LOC"]), len(ds["bins"]))
        self.assertEqual(len(t["DOR"]), len(ds["doors"]))
        self.assertEqual(len(t["OHD"]), len(ds["orders"]))
        self.assertEqual(len(t["OLN"]), sum(len(o["lines"]) for o in ds["orders"]))
        self.assertEqual(len(t["USR"]), len(ds["workers"]))
        self.assertEqual(len(t["TSK"]), len(ds["tasks"]))
        self.assertEqual(sum(r["ONHD"] for r in t["INV"].values()),
                         sum(r["qty"] for r in ds["inventory"]))

    def test_legacy_shape(self):
        for name in LAYOUTS:
            text = self.h.p("MASTER", name + ".DAT").read_text()
            self.assertNotIn("None", text)
            self.assertNotIn("null", text)
            self.assertTrue(text.isascii())
            self.assertEqual(text, text.upper() if name != "COD" else text.upper())
            widths = {len(x) for x in text.splitlines()}
            self.assertLessEqual(len(widths), 1, name)   # fixed record length
        d = self.h.get("ASH", "ASN-1003")
        self.assertEqual((d["ASST"], d["ARDT"], d["ARTM"]), ("AR", "20260112", 630))
        self.assertEqual(self.h.get("ITM", "SKU-1001")["IWGT"], 200)   # 0.2 kg -> grams
        self.assertEqual(self.h.get("OHD", "SO-5001")["ORST"], "RL")
        self.assertEqual(self.h.get("PAL", "PAL-004")["PLST"], "SL")
        self.assertEqual(self.h.get("DOR", "D03")["DRRF"], "ASN-1003")

    def test_unknown_word_stops_seed(self):
        ds = json.loads(Path(DATASET).read_text())
        ds["orders"][0]["status"] = "teleported"
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SeedError):
                seed(Host.open(d), ds)

    def test_sequences_continue_after_seed(self):
        self.assertEqual(self.h.seq["EXC"], 2)
        self.assertEqual(self.h.seq["TRN"], 36)


if __name__ == "__main__":
    unittest.main()
