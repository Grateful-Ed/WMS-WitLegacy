"""Scheduled EXTRACT files: full or delta, fixed width, one file per table.

First line is the header, last line is the trailer, lines between are table
records. Header and trailer have their own fixed widths (not padded)."""
from .fixed import LAYOUTS, EXT_HEADER, OUT_TRAILER, KEYS

from .fixed import LAYOUTS as _L
EXTRACT_TABLES = sorted(_L)


def extract_name(tbl, xctl):
    return f"{tbl}.X{xctl:08d}"


def build_extract(h, now, mode="D", tables=None):
    """Write extract files into OUT. mode 'F' full, 'D' delta.
    Delta = rows whose last-change batch (LCB) is newer than the last extract.
    A delta may repeat a row; readers upsert by key. Returns list of paths."""
    assert mode in ("F", "D")
    paths = []
    for tbl in tables or EXTRACT_TABLES:
        ctl = h.ext.get(tbl) or {"TBLN": tbl, "XCTL": 0, "LBCH": 0}
        if mode == "F":
            rows = [h.t[tbl][k] for k in sorted(h.t[tbl])]
            fbch = 0
        else:
            rows = [h.t[tbl][k] for k in sorted(h.t[tbl]) if h.t[tbl][k]["LCB"] > ctl["LBCH"]]
            fbch = ctl["LBCH"]
        ctl["XCTL"] += 1
        ctl["LBCH"] = h.batch
        h.ext[tbl] = ctl
        lay = LAYOUTS[tbl]
        head = EXT_HEADER.pack({"REC": "H", "TBLN": tbl, "XCTL": ctl["XCTL"], "MODE": mode,
                                "ASOF": now[0], "BTCH": h.batch, "FBCH": fbch})
        lines = [head]
        lines += [lay.pack(r) for r in rows]
        lines.append(OUT_TRAILER.pack({"REC": "T", "NREC": len(rows)}))
        path = h.p("OUT", extract_name(tbl, ctl["XCTL"]))
        path.write_text("".join(x + "\n" for x in lines))
        paths.append(path)
    return paths
