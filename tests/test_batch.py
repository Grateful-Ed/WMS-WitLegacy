import os
import unittest

from helpers import HostCase, DAY, NIGHT, SRC
from legacy_wms import batch as B
from legacy_wms.fixed import DETAIL
from legacy_wms.flatfile import build_inbound, inbound_name

RCPT = {"ACT": "RCPT", "DOC": "ASN-1003", "LIN": 1, "ITM": "SKU-1002", "QTY": 40,
        "DOR": "D03", "TLC": "PAL-100"}


def rcpt(pal, qty=10):
    return dict(RCPT, TLC=pal, QTY=qty)


class BatchTests(HostCase):
    def test_nothing_processed_on_arrival(self):
        self.drop(1, [RCPT])
        self.assertIsNone(self.h.get("PAL", "PAL-100"))
        self.assertEqual(os.listdir(self.h.p("OUT")), [])
        self.assertEqual(len(os.listdir(self.h.p("IN"))), 1)

    def test_batch_applies_and_archives(self):
        self.drop(1, [RCPT])
        s = self.run_batch()
        self.assertEqual((s.files, s.ok, s.rej), (1, 1, 0))
        self.assertEqual(self.inv("PAL-100", "SKU-1002", "PP"), 40)
        self.assertEqual(os.listdir(self.h.p("IN")), [])
        self.assertEqual(os.listdir(self.h.p("ARCH")), [inbound_name(SRC, 1)])

    def test_results_return_one_batch_later(self):
        self.drop(1, [RCPT])
        self.run_batch()
        self.assertEqual(os.listdir(self.h.p("OUT")), [])        # still staged
        self.assertEqual(len(os.listdir(self.h.p("STAGE"))), 1)
        self.run_batch()
        conf = self.results("CF")
        self.assertEqual(len(conf), 1)
        self.assertEqual((conf[0]["ACT"], conf[0]["DOC"], conf[0]["RSLT"], conf[0]["ICTL"]),
                         ("RCPT", "ASN-1003", "OK", 1))

    def test_resent_file_processed_exactly_once(self):
        self.drop(1, [RCPT])
        self.run_batch()
        self.drop(1, [RCPT])                       # same file sent again
        s = self.run2()
        self.assertEqual(s.dups, 1)
        self.assertEqual(self.inv("PAL-100", "SKU-1002", "PP"), 40)
        self.assertEqual([r["RCD"] for r in self.results("RJ")], ["F04"])
        self.assertEqual(self.h.src[SRC]["NEXT"], 2)

    def test_resent_file_with_other_content_alarms(self):
        self.drop(1, [RCPT])
        self.run_batch()
        self.drop(1, [dict(RCPT, QTY=41, TLC="PAL-101")])
        self.run2()
        self.assertEqual([r["RCD"] for r in self.results("RJ")], ["F08"])
        self.assertEqual([a["ALCD"] for a in self.h.open_alarms()], ["A02"])
        self.assertIsNone(self.h.get("PAL", "PAL-101"))
        self.assertEqual(len(os.listdir(self.h.p("ERR"))), 1)

    def test_gap_is_an_alarm_and_holds_later_files(self):
        self.drop(1, [rcpt("PAL-100")])
        self.drop(3, [rcpt("PAL-103")])
        s = self.run_batch()
        self.assertEqual((s.files, s.held), (1, 1))
        alarms = self.h.open_alarms()
        self.assertEqual([(a["ALCD"], a["ICTL"]) for a in alarms], [("A01", 2)])
        self.assertIsNone(self.h.get("PAL", "PAL-103"))
        self.assertTrue(os.path.exists(self.h.p("IN", inbound_name(SRC, 3))))
        # the same gap raises no second alarm on the next batch
        self.run_batch()
        self.assertEqual(len(self.h.open_alarms()), 1)

    def test_missing_file_arrives_then_order_is_kept_and_alarm_closes(self):
        self.drop(1, [rcpt("PAL-100")])
        self.drop(3, [rcpt("PAL-103")])
        self.run_batch()
        self.drop(2, [rcpt("PAL-102")])
        s = self.run_batch()
        self.assertEqual(s.files, 2)
        self.assertEqual(self.h.open_alarms(), [])
        led = [(r["ICTL"], r["BTCH"]) for r in self.h.ledger]
        self.assertEqual([c for c, _ in led], [1, 2, 3])        # strict file order
        self.assertEqual(self.h.src[SRC]["NEXT"], 4)

    def test_operator_can_skip_gap(self):
        self.drop(3, [rcpt("PAL-103")])
        self.run_batch()
        self.assertEqual(len(self.h.open_alarms()), 1)
        self.assertTrue(B.skip_gap(self.h, SRC, DAY))
        self.assertEqual(self.h.open_alarms(), [])
        s = self.run_batch()
        self.assertEqual(s.files, 1)
        self.assertEqual([r["DISP"] for r in self.h.ledger], ["SK", "SK", "OK"])
        self.assertEqual(self.inv("PAL-103", "SKU-1002", "PP"), 10)

    def test_partial_batch_failure(self):
        bad_numeric = build_inbound(SRC, 1, [dict(rcpt("PAL-103"), SEQ=3)]).splitlines()[1]
        pos, w = DETAIL.offset("QTY")
        bad_numeric = bad_numeric[:pos] + "00000X010" + bad_numeric[pos + w:]   # QTY not numeric
        acts = [rcpt("PAL-100"),
                dict(rcpt("PAL-101"), ITM="SKU-9999"),         # item not on ASN line
                bad_numeric,                                    # bad record layout
                "SHORT LINE",                                   # bad length
                rcpt("PAL-102")]
        self.drop(1, acts)
        s = self.run2()
        self.assertEqual((s.ok, s.rej), (2, 3))
        self.assertEqual(self.inv("PAL-100", "SKU-1002", "PP"), 10)
        self.assertEqual(self.inv("PAL-102", "SKU-1002", "PP"), 10)
        self.assertIsNone(self.h.get("PAL", "PAL-101"))
        self.assertEqual(sorted((r["SEQ"], r["RCD"]) for r in self.results("RJ")),
                         [(2, "B09"), (3, "R03"), (4, "R01")])
        self.assertEqual(len(self.results("CF")), 2)

    def test_reject_arc_act_batch_reject_record_with_code(self):
        self.drop(1, [dict(ACT="PICK", DOC="SO-5005", ITM="SKU-1001", QTY=5, FLC="ZB-01-01")])
        self.run_batch()
        self.assertEqual(self.results("RJ"), [])                # not back yet
        self.run_batch()
        rj = self.results("RJ")
        self.assertEqual(len(rj), 1)
        r = rj[0]
        self.assertEqual((r["ACT"], r["DOC"], r["RCD"], r["ICTL"], r["SEQ"]),
                         ("PICK", "SO-5005", "B08", 1, 1))     # order not released
        self.assertEqual(r["IMG"].split()[0][:1], "D")           # original record comes back
        self.assertEqual(r["BTCH"], 1)

    def test_every_reject_code_is_in_the_table(self):
        from legacy_wms.codes import REJECTS
        self.drop(1, [dict(rcpt("PAL-100"), USR="NOBODY"), dict(ACT="ZZZZ")])
        self.run2()
        for r in self.results("RJ"):
            self.assertIn(r["RCD"], REJECTS)

    def test_window_blocks_processing_but_releases_results(self):
        self.drop(1, [rcpt("PAL-100")])
        self.run_batch(DAY)                       # processed, results staged
        self.drop(2, [rcpt("PAL-101")])
        s = self.run_batch(NIGHT)
        self.assertTrue(s.window)
        self.assertEqual(s.files, 0)
        self.assertEqual(s.released, 1)           # staged results still go out
        self.assertIsNone(self.h.get("PAL", "PAL-101"))
        self.assertTrue(os.path.exists(self.h.p("IN", inbound_name(SRC, 2))))
        s = self.run_batch(("20260113", "0600"))  # window over
        self.assertEqual(s.files, 1)
        self.assertEqual(self.inv("PAL-101", "SKU-1002", "PP"), 10)

    def test_window_edges(self):
        for t, expect in (("2159", False), ("2200", True), ("0459", True), ("0500", False)):
            self.assertEqual(B.in_window(self.h, ("20260112", t)), expect, t)

    def test_bad_trailer_count_rejects_whole_file(self):
        text = build_inbound(SRC, 1, [rcpt("PAL-100"), rcpt("PAL-101")])
        lines = text.splitlines()
        lines[-1] = "T000003" + lines[-1][7:]            # says 3, holds 2
        self.h.p("IN", inbound_name(SRC, 1)).write_text("\n".join(lines) + "\n")
        s = self.run2()
        self.assertEqual(s.ok, 0)
        self.assertIsNone(self.h.get("PAL", "PAL-100"))
        self.assertEqual([r["RCD"] for r in self.results("RJ")], ["F03"])
        self.assertEqual(self.h.src[SRC]["NEXT"], 2)       # control number used up

    def test_hash_total_mismatch_rejects_whole_file(self):
        text = build_inbound(SRC, 1, [rcpt("PAL-100")])
        lines = text.splitlines()
        lines[-1] = lines[-1][:7] + "000000000999" + lines[-1][19:]
        self.h.p("IN", inbound_name(SRC, 1)).write_text("\n".join(lines) + "\n")
        self.run2()
        self.assertEqual([r["RCD"] for r in self.results("RJ")], ["F03"])

    def test_missing_trailer(self):
        text = build_inbound(SRC, 1, [rcpt("PAL-100")])
        self.h.p("IN", inbound_name(SRC, 1)).write_text("\n".join(text.splitlines()[:-1]) + "\n")
        self.run2()
        self.assertEqual([r["RCD"] for r in self.results("RJ")], ["F02"])

    def test_unknown_source_and_unreadable_file(self):
        self.h.p("IN", "STRANGER.00000001").write_text(build_inbound("STRANGER", 1, [RCPT]))
        self.h.p("IN", "GARBAGE").write_text("not a flat file\n")
        self.run_batch()
        self.assertEqual(sorted(a["ALCD"] for a in self.h.open_alarms()), ["A03", "A04"])
        self.assertEqual(len(os.listdir(self.h.p("ERR"))), 2)

    def test_file_name_must_match_header(self):
        self.h.p("IN", f"{SRC}.00000007").write_text(build_inbound(SRC, 1, [RCPT]))
        self.run2()
        self.assertEqual([r["RCD"] for r in self.results("RJ")], ["F07"])
        self.assertIsNone(self.h.get("PAL", "PAL-100"))

    def test_state_survives_restart(self):
        self.drop(1, [RCPT])
        self.run_batch()
        h2 = self.reload()
        self.assertEqual(h2.batch, 1)
        self.assertEqual(h2.get("INV", "PAL-100", "SKU-1002", "PP")["ONHD"], 40)
        self.assertEqual(h2.src[SRC]["NEXT"], 2)
        self.assertEqual(len(h2.ledger), 1)


if __name__ == "__main__":
    unittest.main()
