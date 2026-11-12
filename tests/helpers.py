import os
import tempfile
import unittest
from pathlib import Path

from legacy_wms.store import Host
from legacy_wms.seed import seed_from_file
from legacy_wms import batch as B
from legacy_wms.flatfile import drop_inbound, read_records

DATASET = Path(__file__).resolve().parent.parent / "data" / "canonical_dataset.json"
DAY = ("20260112", "1200")     # inside the working day
NIGHT = ("20260112", "2330")   # inside the nightly window
SRC = "EXT00001"


class HostCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.h = Host.open(self._tmp.name)
        seed_from_file(self.h, DATASET)
        self.h.add_source(SRC)
        self.h.save()

    # helpers
    def drop(self, ictl, acts, src=SRC):
        for a in acts:
            if isinstance(a, dict):
                a.setdefault("USR", "W-01")
        return drop_inbound(self.h, src, ictl, acts, "20260112", 1100)

    def run_batch(self, now=DAY):
        return B.run_batch(self.h, now)

    def run2(self, now=DAY):
        """Run two batches: one to process, one to release results."""
        s = self.run_batch(now)
        self.run_batch(now)
        return s

    def results(self, kind):
        rows = []
        for name in sorted(os.listdir(self.h.p("OUT"))):
            if f".{kind[0]}" in name and name.startswith(SRC):
                rows += read_records(self.h.p("OUT", name), kind)[1]
        return rows

    def inv(self, loc, item, st):
        r = self.h.get("INV", loc, item, st)
        return r["ONHD"] if r else 0

    def reload(self):
        h = Host.open(self._tmp.name)
        return h
