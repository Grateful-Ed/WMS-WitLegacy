import unittest

from helpers import HostCase, DAY
from legacy_wms import extract as X
from legacy_wms.fixed import LAYOUTS
from legacy_wms.flatfile import read_records


class ExtractTests(HostCase):
    def full(self):
        return {p.name[:3]: p for p in X.build_extract(self.h, DAY, "F")}

    def test_full_extract_has_every_table_and_every_row(self):
        paths = self.full()
        self.assertEqual(sorted(paths), sorted(LAYOUTS))
        for tbl, p in paths.items():
            hdr, rows, trl = read_records(p, tbl)
            self.assertEqual(hdr["MODE"], "F")
            self.assertEqual(trl["NREC"], len(rows))
            self.assertEqual(len(rows), len(self.h.t[tbl]), tbl)
            self.assertEqual({tuple(r[k] for k in __import__("legacy_wms.fixed").fixed.KEYS[tbl])
                              for r in rows}, set(self.h.t[tbl]), tbl)

    def test_extract_control_numbers_count_up(self):
        self.full()
        paths = X.build_extract(self.h, DAY, "F", ["ITM"])
        hdr = read_records(paths[0], "ITM")[0]
        self.assertEqual(hdr["XCTL"], 2)

    def test_extract_records_are_fixed_width_and_unpadded_numbers_zero_filled(self):
        p = self.full()["INV"]
        lines = p.read_text().splitlines()[1:-1]
        self.assertEqual(len({len(x) for x in lines}), 1)
        self.assertEqual(lines[0][-17:], "00000006000000000")   # ONHD then LCB, zero padded

    def test_delta_holds_only_changed_rows(self):
        self.full()
        self.drop(1, [dict(ACT="RCPT", DOC="ASN-1003", LIN=1, ITM="SKU-1002", QTY=40,
                           DOR="D03", TLC="PAL-100")])
        self.run_batch()
        deltas = {p.name[:3]: p for p in X.build_extract(self.h, DAY, "D")}
        got = {t: read_records(p, t)[1] for t, p in deltas.items()}
        self.assertEqual([r["PLNO"] for r in got["PAL"]], ["PAL-100"])
        self.assertEqual([(r["LCNO"], r["IVST"], r["ONHD"]) for r in got["INV"]],
                         [("PAL-100", "SKU-1002", "PP", 40)[0:1] + ("PP", 40)][:0] or
                         [("PAL-100", "PP", 40)])
        self.assertEqual([r["ASST"] for r in got["ASH"]], ["RG"])
        self.assertEqual(got["ITM"], [])           # nothing changed there
        self.assertEqual(len(got["TRN"]), 1)
        self.assertEqual(read_records(deltas["ITM"], "ITM")[0]["MODE"], "D")

    def test_full_plus_deltas_rebuild_the_host(self):
        base = {t: read_records(p, t)[1] for t, p in self.full().items()}
        state = {t: {tuple(r[k] for k in __import__("legacy_wms.fixed").fixed.KEYS[t]): r
                     for r in rows} for t, rows in base.items()}
        self.drop(1, [dict(ACT="RLSE", DOC="SO-5005"),
                      dict(ACT="LABR", FLG="ST", RSN="PI", USR="W-09")])
        self.run_batch()
        for t, p in ((p.name[:3], p) for p in X.build_extract(self.h, DAY, "D")):
            for r in read_records(p, t)[1]:
                state[t][tuple(r[k] for k in __import__("legacy_wms.fixed").fixed.KEYS[t])] = r
        for t in LAYOUTS:
            self.assertEqual(state[t], self.h.t[t], t)

    def test_delta_after_online_change_is_picked_up(self):
        self.full()
        from legacy_wms import ops
        from legacy_wms.fixed import DETAIL
        rec = DETAIL.blank()
        rec.update(ACT="RLSE", DOC="SO-5006", USR="W-01")
        ops.apply_act(self.h, rec, DAY)            # operator at the terminal
        paths = {p.name[:3]: p for p in X.build_extract(self.h, DAY, "D")}
        self.assertEqual([r["ORNO"] for r in read_records(paths["OHD"], "OHD")[1]], ["SO-5006"])

    def test_code_table_extract_decodes_status_codes(self):
        rows = read_records(self.full()["COD"], "COD")[1]
        codes = {(r["TBLN"], r["CODE"]): r["CDSC"] for r in rows}
        self.assertEqual(codes[("ORST", "RL")], "RELEASED")
        self.assertEqual(codes[("TASK", "PI")], "PICKING")


if __name__ == "__main__":
    unittest.main()
