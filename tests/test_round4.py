"""Fix round 4: one test per item."""
import os
import unittest
from unittest import mock

from helpers import HostCase, SRC
from legacy_wms import batch as B
from legacy_wms import ops
from legacy_wms.fixed import DETAIL, HEADER
from legacy_wms.flatfile import build_inbound, inbound_name
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def act(a, **kw):
    return dict(ACT=a, **kw)


def rcpt(pal, qty=10):
    return act("RCPT", DOC="ASN-1003", LIN=1, ITM="SKU-1002", QTY=qty, DOR="D03", TLC=pal)


class Round4(HostCase):
    def put(self, name, text):
        self.h.p("IN", name).write_text(text)

    # ---- A1
    def test_1a_unreadable_file_uses_its_number_and_next_file_processes(self):
        self.put(inbound_name(SRC, 1), "this is garbage\n")
        self.drop(2, [rcpt("PAL-100")])
        s = self.run2()
        self.assertEqual(s.files, 1)
        self.assertEqual(self.inv("PAL-100", "SKU-1002", "PP"), 10)
        self.assertEqual(self.h.src[SRC]["NEXT"], 3)
        self.assertEqual([r["DISP"] for r in self.h.ledger], ["UR", "OK"])
        self.assertEqual([a["ALCD"] for a in self.h.open_alarms()], ["A03"])
        self.assertEqual(self.results("RJ"), [])             # sender not trusted: no result
        self.assertEqual(os.listdir(self.h.p("ERR")), [inbound_name(SRC, 1)])

    def test_1b_zero_byte_and_bad_header_date_behave_the_same(self):
        self.put(inbound_name(SRC, 1), "")
        good = build_inbound(SRC, 2, [rcpt("PAL-100")])
        bad_date = HEADER.pack({"REC": "H", "SRC": SRC, "ICTL": 2, "FDAT": "00000000",
                                "FTIM": 0})
        pos, w = HEADER.offset("FDAT")
        bad_line = (bad_date[:pos] + "20261399" + bad_date[pos + w:]).ljust(151)
        self.put(inbound_name(SRC, 2), bad_line + "\n" + good.split("\n", 1)[1])
        self.drop(3, [rcpt("PAL-101")])
        s = self.run_batch()
        self.assertEqual([r["DISP"] for r in self.h.ledger], ["UR", "UR", "OK"])
        self.assertEqual(self.h.src[SRC]["NEXT"], 4)
        self.assertEqual(s.held, 0)
        self.assertEqual(self.inv("PAL-101", "SKU-1002", "PP"), 10)
        self.assertIsNone(self.h.get("PAL", "PAL-100"))

    def test_1c_unparseable_name_raises_an_alarm(self):
        self.put("notes.txt", "hello\n")
        self.run_batch()
        self.assertEqual([a["ALCD"] for a in self.h.open_alarms()], ["A03"])
        self.assertEqual(os.listdir(self.h.p("ERR")), ["notes.txt"])
        self.assertEqual(self.h.src[SRC]["NEXT"], 1)

    # ---- A2
    def test_2_f07_belongs_to_the_filename_source(self):
        self.h.add_source("EXT00002")
        self.h.save()
        self.put(inbound_name(SRC, 1), build_inbound("EXT00002", 1, [rcpt("PAL-100")]))
        self.run2()
        self.assertEqual([r["RCD"] for r in self.results("RJ")], ["F07"])
        self.assertEqual(self.h.src[SRC]["NEXT"], 2)          # filename source used its number
        self.assertEqual(self.h.src["EXT00002"]["NEXT"], 1)   # header source untouched
        self.assertIsNone(self.h.get("PAL", "PAL-100"))
        self.drop(2, [rcpt("PAL-101")])
        self.run_batch()
        self.assertEqual(self.inv("PAL-101", "SKU-1002", "PP"), 10)

    # ---- A3
    def test_3_late_file_for_skipped_number_is_a_plain_duplicate(self):
        self.drop(3, [rcpt("PAL-103")])
        self.run_batch()
        self.assertTrue(B.skip_gap(self.h, SRC, ("20260112", "1200")))
        self.run_batch()
        self.drop(1, [rcpt("PAL-101")])                       # the missing file, finally
        self.drop(4, [rcpt("PAL-104")])
        self.run2()
        self.assertEqual([r["RCD"] for r in self.results("RJ")], ["F04"])
        self.assertEqual([a for a in self.h.open_alarms() if a["ALCD"] == "A02"], [])
        self.assertIsNone(self.h.get("PAL", "PAL-101"))       # acts never applied
        self.assertEqual(self.inv("PAL-104", "SKU-1002", "PP"), 10)
        self.assertTrue(any(n.startswith(inbound_name(SRC, 1) + ".DUP")
                            for n in os.listdir(self.h.p("ARCH"))))

    # ---- A4
    def test_4a_deleting_seq_ctl_never_overwrites_a_record(self):
        before = [l for l in self.h.p("MASTER", "EXC.DAT").read_text().splitlines()
                  if l.startswith("EX-001")]
        os.remove(self.h.p("CTL", "SEQ.CTL"))
        self.h = self.reload()
        self.assertEqual(self.h.seq["EXC"], 2)                # reconciled from the masters
        self.drop(1, [act("EXCP", RSN="OT", FLG="OT", DOC="SOMETHING")])
        self.run_batch()
        self.assertIsNotNone(self.h.get("EXC", "EX-003"))
        after = [l for l in self.h.p("MASTER", "EXC.DAT").read_text().splitlines()
                 if l.startswith("EX-001")]
        self.assertEqual(before, after)
        self.assertEqual(len(self.h.t["EXC"]), 3)

    def test_4b_allocation_skips_ids_in_use_even_with_a_stale_counter(self):
        self.h.seq.update({"EXC": 1, "CCN": 400, "TRN": 30, "DLV": 7001, "LBL": 0,
                           "PAL": 5, "TSK": 10})               # counters behind the data
        self.assertEqual(self.h.alloc("EXC"), "EX-003")
        self.assertEqual(self.h.alloc("TRN"), "LG-000037")
        self.assertEqual(self.h.alloc("CCN"), "CC-403")
        self.assertEqual(self.h.alloc("DLV"), "OD-7004")
        self.assertEqual(self.h.alloc("PAL"), "PAL-009")
        self.assertEqual(self.h.alloc("TSK"), "TK-0023")
        self.assertEqual(self.h.alloc("LBL"), 1)
        os.remove(self.h.p("CTL", "SEQ.CTL"))
        self.h = self.reload()
        self.drop(1, [rcpt("PAL-100")])
        self.run_batch()
        ids = [k[0] for k in self.h.t["TRN"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("LG-000037", ids)

    # ---- B5
    def test_5a_putaway_task_closes_only_when_the_pallet_is_done(self):
        put = lambda q, n: self.drop(n, [act("PUTA", ITM="SKU-1003", QTY=q, FLC="PAL-001",
                                             TLC="ZA-01-03")])
        put(1, 1)
        self.run_batch()
        self.assertEqual(self.h.get("TSK", "TK-0018")["TKST"], "OP")   # 59 still on the pallet
        put(59, 2)
        self.run_batch()
        self.assertEqual(self.h.get("TSK", "TK-0018")["TKST"], "CP")

    def test_5b_pick_task_closes_on_cumulative_picks(self):
        pick = lambda n: self.drop(n, [act("PICK", DOC="SO-5001", LIN=1, ITM="SKU-1001", QTY=6,
                                           FLC="ZB-01-01", USR="W-09")])
        pick(1)
        self.run_batch()
        self.assertEqual(self.h.get("TSK", "TK-0001")["TKST"], "OP")
        pick(2)
        self.run_batch()
        self.assertEqual(self.h.get("OLN", "SO-5001", 1)["LNST"], "PD")
        self.assertEqual(self.h.get("TSK", "TK-0001")["TKST"], "CP")

    # ---- B6
    def test_6_pack_refuses_a_fully_shorted_order(self):
        self.drop(1, [act("RLSE", DOC="SO-5006"), act("SHRT", DOC="SO-5006", LIN=1)])
        self.run_batch()
        pal, dlv = len(self.h.t["PAL"]), len(self.h.t["DLV"])
        self.drop(2, [act("PACK", DOC="SO-5006")])
        self.run2()
        self.assertEqual([r["RCD"] for r in self.results("RJ")], ["B12"])
        self.assertEqual((len(self.h.t["PAL"]), len(self.h.t["DLV"])), (pal, dlv))
        self.assertEqual(self.h.get("OHD", "SO-5006")["ORST"], "PD")

    # ---- B7
    def test_7_adjust_needs_a_sign(self):
        self.drop(1, [act("ADJT", FLC="ZA-01-01", ITM="SKU-1001", QTY=5, RSN="03")])
        before = self.inv("ZA-01-01", "SKU-1001", "AV")
        self.run2()
        self.assertEqual([r["RCD"] for r in self.results("RJ")], ["R07"])
        self.assertEqual(self.inv("ZA-01-01", "SKU-1001", "AV"), before)

    # ---- B8
    def test_8_recount_reuses_the_count_record(self):
        sysq = self.inv("ZA-01-02", "SKU-1002", "AV")
        cnt = lambda n, q: self.drop(n, [act("CNTS", FLC="ZA-01-02", ITM="SKU-1002", QTY=q,
                                             USR="W-07")])
        cnt(1, sysq - 2)
        self.run_batch()
        self.assertEqual(self.h.get("CCN", "CC-401")["CCST"], "RC")
        cnt(2, sysq)
        self.run_batch()
        cc = self.h.get("CCN", "CC-401")
        self.assertEqual((cc["CCST"], cc["CVAR"], cc["CQTY"]), ("CM", 0, sysq))
        self.assertEqual(sorted(k[0] for k in self.h.t["CCN"]), ["CC-401", "CC-402"])
        self.assertEqual(self.h.get("TSK", "TK-0021")["TKST"], "CP")

    # ---- C9
    def test_9_one_unexpected_error_rejects_one_record_only(self):
        real = ops._ACT_FUNCS["RLSE"]

        def boom(h, rec, *a):
            if rec["DOC"] == "SO-5005":
                h.get("OHD", "SO-5005")["ORST"] = "RL"        # half done, then it dies
                raise RuntimeError("engineered failure")
            real(h, rec, *a)

        self.drop(1, [act("RLSE", DOC="SO-5005"), act("RLSE", DOC="SO-5006"), rcpt("PAL-100")])
        with mock.patch.dict(ops._ACT_FUNCS, {"RLSE": boom}):
            s = self.run2()
        self.assertEqual((s.ok, s.rej), (2, 1))
        self.assertEqual([(r["SEQ"], r["RCD"]) for r in self.results("RJ")], [(1, "R01")])
        self.assertEqual(self.h.get("OHD", "SO-5005")["ORST"], "NW")   # rolled back
        self.assertEqual(self.h.get("OHD", "SO-5006")["ORST"], "RL")
        self.assertEqual(self.inv("PAL-100", "SKU-1002", "PP"), 10)
        self.assertIn("UNEXPECTED ERROR", self.h.p("LOG", "BATCH.LOG").read_text())

    # ---- D
    def test_10_to_13_readme_says_it(self):
        t = (ROOT / "README.md").read_text()
        self.assertIn("except extract files", t)
        self.assertIn("before any full extract has zero rows by design", t)
        self.assertIn("not yet counted", t)
        self.assertIn("batch commit is not atomic", t)

    def test_14_batch_log_is_upper_case(self):
        self.drop(1, [rcpt("PAL-100")])
        self.run_batch()
        B.skip_gap(self.h, SRC, ("20260112", "1200"))
        text = self.h.p("LOG", "BATCH.LOG").read_text()
        self.assertTrue(text.strip())
        self.assertEqual(text, text.upper())
        self.assertNotIn("window=", text)


if __name__ == "__main__":
    unittest.main()
