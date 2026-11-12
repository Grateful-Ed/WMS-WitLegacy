import unittest

from helpers import HostCase


def act(a, **kw):
    return dict(ACT=a, **kw)


class FlowTests(HostCase):
    def send(self, ictl, acts):
        self.drop(ictl, acts)
        self.run_batch()

    def reject_codes(self):
        self.run_batch()
        return [r["RCD"] for r in self.results("RJ")]

    def test_receive_then_putaway(self):
        self.send(1, [act("RCPT", DOC="ASN-1003", LIN=1, ITM="SKU-1002", QTY=100,
                          DOR="D03", TLC="PAL-100"),
                      act("RCPT", DOC="ASN-1003", LIN=2, ITM="SKU-1005", QTY=60,
                          DOR="D03", TLC="PAL-101")])
        self.assertEqual(self.h.get("ASH", "ASN-1003")["ASST"], "RC")
        self.assertEqual(self.h.get("PAL", "PAL-100")["LANE"], "STG-D03")
        bin_ = "ZA-02-01"
        before = self.inv(bin_, "SKU-1002", "AV")
        self.send(2, [act("PUTA", ITM="SKU-1002", QTY=100, FLC="PAL-100", TLC=bin_)])
        self.assertEqual(self.inv(bin_, "SKU-1002", "AV"), before + 100)
        self.assertEqual(self.inv("PAL-100", "SKU-1002", "PP"), 0)
        self.assertEqual(self.h.get("PAL", "PAL-100")["PLST"], "PC")
        self.assertEqual(self.reject_codes(), [])
        types = [r["LGTY"] for r in self.h.t["TRN"].values()][-3:]
        self.assertEqual(sorted(types), ["PU", "RC", "RC"])

    def test_putaway_completes_the_open_task(self):
        self.send(1, [act("PUTA", ITM="SKU-1003", QTY=60, FLC="PAL-001", TLC="ZA-01-03")])
        self.assertEqual(self.h.get("TSK", "TK-0018")["TKST"], "CP")
        self.assertEqual(self.h.get("TSK", "TK-0018")["CPBY"], "W-01")

    def test_receipt_rules(self):
        base = dict(DOC="ASN-1003", LIN=1, ITM="SKU-1002", DOR="D03")
        self.send(1, [act("RCPT", QTY=101, TLC="PAL-100", **base),          # over receipt
                      act("RCPT", QTY=5, TLC="PAL-001", **base),            # pallet exists
                      act("RCPT", DOC="ASN-1001", LIN=1, ITM="SKU-1004", QTY=5,
                          DOR="D01", TLC="PAL-102"),                         # not arrived
                      act("RCPT", DOC="ASN-0000", LIN=1, ITM="SKU-1002", QTY=5,
                          DOR="D03", TLC="PAL-103"),                         # unknown ASN
                      act("RCPT", QTY=5, TLC="PAL-104", **dict(base, DOR="D07"))])  # out door
        self.assertEqual(self.reject_codes(), ["B20", "B14", "B19", "B18", "B11"])

    def test_pick_pack_load_ship(self):
        # SO-5006: open, one line. Find its item and quantity from the host.
        line = self.h.get("OLN", "SO-5006", 1)
        item, qty = line["ITNO"], line["OQTY"]
        bin_ = next(k[0] for k, r in sorted(self.h.t["INV"].items())
                    if k[1] == item and k[2] == "AV" and r["ONHD"] >= qty)
        self.send(1, [act("RLSE", DOC="SO-5006"),
                      act("PICK", DOC="SO-5006", ITM=item, QTY=qty, FLC=bin_),
                      act("PACK", DOC="SO-5006")])
        o = self.h.get("OHD", "SO-5006")
        self.assertEqual((o["ORST"], o["DLNO"]), ("PK", "OD-7004"))
        self.assertEqual(self.inv("PK-SO-5006", item, "PK"), qty)
        self.send(2, [act("LOAD", DOC="OD-7004", TLC="LD-9002")])
        self.assertEqual(self.h.get("LDS", "LD-9002")["LDST"], "LG")
        self.send(3, [act("SHIP", DOC="LD-9002", DOR="D08", TLC="SEAL-77")])
        self.assertEqual(self.reject_codes(), [])
        self.assertEqual(self.h.get("LDS", "LD-9002")["SEAL"], "SEAL-77")
        for odno in ("OD-7003", "OD-7004"):
            self.assertEqual(self.h.get("DLV", odno)["DLST"], "SH")
        self.assertEqual(self.h.get("OHD", "SO-5009")["ORST"], "SH")
        self.assertEqual(self.h.get("OHD", "SO-5006")["ORST"], "SH")
        self.assertEqual(self.inv("PAL-007", "SKU-1006", "SL"), 0)
        self.assertEqual(self.inv("PK-SO-5006", item, "PK"), 0)
        self.assertEqual(self.h.get("APT", "APT-202")["APST"], "CP")

    def test_pick_rules(self):
        item = self.h.get("OLN", "SO-5001", 1)["ITNO"]        # SO-5001 is released
        self.send(1, [act("PICK", DOC="SO-5001", ITM=item, QTY=999, FLC="ZB-01-01"),   # over qty
                      act("PICK", DOC="SO-5001", ITM=item, QTY=1, FLC="NOPE"),         # no bin
                      act("PICK", DOC="SO-5001", ITM=item, QTY=1, FLC="ZA-01-05"),     # no stock
                      act("PICK", DOC="SO-5002", ITM="SKU-1999", QTY=1, FLC="ZB-01-01"),
                      act("PICK", DOC="SO-0000", ITM=item, QTY=1, FLC="ZB-01-01")])
        codes = self.reject_codes()
        self.assertEqual(codes, ["B09", "B03", "B06", "B09", "B07"])

    def test_pack_and_ship_need_the_right_status(self):
        self.send(1, [act("PACK", DOC="SO-5001"),                          # not picked
                      act("SHIP", DOC="LD-9002", DOR="D08"),               # load only planned
                      act("SHIP", DOC="LD-9001", DOR="D08"),               # wrong door
                      act("LOAD", DOC="OD-7003", TLC="LD-9001"),           # already on a load
                      act("SHIP", DOC="LD-9001", DOR="D07")])              # good
        self.assertEqual(self.reject_codes(), ["B12", "B25", "B11", "B12"])
        self.assertEqual(self.h.get("LDS", "LD-9001")["LDST"], "SH")

    def test_short_a_line_lets_order_finish_picking(self):
        o = "SO-5006"
        line = self.h.get("OLN", o, 1)
        self.send(1, [act("RLSE", DOC=o), act("SHRT", DOC=o, LIN=1)])
        self.assertEqual(self.h.get("OLN", o, 1)["LNST"], "SX")
        self.assertEqual(self.h.get("OHD", o)["ORST"], "PD")
        self.assertEqual(self.h.get("OLN", o, 1)["SQTY"], line["OQTY"])

    def test_count_variance_makes_exception_and_closes_count_task(self):
        sysq = self.inv("ZA-01-02", "SKU-1002", "AV")
        self.send(1, [act("CNTS", FLC="ZA-01-02", ITM="SKU-1002", QTY=sysq - 3, USR="W-07")])
        cc = self.h.get("CCN", "CC-401")
        self.assertEqual((cc["CCST"], cc["CVAR"], cc["SQTY"]), ("RC", -3, sysq))
        self.assertEqual(self.h.get("TSK", "TK-0021")["TKST"], "CP")
        new = [r for r in self.h.t["EXC"].values() if r["EXKD"] == "CV"]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["EXNO"], "EX-003")
        self.send(2, [act("ADJT", FLC="ZA-01-02", ITM="SKU-1002", QTY=3, SGN="-", RSN="01")])
        self.assertEqual(self.inv("ZA-01-02", "SKU-1002", "AV"), sysq - 3)

    def test_count_match_has_no_exception(self):
        sysq = self.inv("ZC-01-01", "SKU-1011", "AV")
        self.send(1, [act("CNTS", FLC="ZC-01-01", ITM="SKU-1011", QTY=sysq)])
        self.assertEqual(self.h.get("CCN", "CC-402")["CCST"], "CM")
        self.assertEqual(len(self.h.t["EXC"]), 2)

    def test_adjust_rules(self):
        self.send(1, [act("ADJT", FLC="ZA-01-01", ITM="SKU-1001", QTY=999999, SGN="-", RSN="02"),
                      act("ADJT", FLC="ZA-01-01", ITM="SKU-1001", QTY=1, SGN="+", RSN="99"),
                      act("ADJT", FLC="ZA-01-01", ITM="SKU-1001", QTY=100000, SGN="+", RSN="03"),
                      act("ADJT", FLC="ZA-01-01", ITM="SKU-1001", QTY=0, SGN="+", RSN="03")])
        self.assertEqual(self.reject_codes(), ["B06", "R06", "B05", "R05"])

    def test_exception_and_labor_acts(self):
        self.send(1, [act("EXCP", RSN="DM", FLG="AS", DOC="ASN-1003", SGN="H", TXT="Pallet wet"),
                      act("LABR", FLG="ST", RSN="RC", USR="W-02"),
                      act("LABR", FLG="ST", RSN="PU", USR="W-02"),     # already on a task
                      act("LABR", FLG="EN", QTY=12, USR="W-02"),
                      act("LABR", FLG="EN", QTY=1, USR="W-02")])       # none open
        exc = self.h.get("EXC", "EX-003")
        self.assertEqual((exc["EXKD"], exc["EXSV"], exc["EXRS"]), ("DM", "H", "PALLET WET"))
        lb = self.h.get("LBL", 1)
        self.assertEqual((lb["LBST"], lb["UNIT"], lb["TKCD"]), ("CL", 12, "RC"))
        self.assertEqual(self.reject_codes(), ["B16", "B17"])


if __name__ == "__main__":
    unittest.main()
