"""Fix round 5: one test per item."""
import os
import unittest
from pathlib import Path
from unittest import mock

from helpers import HostCase, DAY, SRC
from legacy_wms import ops
from legacy_wms.fixed import DETAIL
from legacy_wms.flatfile import build_inbound, inbound_name

ROOT = Path(__file__).resolve().parent.parent


def act(a, **kw):
    return dict(ACT=a, **kw)


class Round5(HostCase):
    def send(self, ictl, acts):
        self.drop(ictl, acts)
        self.run_batch()

    def sp(self):
        return [r for k, r in sorted(self.h.t["EXC"].items()) if r["EXKD"] == "SP"]

    def pick_bin(self, item, qty):
        return next(k[0] for k, r in sorted(self.h.t["INV"].items())
                    if k[1] == item and k[2] == "AV" and r["ONHD"] >= qty)

    # ---- 1
    def test_1a_shrt_raises_a_short_pick_exception(self):
        ln = self.h.get("OLN", "SO-5006", 1)
        self.send(1, [act("RLSE", DOC="SO-5006"), act("SHRT", DOC="SO-5006", LIN=1)])
        (e,) = self.sp()
        self.assertEqual((e["EXEN"], e["EXEI"], e["EXSV"], e["EXST"]), ("OR", "SO-5006", "M", "OP"))
        for part in ("SO-5006", "LINE 1", ln["ITNO"], f"ORDERED {ln['OQTY']}", "PICKED 0"):
            self.assertIn(part, e["EXRS"])

    def test_1b_pack_that_goes_out_short_is_flagged_full_pack_is_not(self):
        o = "SO-5010"                                   # one line, ordered 10
        item = self.h.get("OLN", o, 1)["ITNO"]
        self.send(1, [act("RLSE", DOC=o),
                      act("PICK", DOC=o, LIN=1, ITM=item, QTY=4, FLC=self.pick_bin(item, 4),
                          USR="W-09")])
        self.assertEqual(self.sp(), [])                  # a part pick alone raises nothing
        self.send(2, [act("SHRT", DOC=o, LIN=1)])
        self.assertEqual(len(self.sp()), 1)              # flagged once, at the SHRT
        self.send(3, [act("PACK", DOC=o)])
        flags = self.sp()
        self.assertEqual(len(flags), 2)
        self.assertIn("SHORT PACK SO-5010 ORDERED 10 PACKED 4", flags[1]["EXRS"])
        # a full pick and full pack raise nothing
        ln = self.h.get("OLN", "SO-5006", 1)
        self.send(4, [act("RLSE", DOC="SO-5006"),
                      act("PICK", DOC="SO-5006", LIN=1, ITM=ln["ITNO"], QTY=ln["OQTY"],
                          FLC=self.pick_bin(ln["ITNO"], ln["OQTY"]), USR="W-09"),
                      act("PACK", DOC="SO-5006")])
        self.assertEqual(len(self.sp()), 2)

    # ---- 2
    def test_2_zero_picked_order_has_no_pack_task_and_pack_is_refused(self):
        self.send(1, [act("RLSE", DOC="SO-5006"), act("SHRT", DOC="SO-5006", LIN=1)])
        self.assertEqual([r for r in self.h.t["TSK"].values() if r["TKTY"] == "PA"], [])
        self.drop(2, [act("PACK", DOC="SO-5006")])
        self.run2()
        self.assertEqual([r["RCD"] for r in self.results("RJ")], ["B12"])
        self.assertEqual(len(self.sp()), 1)              # the order's record is its flag

    # ---- 3
    def test_3_shrt_finishes_the_lines_pick_task(self):
        self.send(1, [act("PICK", DOC="SO-5001", LIN=1, ITM="SKU-1001", QTY=3,
                          FLC="ZB-01-01", USR="W-09")])
        self.assertEqual(self.h.get("TSK", "TK-0001")["TKST"], "OP")
        self.send(2, [act("SHRT", DOC="SO-5001", LIN=1)])
        t = self.h.get("TSK", "TK-0001")
        self.assertEqual((t["TKST"], t["CPBY"]), ("CP", "W-01"))
        self.assertEqual(self.h.get("OLN", "SO-5001", 1)["LNST"], "SX")
        self.send(3, [act("PICK", DOC="SO-5001", LIN=1, ITM="SKU-1001", QTY=1,
                          FLC="ZB-01-01", USR="W-09")])
        self.run_batch()
        self.assertEqual([r["RCD"] for r in self.results("RJ")], ["B09"])

    # ---- 4
    def test_4_pick_task_measures_its_own_line(self):
        h = self.h
        h.put("OLN", {"ORNO": "SO-5001", "LNNO": 7, "ITNO": "SKU-1001", "OQTY": 12, "PQTY": 0,
                      "SQTY": 0, "LNST": "OP"})
        t1 = dict(h.get("TSK", "TK-0001"))
        t1.update(TKNO="TK-0099", LNNO=7)
        h.put("TSK", t1)
        rec = DETAIL.blank()
        rec.update(ACT="PICK", DOC="SO-5001", LIN=1, ITM="SKU-1001", QTY=12, FLC="ZB-01-01",
                   USR="W-09")
        ops.apply_act(h, rec, DAY)                       # line 1 done
        self.assertEqual(h.get("TSK", "TK-0001")["TKST"], "CP")
        self.assertEqual(h.get("TSK", "TK-0099")["TKST"], "OP")   # line 7 untouched
        rec["LIN"] = 7
        ops.apply_act(h, rec, DAY)
        self.assertEqual(h.get("TSK", "TK-0099")["TKST"], "CP")

    # ---- 5
    def test_5_unreadable_resend_gets_a_result(self):
        self.h.p("IN", inbound_name(SRC, 1)).write_text("garbage\n")
        self.run_batch()
        self.h.p("IN", inbound_name(SRC, 1)).write_text("garbage\n")        # same bytes
        self.run2()
        self.assertEqual([r["RCD"] for r in self.results("RJ")], ["F04"])
        self.assertEqual([a["ALCD"] for a in self.h.open_alarms() if a["ALCD"] == "A02"], [])
        self.h.p("IN", inbound_name(SRC, 1)).write_text("other garbage\n")  # different bytes
        self.run2()
        self.assertEqual([r["RCD"] for r in self.results("RJ")], ["F04", "F08"])
        self.assertEqual(sorted(a["ALCD"] for a in self.h.open_alarms()), ["A02", "A03"])
        self.assertTrue(os.path.exists(self.h.p("ERR", inbound_name(SRC, 1))))

    # ---- 6
    def test_6_rollback_covers_alarms_ledger_sources_and_extract_control(self):
        real = ops._ACT_FUNCS["RLSE"]

        def leaky(h, rec, *a):
            h.raise_alarm("A01", SRC, 9, "LEAKED", ("20260112", "1200"))
            h.ledger.append({"SRCID": "LEAK", "ICTL": 1, "CKSM": "", "BTCH": 1, "DISP": "OK",
                             "NREC": 0, "NOK": 0, "NRJ": 0, "PDAT": "20260112"})
            h.src[SRC]["OCF"] = 77
            h.src["LEAK"] = {"SRCID": "LEAK", "NEXT": 1, "LAST": 0, "OCF": 0, "ORJ": 0}
            h.ext["ITM"] = {"TBLN": "ITM", "XCTL": 5, "LBCH": 5}
            raise RuntimeError("engineered")

        self.drop(1, [act("RLSE", DOC="SO-5005"), act("RLSE", DOC="SO-5006")])
        with mock.patch.dict(ops._ACT_FUNCS, {"RLSE": leaky}):
            self.run_batch()
        self.assertEqual(self.h.alarms, [])
        self.assertEqual([r["SRCID"] for r in self.h.ledger], [SRC])
        self.assertEqual(sorted(self.h.src), [SRC])
        self.assertNotEqual(self.h.src[SRC]["OCF"], 77)
        self.assertEqual(self.h.src[SRC]["NEXT"], 2)       # file still advanced the number
        self.assertEqual(self.h.ext, {})

    # ---- 7
    def test_7a_readme_discloses_the_burned_number(self):
        t = (ROOT / "README.md").read_text()
        self.assertIn("A used-up number stays used up", t)
        self.assertIn("fresh control number agreed with the operator", t)

    def test_7b_readme_rows_state_the_closure_rules(self):
        t = (ROOT / "README.md").read_text()
        self.assertIn("accumulation: part putaways leave the task open", t)
        self.assertIn("accumulation per line", t)

    def test_7c_trailer_refusals_land_in_err_and_readme_agrees(self):
        text = build_inbound(SRC, 1, [act("RLSE", DOC="SO-5005", USR="W-01")])
        lines = text.splitlines()
        lines[-1] = "T000009" + lines[-1][7:]
        self.h.p("IN", inbound_name(SRC, 1)).write_text("\n".join(lines) + "\n")
        self.run_batch()
        self.assertEqual(os.listdir(self.h.p("ERR")), [inbound_name(SRC, 1)])
        self.assertEqual(os.listdir(self.h.p("ARCH")), [])
        t = (ROOT / "README.md").read_text()
        self.assertIn("trailer or count/hash refusals (`F02`, `F03`)", t)

    def test_7d_readme_gains_the_short_flag_and_zero_rules(self):
        t = (ROOT / "README.md").read_text()
        self.assertIn("Shorts are flagged, never blocked", t)
        self.assertIn("Zero is not a short. Packing needs something picked", t)


if __name__ == "__main__":
    unittest.main()
