"""Hardening: the R01 rollback restores the master tables whatever the act did
to the set of tables (a table deleted, a bogus table added)."""
import copy
import unittest
from unittest import mock

from helpers import HostCase
from legacy_wms import ops


def act(a, **kw):
    return dict(ACT=a, **kw)


class Rollback(HostCase):
    def test_rollback_restores_a_deleted_table_and_drops_a_bogus_one(self):
        real = ops._ACT_FUNCS["RLSE"]
        seen = {}

        def hostile(h, rec, *a):
            if rec["DOC"] == "SO-5005":
                seen["before"] = copy.deepcopy(h.t)
                del h.t["OHD"]                              # whole table entry gone
                h.t["BOGUS"] = {("X",): {"X": 1}}           # a table that never existed
                raise RuntimeError("engineered")
            seen["after"] = copy.deepcopy(h.t)              # state the sibling starts from
            seen["same_dict"] = h.t is seen["tables_obj"]
            real(h, rec, *a)

        seen["tables_obj"] = self.h.t
        self.drop(1, [act("RLSE", DOC="SO-5005"), act("RLSE", DOC="SO-5006")])
        with mock.patch.dict(ops._ACT_FUNCS, {"RLSE": hostile}):
            s = self.run2()
        self.assertEqual((s.ok, s.rej), (1, 1))
        self.assertEqual([(r["SEQ"], r["RCD"]) for r in self.results("RJ")], [(1, "R01")])
        self.assertEqual(seen["after"], seen["before"])     # exactly the pre-act tables
        self.assertTrue(seen["same_dict"])                  # restored in place
        self.assertIs(self.h.t, seen["tables_obj"])
        self.assertNotIn("BOGUS", self.h.t)
        self.assertEqual(sorted(self.h.t), sorted(seen["before"]))
        self.assertEqual(len(self.h.t["OHD"]), len(seen["before"]["OHD"]))   # rows back
        self.assertEqual(self.h.get("OHD", "SO-5005")["ORST"], "NW")
        self.assertEqual(self.h.get("OHD", "SO-5006")["ORST"], "RL")         # sibling ran
        self.assertNotIn("BOGUS", self.reload().t)                           # and on disk


if __name__ == "__main__":
    unittest.main()
