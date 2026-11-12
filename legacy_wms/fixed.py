"""Fixed-width record layouts. No nulls: spaces for text, zeros for numbers."""
import datetime


class LayoutError(Exception):
    def __init__(self, code, text=""):
        super().__init__(f"{code} {text}".strip())
        self.code = code


def valid_date(s):
    if s == "00000000":
        return True
    if len(s) != 8 or not s.isdigit():
        return False
    try:
        datetime.date(int(s[:4]), int(s[4:6]), int(s[6:]))
    except ValueError:
        return False
    return True


class Layout:
    """fields: list of (name, width, kind). kind: A text, N unsigned number,
    S signed number (sign char then digits), D date YYYYMMDD."""

    def __init__(self, name, fields):
        self.name = name
        self.fields = fields
        self.width = sum(w for _, w, _ in fields)
        self.names = [n for n, _, _ in fields]

    def offset(self, name):
        pos = 0
        for n, w, _ in self.fields:
            if n == name:
                return pos, w
            pos += w
        raise KeyError(name)

    def blank(self):
        return {n: ("" if k == "A" else "00000000" if k == "D" else 0)
                for n, _, k in self.fields}

    def pack(self, row):
        out = []
        for n, w, k in self.fields:
            v = row.get(n)
            if k == "A":
                s = "" if v is None else str(v)
                if len(s) > w:
                    raise ValueError(f"{self.name}.{n} value too long: {s!r} (max {w})")
                out.append(s.ljust(w))
            elif k == "N":
                i = 0 if v is None else int(v)
                if i < 0 or len(str(i)) > w:
                    raise ValueError(f"{self.name}.{n} number out of range: {i}")
                out.append(str(i).zfill(w))
            elif k == "S":
                i = 0 if v is None else int(v)
                if len(str(abs(i))) > w - 1:
                    raise ValueError(f"{self.name}.{n} number out of range: {i}")
                out.append(("-" if i < 0 else "+") + str(abs(i)).zfill(w - 1))
            else:  # D
                s = "00000000" if not v else str(v)
                if not valid_date(s):
                    raise ValueError(f"{self.name}.{n} bad date: {s!r}")
                out.append(s)
        return "".join(out)

    def unpack(self, line):
        line = line.rstrip("\r\n")
        if len(line) != self.width:
            raise LayoutError("R01", f"{self.name} length {len(line)} not {self.width}")
        row, pos = {}, 0
        for n, w, k in self.fields:
            raw = line[pos:pos + w]
            pos += w
            if k == "A":
                row[n] = raw.rstrip()
            elif k == "N":
                if not raw.isdigit():
                    raise LayoutError("R03", f"{n}")
                row[n] = int(raw)
            elif k == "S":
                if raw[0] not in "+-" or not raw[1:].isdigit():
                    raise LayoutError("R03", f"{n}")
                row[n] = int(raw)
            else:
                if not valid_date(raw):
                    raise LayoutError("R04", f"{n}")
                row[n] = raw
        return row


# ---- master tables -------------------------------------------------------
def _L(name, *fields):
    return Layout(name, list(fields) + [("LCB", 8, "N")])


LAYOUTS = {
    "WHS": _L("WHS", ("WHID", 8, "A"), ("WHNM", 30, "A"), ("WHTZ", 4, "A"),
              ("SDAT", 8, "D"), ("STIM", 4, "N")),
    "ZON": _L("ZON", ("ZNID", 2, "A"), ("ZNDS", 20, "A"), ("ZNTY", 2, "A")),
    "DEP": _L("DEP", ("DPID", 3, "A"), ("DPDS", 20, "A")),
    "ITM": _L("ITM", ("ITNO", 20, "A"), ("ITDS", 30, "A"), ("IUOM", 2, "A"),
              ("ICSQ", 5, "N"), ("IWGT", 7, "N"), ("IPBN", 12, "A"), ("ITST", 2, "A")),
    "LOC": _L("LOC", ("LCNO", 12, "A"), ("LCZN", 2, "A"), ("LCAI", 2, "A"),
              ("LCPS", 2, "A"), ("LCCP", 9, "N"), ("LCST", 2, "A")),
    "DOR": _L("DOR", ("DRNO", 6, "A"), ("DRDS", 20, "A"), ("DRDI", 2, "A"),
              ("DRST", 2, "A"), ("DRRT", 2, "A"), ("DRRF", 12, "A")),
    "APT": _L("APT", ("APNO", 8, "A"), ("DRNO", 6, "A"), ("ADIR", 2, "A"),
              ("RFTY", 2, "A"), ("RFNO", 12, "A"), ("SDAT", 8, "D"), ("STIM", 4, "N"),
              ("EDAT", 8, "D"), ("ETIM", 4, "N"), ("APST", 2, "A")),
    "ASH": _L("ASH", ("ASNO", 8, "A"), ("SUPL", 30, "A"), ("ASST", 2, "A"),
              ("DRNO", 6, "A"), ("APNO", 8, "A"), ("ARDT", 8, "D"), ("ARTM", 4, "N")),
    "ASL": _L("ASL", ("ASNO", 8, "A"), ("LNNO", 4, "N"), ("ITNO", 20, "A"),
              ("EXQT", 9, "N"), ("RCQT", 9, "N")),
    "PAL": _L("PAL", ("PLNO", 8, "A"), ("PDIR", 2, "A"), ("LANE", 8, "A"),
              ("PLST", 2, "A"), ("ASNO", 8, "A"), ("ASLN", 4, "N"), ("DLNO", 8, "A")),
    "INV": _L("INV", ("LCNO", 12, "A"), ("ITNO", 20, "A"), ("IVST", 2, "A"),
              ("ONHD", 9, "N")),
    "TRN": _L("TRN", ("LGNO", 9, "A"), ("LGDT", 8, "D"), ("LGTM", 4, "N"),
              ("LGTY", 2, "A"), ("ITNO", 20, "A"), ("FLOC", 12, "A"), ("TLOC", 12, "A"),
              ("QTY", 9, "N"), ("REF", 12, "A")),
    "OHD": _L("OHD", ("ORNO", 8, "A"), ("CUNM", 30, "A"), ("ORST", 2, "A"),
              ("WVNO", 8, "A"), ("DLNO", 8, "A"), ("SHDT", 8, "D")),
    "OLN": _L("OLN", ("ORNO", 8, "A"), ("LNNO", 4, "N"), ("ITNO", 20, "A"),
              ("OQTY", 9, "N"), ("PQTY", 9, "N"), ("SQTY", 9, "N"), ("LNST", 2, "A")),
    "WAV": _L("WAV", ("WVNO", 8, "A"), ("WVST", 2, "A"), ("RLDT", 8, "D"),
              ("RLTM", 4, "N")),
    "DLV": _L("DLV", ("DLNO", 8, "A"), ("ORNO", 8, "A"), ("DLST", 2, "A"),
              ("LDNO", 8, "A"), ("SHDT", 8, "D"), ("SHTM", 4, "N")),
    "LDS": _L("LDS", ("LDNO", 8, "A"), ("DRNO", 6, "A"), ("CARR", 30, "A"),
              ("LDST", 2, "A"), ("APNO", 8, "A"), ("SEAL", 12, "A"), ("SHDT", 8, "D"),
              ("SHTM", 4, "N")),
    "TSK": _L("TSK", ("TKNO", 8, "A"), ("TKTY", 2, "A"), ("TKST", 2, "A"),
              ("ZNID", 2, "A"), ("ASGN", 8, "A"), ("WVNO", 8, "A"), ("ORNO", 8, "A"),
              ("LNNO", 4, "N"), ("ITNO", 20, "A"), ("QTY", 9, "N"), ("FBIN", 12, "A"),
              ("TBIN", 12, "A"), ("PLNO", 8, "A"), ("CCNO", 8, "A"), ("BNNO", 12, "A"),
              ("CRDT", 8, "D"), ("CRTM", 4, "N"), ("CPDT", 8, "D"), ("CPTM", 4, "N"),
              ("CPBY", 8, "A")),
    "CCN": _L("CCN", ("CCNO", 8, "A"), ("BNNO", 12, "A"), ("ITNO", 20, "A"),
              ("CCST", 2, "A"), ("TKNO", 8, "A"), ("SQTY", 9, "N"), ("CQTY", 9, "N"),
              ("CVAR", 10, "S")),
    "EXC": _L("EXC", ("EXNO", 8, "A"), ("EXKD", 2, "A"), ("EXEN", 2, "A"),
              ("EXEI", 12, "A"), ("EXSV", 1, "A"), ("EXRS", 60, "A"), ("EXST", 2, "A"),
              ("EXDT", 8, "D"), ("EXTM", 4, "N"), ("EXBY", 8, "A")),
    "USR": _L("USR", ("USNO", 8, "A"), ("USNM", 30, "A"), ("USDP", 3, "A"),
              ("USZN", 2, "A"), ("USSH", 2, "A"), ("USST", 2, "A")),
    "LBL": _L("LBL", ("LBNO", 8, "N"), ("USNO", 8, "A"), ("TKCD", 2, "A"),
              ("SDAT", 8, "D"), ("STIM", 4, "N"), ("EDAT", 8, "D"), ("ETIM", 4, "N"),
              ("UNIT", 9, "N"), ("LBST", 2, "A")),
    "COD": _L("COD", ("TBLN", 6, "A"), ("CODE", 3, "A"), ("CDSC", 40, "A")),
}
KEYS = {
    "WHS": ("WHID",), "ZON": ("ZNID",), "DEP": ("DPID",), "ITM": ("ITNO",),
    "LOC": ("LCNO",), "DOR": ("DRNO",), "APT": ("APNO",), "ASH": ("ASNO",),
    "ASL": ("ASNO", "LNNO"), "PAL": ("PLNO",), "INV": ("LCNO", "ITNO", "IVST"),
    "TRN": ("LGNO",), "OHD": ("ORNO",), "OLN": ("ORNO", "LNNO"), "WAV": ("WVNO",),
    "DLV": ("DLNO",), "LDS": ("LDNO",), "TSK": ("TKNO",), "CCN": ("CCNO",),
    "EXC": ("EXNO",), "USR": ("USNO",), "LBL": ("LBNO",), "COD": ("TBLN", "CODE"),
}

# ---- control tables ------------------------------------------------------
SRC = Layout("SRC", [("SRCID", 8, "A"), ("NEXT", 8, "N"), ("LAST", 8, "N"),
                     ("OCF", 8, "N"), ("ORJ", 8, "N")])
LDG = Layout("LDG", [("SRCID", 8, "A"), ("ICTL", 8, "N"), ("CKSM", 8, "A"),
                     ("BTCH", 8, "N"), ("DISP", 2, "A"), ("NREC", 6, "N"),
                     ("NOK", 6, "N"), ("NRJ", 6, "N"), ("PDAT", 8, "D")])
ALM = Layout("ALM", [("ALNO", 8, "N"), ("ALCD", 3, "A"), ("ALDT", 8, "D"),
                     ("ALTM", 4, "N"), ("SRCID", 8, "A"), ("ICTL", 8, "N"),
                     ("ALST", 2, "A"), ("ALTX", 40, "A")])
EXT = Layout("EXT", [("TBLN", 3, "A"), ("XCTL", 8, "N"), ("LBCH", 8, "N")])

# ---- integration file records (all padded to RECLEN) ---------------------
DETAIL = Layout("DTL", [
    ("REC", 1, "A"), ("SEQ", 6, "N"), ("ACT", 4, "A"), ("USR", 8, "A"),
    ("DOC", 12, "A"), ("LIN", 4, "N"), ("ITM", 20, "A"), ("QTY", 9, "N"),
    ("SGN", 1, "A"), ("FLC", 12, "A"), ("TLC", 12, "A"), ("DOR", 6, "A"),
    ("RSN", 2, "A"), ("FLG", 2, "A"), ("ADT", 8, "D"), ("ATM", 4, "N"),
    ("TXT", 40, "A"),
])
RECLEN = DETAIL.width
HEADER = Layout("HDR", [("REC", 1, "A"), ("SRC", 8, "A"), ("ICTL", 8, "N"),
                        ("FDAT", 8, "D"), ("FTIM", 4, "N")])
TRAILER = Layout("TRL", [("REC", 1, "A"), ("NREC", 6, "N"), ("HASH", 12, "N")])

CONF = Layout("CNF", [("REC", 1, "A"), ("ICTL", 8, "N"), ("SEQ", 6, "N"),
                      ("ACT", 4, "A"), ("DOC", 12, "A"), ("LIN", 4, "N"),
                      ("ITM", 20, "A"), ("QTY", 9, "N"), ("RSLT", 2, "A"),
                      ("BTCH", 8, "N"), ("PDAT", 8, "D")])
REJ = Layout("REJ", [("REC", 1, "A"), ("ICTL", 8, "N"), ("SEQ", 6, "N"),
                     ("ACT", 4, "A"), ("DOC", 12, "A"), ("LIN", 4, "N"),
                     ("ITM", 20, "A"), ("QTY", 9, "N"), ("RCD", 3, "A"),
                     ("BTCH", 8, "N"), ("PDAT", 8, "D"), ("IMG", RECLEN, "A")])
OUT_HEADER = Layout("OHD", [("REC", 1, "A"), ("SRC", 8, "A"), ("OCTL", 8, "N"),
                            ("KIND", 2, "A"), ("BTCH", 8, "N"), ("PDAT", 8, "D")])
OUT_TRAILER = Layout("OTR", [("REC", 1, "A"), ("NREC", 8, "N")])
EXT_HEADER = Layout("XHD", [("REC", 1, "A"), ("TBLN", 3, "A"), ("XCTL", 8, "N"),
                            ("MODE", 1, "A"), ("ASOF", 8, "D"), ("BTCH", 8, "N"),
                            ("FBCH", 8, "N")])
