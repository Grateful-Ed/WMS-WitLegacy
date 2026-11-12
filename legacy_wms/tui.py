"""Character-cell terminal UI: 80x24, menus, function keys. F3=Exit F12=Back.

Operators work in the host directly (online). Online acts use the same
rules as the batch job (ops.apply_act) and show reject codes on line 23.
"""
from . import codes as C
from . import batch as B
from . import extract as X
from . import ops
from .fixed import DETAIL

W, H = 80, 24


class Terminal:
    """Base class. show() draws a screen; ask() reads one input line.
    ask() returns text, or 'F3' / 'F12' for those function keys."""

    def show(self, lines, msg=""):
        raise NotImplementedError

    def ask(self, label):
        raise NotImplementedError


class ScriptedTerminal(Terminal):
    """Feeds keys from a list. Used by tests and demos. Keeps every screen."""

    def __init__(self, keys):
        self.keys = list(keys)
        self.screens = []
        self.cur = []

    def show(self, lines, msg=""):
        self.cur = list(lines) + ([msg] if msg else [])
        self.screens.append("\n".join(self.cur))

    def ask(self, label):
        return self.keys.pop(0) if self.keys else "F3"

    def text(self):
        return "\n".join(self.screens)


class CursesTerminal(Terminal):
    def __init__(self, scr):
        import curses
        self.c = curses
        self.s = scr
        curses.curs_set(1)
        if curses.has_colors():
            curses.start_color()
            curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
            self.s.bkgd(" ", curses.color_pair(1))

    def show(self, lines, msg=""):
        self.s.erase()
        for i, ln in enumerate(lines[:H - 2]):
            self.s.addstr(i, 0, ln[:W])
        if msg:
            self.s.addstr(H - 2, 0, msg[:W], self.c.A_REVERSE)
        self.s.addstr(H - 1, 0, "F3=Exit  F12=Back  ENTER=Submit"[:W])
        self.s.refresh()

    def ask(self, label):
        c = self.c
        row = min(H - 3, 21)
        self.s.addstr(row, 0, label[:W])
        self.s.refresh()
        buf = ""
        while True:
            k = self.s.get_wch()
            if k == c.KEY_F0 + 3:
                return "F3"
            if k in (c.KEY_F0 + 12, "\x1b"):
                return "F12"
            if k in ("\n", "\r", c.KEY_ENTER):
                return buf
            if k in (c.KEY_BACKSPACE, "\x7f", "\b"):
                buf = buf[:-1]
            elif isinstance(k, str) and k.isprintable():
                buf += k
            self.s.addstr(row, len(label), (buf + " ")[:W - len(label)])
            self.s.refresh()


def frame(title, body, host_name="WMSLEG"):
    head = f"{title:<56}{host_name:>8}  "
    lines = [head[:W].ljust(W), "-" * W] + list(body)
    return [x[:W] for x in lines]


class App:
    def __init__(self, host, term, clock):
        self.h = host
        self.t = term
        self.clock = clock

    # -- helpers
    def screen(self, title, body, msg=""):
        self.t.show(frame(title, body), msg)

    def form(self, title, fields, msg=""):
        """fields: (key, label, width, kind). Returns dict or None on F12/F3."""
        vals = {}
        for key, label, width, kind in fields:
            body = [f"  {l:<22}: {vals.get(k, '')}" for k, l, _, _ in fields]
            self.screen(title, body, msg)
            ans = self.t.ask(f"{label} ({width}) ===> ")
            if ans in ("F3", "F12"):
                return None
            ans = ans.strip().upper()
            if kind == "N":
                if ans == "":
                    ans = "0"
                if not ans.isdigit():
                    return self.form(title, fields, "NUMERIC FIELD REQUIRED")
                ans = int(ans)
            vals[key] = ans
        return vals

    def do_act(self, title, act, fields, extra=None):
        data = self.form(title, fields)
        if data is None:
            return
        rec = DETAIL.blank()
        rec.update({"REC": "D", "ACT": act})
        rec.update(extra or {})
        rec.update(data)
        now = self.clock()
        try:
            ops.apply_act(self.h, rec, now)
            self.h.save()
            msg = "ACT ACCEPTED"
        except ops.Reject as e:
            msg = f"REJECT {e.code} {C.REJECTS.get(e.code, '')}"
        self.screen(title, ["", "  " + msg, "", "  PRESS ENTER"], msg)
        self.t.ask("===> ")

    # -- menus
    def run(self):
        menu = [
            ("1", "RECEIVING", self.m_receive), ("2", "PUTAWAY", self.m_putaway),
            ("3", "INVENTORY", self.m_inventory), ("4", "ORDERS", self.m_orders),
            ("5", "PICKING", self.m_pick), ("6", "PACKING", self.m_pack),
            ("7", "SHIPPING", self.m_ship), ("8", "CYCLE COUNTS", self.m_count),
            ("9", "EXCEPTIONS", self.m_exceptions), ("10", "LABOR", self.m_labor),
            ("11", "BATCH CONTROL", self.m_batch),
        ]
        msg = ""
        while True:
            body = [""] + [f"   {n:>2}. {t}" for n, t, _ in menu] + [""]
            body += [f"   BATCH {self.h.batch:08d}   OPEN ALARMS {len(self.h.open_alarms()):03d}"]
            self.screen("WAREHOUSE MANAGEMENT SYSTEM - MAIN MENU", body, msg)
            sel = self.t.ask("SELECTION ===> ").strip()
            msg = ""
            if sel in ("F3", "F12"):
                return
            fn = {n: f for n, _, f in menu}.get(sel)
            if fn:
                fn()
            else:
                msg = "INVALID SELECTION"

    def m_receive(self):
        self.do_act("RECEIVING", "RCPT", [
            ("DOC", "ASN NO", 12, "A"), ("LIN", "ASN LINE", 4, "N"),
            ("ITM", "ITEM", 20, "A"), ("QTY", "QUANTITY", 9, "N"),
            ("DOR", "DOOR", 6, "A"), ("TLC", "NEW PALLET NO", 12, "A"),
            ("USR", "USER", 8, "A")])

    def m_putaway(self):
        self.do_act("PUTAWAY", "PUTA", [
            ("ITM", "ITEM", 20, "A"), ("QTY", "QUANTITY", 9, "N"),
            ("FLC", "FROM PALLET", 12, "A"), ("TLC", "TO BIN", 12, "A"),
            ("USR", "USER", 8, "A")])

    def m_inventory(self):
        while True:
            self.screen("INVENTORY", ["", "   1. INQUIRY BY ITEM", "   2. INQUIRY BY BIN",
                                      "   3. ADJUST"])
            sel = self.t.ask("SELECTION ===> ").strip()
            if sel in ("F3", "F12"):
                return
            if sel == "1":
                d = self.form("INVENTORY BY ITEM", [("k", "ITEM", 20, "A")])
                if d:
                    self.list_inv(lambda k: k[1] == d["k"], "ITEM " + d["k"])
            elif sel == "2":
                d = self.form("INVENTORY BY BIN", [("k", "BIN", 12, "A")])
                if d:
                    self.list_inv(lambda k: k[0] == d["k"], "BIN " + d["k"])
            elif sel == "3":
                self.do_act("INVENTORY ADJUST", "ADJT", [
                    ("ITM", "ITEM", 20, "A"), ("FLC", "BIN", 12, "A"),
                    ("QTY", "QUANTITY", 9, "N"), ("SGN", "SIGN (+/-)", 1, "A"),
                    ("RSN", "REASON 01-05", 2, "A"), ("USR", "USER", 8, "A")])

    def list_inv(self, pred, title):
        body = ["  BIN          ITEM                 ST      ON HAND"]
        for k, r in sorted(self.h.t["INV"].items()):
            if pred(k):
                body.append(f"  {r['LCNO']:<12} {r['ITNO']:<20} {r['IVST']}  {r['ONHD']:>9}")
        self.screen("INVENTORY - " + title, body[:20])
        self.t.ask("ENTER ===> ")

    def m_orders(self):
        while True:
            body = ["  ORDER    CUSTOMER                       ST WAVE     DELIVERY"]
            for k, r in sorted(self.h.t["OHD"].items())[:18]:
                body.append(f"  {r['ORNO']:<8} {r['CUNM']:<30} {r['ORST']} {r['WVNO']:<8} {r['DLNO']}")
            body.append("  TYPE ORDER NO TO RELEASE, F12=BACK")
            self.screen("WORK WITH ORDERS", body)
            sel = self.t.ask("ORDER TO RELEASE ===> ").strip().upper()
            if sel in ("F3", "F12", ""):
                return
            self.do_act("RELEASE ORDER", "RLSE", [("USR", "USER", 8, "A")], {"DOC": sel})

    def m_pick(self):
        self.do_act("PICKING", "PICK", [
            ("DOC", "ORDER", 12, "A"), ("LIN", "LINE NO (0=ANY)", 4, "N"),
            ("ITM", "ITEM", 20, "A"), ("QTY", "QUANTITY", 9, "N"),
            ("FLC", "FROM BIN", 12, "A"), ("USR", "USER", 8, "A")])

    def m_pack(self):
        self.do_act("PACKING", "PACK", [("DOC", "ORDER", 12, "A"), ("USR", "USER", 8, "A")])

    def m_ship(self):
        while True:
            self.screen("SHIPPING", ["", "   1. PUT DELIVERY ON LOAD", "   2. SHIP LOAD"])
            sel = self.t.ask("SELECTION ===> ").strip()
            if sel in ("F3", "F12"):
                return
            if sel == "1":
                self.do_act("LOAD DELIVERY", "LOAD", [
                    ("DOC", "DELIVERY NO", 12, "A"), ("TLC", "LOAD NO", 12, "A"),
                    ("USR", "USER", 8, "A")])
            elif sel == "2":
                self.do_act("SHIP LOAD", "SHIP", [
                    ("DOC", "LOAD NO", 12, "A"), ("DOR", "DOOR", 6, "A"),
                    ("TLC", "SEAL NO", 12, "A"), ("USR", "USER", 8, "A")])

    def m_count(self):
        self.do_act("CYCLE COUNT", "CNTS", [
            ("FLC", "BIN", 12, "A"), ("ITM", "ITEM", 20, "A"),
            ("QTY", "COUNTED QTY", 9, "N"), ("USR", "USER", 8, "A")])

    def m_exceptions(self):
        while True:
            body = ["  NO     KD EN ENTITY       SV ST DATE     REASON"]
            for k, r in sorted(self.h.t["EXC"].items())[-16:]:
                body.append(f"  {r['EXNO']:<6} {r['EXKD']} {r['EXEN']} {r['EXEI']:<12} "
                            f"{r['EXSV']}  {r['EXST']} {r['EXDT']} {r['EXRS'][:22]}")
            body.append("  1=LOG NEW  OR TYPE EXCEPTION NO TO CLOSE")
            self.screen("EXCEPTIONS", body)
            sel = self.t.ask("OPTION ===> ").strip().upper()
            if sel in ("F3", "F12", ""):
                return
            if sel == "1":
                self.do_act("LOG EXCEPTION", "EXCP", [
                    ("RSN", "KIND DM LB CV SR OR OT", 2, "A"),
                    ("FLG", "ENTITY AS BN OR IT OT", 2, "A"),
                    ("DOC", "ENTITY ID", 12, "A"), ("SGN", "SEVERITY L M H", 1, "A"),
                    ("TXT", "REASON TEXT", 40, "A"), ("USR", "USER", 8, "A")])
            elif ops.close_exception(self.h, sel):
                self.h.save()

    def m_labor(self):
        while True:
            body = ["  1=START TASK  2=END TASK", "",
                    "  NO       USER     TK START          END            UNITS ST"]
            for k, r in sorted(self.h.t["LBL"].items())[-14:]:
                body.append(f"  {r['LBNO']:08d} {r['USNO']:<8} {r['TKCD']} "
                            f"{r['SDAT']}{r['STIM']:04d} {r['EDAT']}{r['ETIM']:04d} "
                            f"{r['UNIT']:>7} {r['LBST']}")
            self.screen("LABOR", body)
            sel = self.t.ask("OPTION ===> ").strip()
            if sel in ("F3", "F12", ""):
                return
            if sel == "1":
                self.do_act("START TASK", "LABR", [
                    ("USR", "USER", 8, "A"), ("RSN", "TASK (RC PU PI PK SH CN OT)", 2, "A")],
                    {"FLG": "ST"})
            elif sel == "2":
                self.do_act("END TASK", "LABR", [
                    ("USR", "USER", 8, "A"), ("QTY", "UNITS DONE", 9, "N")], {"FLG": "EN"})

    def m_batch(self):
        while True:
            body = ["", "   1. RUN BATCH NOW", "   2. BUILD DELTA EXTRACT",
                    "   3. BUILD FULL EXTRACT", "   4. ALARMS", "   5. SKIP GAP FOR SOURCE",
                    "   6. CLEAR ALARM", "   7. REGISTER SOURCE", "   8. FILE QUEUES",
                    "   9. BATCH LOG", "",
                    f"   BATCH {self.h.batch:08d}   WINDOW {B.get_window(self.h)[0]:04d}-"
                    f"{B.get_window(self.h)[1]:04d}"]
            self.screen("BATCH CONTROL", body)
            sel = self.t.ask("SELECTION ===> ").strip()
            if sel in ("F3", "F12"):
                return
            now = self.clock()
            msg = ""
            if sel == "1":
                s = B.run_batch(self.h, now, "OPER")
                msg = ("WINDOW - INBOUND NOT PROCESSED. " if s.window else "") + \
                    f"OK {s.ok} REJ {s.rej} HELD {s.held} DUP {s.dups}"
            elif sel in ("2", "3"):
                ps = X.build_extract(self.h, now, "D" if sel == "2" else "F")
                self.h.save()
                msg = f"{len(ps)} EXTRACT FILES WRITTEN"
            elif sel == "4":
                self.show_alarms()
            elif sel == "5":
                d = self.form("SKIP GAP", [("s", "SOURCE", 8, "A")])
                if d:
                    msg = "GAP SKIPPED" if B.skip_gap(self.h, d["s"], now) else "NO GAP FOUND"
            elif sel == "6":
                d = self.form("CLEAR ALARM", [("n", "ALARM NO", 8, "N")])
                if d:
                    msg = "ALARM CLEARED" if B.clear_alarm(self.h, d["n"]) else "NOT FOUND"
            elif sel == "7":
                d = self.form("REGISTER SOURCE", [("s", "SOURCE", 8, "A")])
                if d and d["s"]:
                    self.h.add_source(d["s"])
                    self.h.save()
                    msg = "SOURCE REGISTERED"
            elif sel == "8":
                self.show_queues()
            elif sel == "9":
                self.show_log()
            if msg:
                self.screen("BATCH CONTROL", ["", "  " + msg, "", "  PRESS ENTER"], msg)
                self.t.ask("===> ")

    def show_alarms(self):
        body = ["  NO       CD  DATE     SOURCE   CTL      ST TEXT"]
        for a in self.h.alarms[-17:]:
            body.append(f"  {a['ALNO']:08d} {a['ALCD']} {a['ALDT']} {a['SRCID']:<8} "
                        f"{a['ICTL']:08d} {a['ALST']} {a['ALTX']}")
        self.screen("OPERATOR ALARMS", body)
        self.t.ask("ENTER ===> ")

    def show_queues(self):
        import os
        body = []
        for d in ("IN", "STAGE", "OUT", "ERR"):
            names = sorted(os.listdir(self.h.p(d)))
            body.append(f"  {d:<6} {len(names):>4} FILES  " + " ".join(names[:3]))
        self.screen("FILE QUEUES", body)
        self.t.ask("ENTER ===> ")

    def show_log(self):
        p = self.h.p("LOG", "BATCH.LOG")
        lines = p.read_text().splitlines()[-18:] if p.exists() else []
        self.screen("BATCH LOG", ["  " + x for x in lines])
        self.t.ask("ENTER ===> ")


def run_curses(host, clock):
    import curses

    def main(scr):
        App(host, CursesTerminal(scr), clock).run()

    curses.wrapper(main)
