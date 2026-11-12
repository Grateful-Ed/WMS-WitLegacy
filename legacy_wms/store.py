"""Host library: master files, control files, folders. All state is flat files."""
import os
from pathlib import Path

from .fixed import LAYOUTS, KEYS, SRC, LDG, ALM, EXT

DIRS = ["MASTER", "CTL", "IN", "STAGE", "OUT", "ARCH", "ERR", "LOG"]
SEQ_NAMES = ["EXC", "CCN", "LBL", "DLV", "TRN", "PAL", "TSK"]


def _atomic_write(path, text):
    tmp = str(path) + ".TMP"
    with open(tmp, "w", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


class Host:
    def __init__(self, root):
        self.root = Path(root)
        self.t = {n: {} for n in LAYOUTS}      # master tables: key tuple -> row
        self.src = {}                          # SRCID -> row
        self.ledger = []                       # list of LDG rows
        self.alarms = []                       # list of ALM rows
        self.ext = {}                          # TBLN -> row
        self.batch = 0                         # last batch number run
        self.stamp = 1                         # LCB stamp for changes now
        self.seq = {n: 0 for n in SEQ_NAMES}

    # -- paths
    def p(self, *parts):
        return self.root.joinpath(*parts)

    def init_dirs(self):
        for d in DIRS:
            self.p(d).mkdir(parents=True, exist_ok=True)

    # -- row helpers
    def key(self, table, row):
        return tuple(row[k] for k in KEYS[table])

    def put(self, table, row):
        """Insert or replace a master row; stamps LCB."""
        row["LCB"] = self.stamp
        self.t[table][self.key(table, row)] = row
        return row

    def get(self, table, *key):
        return self.t[table].get(tuple(key))

    def touch(self, row):
        row["LCB"] = self.stamp

    def next_seq(self, table):
        self.seq[table] += 1
        return self.seq[table]

    # -- persistence
    def save(self):
        for name, lay in LAYOUTS.items():
            rows = [self.t[name][k] for k in sorted(self.t[name])]
            _atomic_write(self.p("MASTER", name + ".DAT"),
                          "".join(lay.pack(r) + "\n" for r in rows))
        srcs = [self.src[k] for k in sorted(self.src)]
        _atomic_write(self.p("CTL", "SRC.DAT"), "".join(SRC.pack(r) + "\n" for r in srcs))
        _atomic_write(self.p("CTL", "LEDGER.DAT"),
                      "".join(LDG.pack(r) + "\n" for r in self.ledger))
        _atomic_write(self.p("CTL", "ALARM.DAT"),
                      "".join(ALM.pack(r) + "\n" for r in self.alarms))
        exts = [self.ext[k] for k in sorted(self.ext)]
        _atomic_write(self.p("CTL", "EXTCTL.DAT"), "".join(EXT.pack(r) + "\n" for r in exts))
        _atomic_write(self.p("CTL", "BATCH.CTL"), f"{self.batch:08d}\n")
        _atomic_write(self.p("CTL", "SEQ.CTL"),
                      "".join(f"{n:<4}{self.seq[n]:08d}\n" for n in SEQ_NAMES))

    def load(self):
        for name, lay in LAYOUTS.items():
            self.t[name] = {}
            path = self.p("MASTER", name + ".DAT")
            if path.exists():
                for line in path.read_text().splitlines():
                    if line.strip():
                        row = lay.unpack(line)
                        self.t[name][self.key(name, row)] = row

        def rd(fname, lay):
            path = self.p("CTL", fname)
            if not path.exists():
                return []
            return [lay.unpack(x) for x in path.read_text().splitlines() if x.strip()]

        self.src = {r["SRCID"]: r for r in rd("SRC.DAT", SRC)}
        self.ledger = rd("LEDGER.DAT", LDG)
        self.alarms = rd("ALARM.DAT", ALM)
        self.ext = {r["TBLN"]: r for r in rd("EXTCTL.DAT", EXT)}
        path = self.p("CTL", "BATCH.CTL")
        if path.exists():
            self.batch = int(path.read_text().strip())
        path = self.p("CTL", "SEQ.CTL")
        if path.exists():
            for ln in path.read_text().splitlines():
                if ln.strip():
                    self.seq[ln[:4].strip()] = int(ln[4:12])
        self.stamp = self.batch + 1

    @classmethod
    def open(cls, root):
        h = cls(root)
        h.init_dirs()
        h.load()
        return h

    # -- control helpers
    def add_source(self, srcid):
        srcid = srcid.upper()
        if srcid not in self.src:
            self.src[srcid] = {"SRCID": srcid, "NEXT": 1, "LAST": 0, "OCF": 0, "ORJ": 0}
        return self.src[srcid]

    def raise_alarm(self, code, srcid, ictl, text, now):
        for a in self.alarms:
            if (a["ALCD"], a["SRCID"], a["ICTL"], a["ALST"]) == (code, srcid, ictl, "OP"):
                return a  # already open: do not duplicate
        a = {"ALNO": len(self.alarms) + 1, "ALCD": code, "ALDT": now[0], "ALTM": int(now[1]),
             "SRCID": srcid, "ICTL": ictl, "ALST": "OP", "ALTX": text[:40]}
        self.alarms.append(a)
        return a

    def open_alarms(self):
        return [a for a in self.alarms if a["ALST"] == "OP"]
