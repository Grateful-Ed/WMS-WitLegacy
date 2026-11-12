"""Reference reader/writer for the integration flat files.

The outside layer can use build_inbound() to make a drop file and
read_records() to read confirm, reject and extract files.
"""
import zlib

from .fixed import (DETAIL, HEADER, TRAILER, RECLEN, OUT_HEADER, OUT_TRAILER,
                    EXT_HEADER, CONF, REJ, LAYOUTS)


def hash_total(lines):
    """Sum of the QTY field of every detail line (non-numeric counts as 0)."""
    pos, w = DETAIL.offset("QTY")
    total = 0
    for ln in lines:
        q = ln[pos:pos + w]
        if q.isdigit():
            total += int(q)
    return total % 10 ** 12


def build_inbound(src, ictl, acts, fdat="00000000", ftim=0):
    """Return the text of an inbound file. acts: list of dicts (partial DETAIL)."""
    detail = []
    for i, a in enumerate(acts, 1):
        if isinstance(a, str):          # raw line, used to make bad records
            detail.append(a)
            continue
        r = DETAIL.blank()
        r.update(a)
        r["REC"] = "D"
        r["SEQ"] = a.get("SEQ", i)
        detail.append(DETAIL.pack(r))
    lines = [HEADER.pack({"REC": "H", "SRC": src, "ICTL": ictl, "FDAT": fdat,
                          "FTIM": ftim}).ljust(RECLEN)]
    lines += detail
    lines.append(TRAILER.pack({"REC": "T", "NREC": len(detail),
                               "HASH": hash_total(detail)}).ljust(RECLEN))
    return "".join(x + "\n" for x in lines)


def inbound_name(src, ictl):
    return f"{src}.{ictl:08d}"


def drop_inbound(host, src, ictl, acts, fdat="00000000", ftim=0, name=None):
    path = host.p("IN", name or inbound_name(src, ictl))
    path.write_text(build_inbound(src, ictl, acts, fdat, ftim))
    return path


def checksum(text):
    return f"{zlib.crc32(text.encode('latin-1', 'replace')):08X}"


def pad(layout_text, width):
    return layout_text.ljust(width)


def write_out(path, header_layout, header_row, detail_layout, rows):
    w = detail_layout.width
    lines = [header_layout.pack(header_row).ljust(w)]
    lines += [detail_layout.pack(r) for r in rows]
    lines.append(OUT_TRAILER.pack({"REC": "T", "NREC": len(rows)}).ljust(w))
    path.write_text("".join(x + "\n" for x in lines))


def read_records(path, kind):
    """Read an output file. kind: 'CF', 'RJ' or a master table name for extracts.
    Returns (header_row, detail_rows, trailer_row)."""
    lay = {"CF": CONF, "RJ": REJ}.get(kind) or LAYOUTS[kind]
    hdr_lay = EXT_HEADER if kind in LAYOUTS else OUT_HEADER
    lines = [x for x in path.read_text().splitlines() if x.strip()]
    hdr = hdr_lay.unpack(lines[0][:hdr_lay.width])
    trl = OUT_TRAILER.unpack(lines[-1][:OUT_TRAILER.width])
    rows = [lay.unpack(x) for x in lines[1:-1]]
    return hdr, rows, trl
