"""The batch job. Nothing is processed when a file arrives; an operator
(or a timer) runs run_batch(). Results go out one batch later."""
import os

from . import ops
from .fixed import (DETAIL, HEADER, TRAILER, RECLEN, CONF, REJ, OUT_HEADER,
                    LayoutError)
from .flatfile import checksum, hash_total, write_out

DEFAULT_WINDOW = (2200, 500)   # nightly window: 22:00 up to (not incl.) 05:00


def get_window(h):
    p = h.p("CTL", "WINDOW.CTL")
    if p.exists():
        s = p.read_text().strip()
        return int(s[:4]), int(s[4:8])
    return DEFAULT_WINDOW


def set_window(h, start, end):
    h.p("CTL", "WINDOW.CTL").write_text(f"{start:04d}{end:04d}\n")


def in_window(h, now):
    start, end = get_window(h)
    t = int(now[1])
    if start == end:
        return False
    return (t >= start or t < end) if start > end else (start <= t < end)


def log(h, now, text):
    with open(h.p("LOG", "BATCH.LOG"), "a") as f:
        f.write(f"{now[0]} {now[1]} {text}\n")


class Summary:
    def __init__(self, batch):
        self.batch = batch
        self.window = False
        self.released = 0        # staged result files released at start
        self.files = 0           # inbound files processed
        self.held = 0            # files held (gap)
        self.dups = 0
        self.ok = 0
        self.rej = 0

    def __repr__(self):
        return (f"BATCH {self.batch:08d} window={self.window} files={self.files} "
                f"held={self.held} dups={self.dups} ok={self.ok} rej={self.rej} "
                f"released={self.released}")


def _release_staged(h):
    n = 0
    for name in sorted(os.listdir(h.p("STAGE"))):
        os.replace(h.p("STAGE", name), h.p("OUT", name))
        n += 1
    return n


def _parse_header(text):
    first = text.split("\n", 1)[0]
    if len(first.rstrip("\r")) != RECLEN or first[:1] != "H":
        return None
    try:
        return HEADER.unpack(first[:HEADER.width])
    except LayoutError:
        return None


def _move(h, name, folder, suffix=""):
    os.replace(h.p("IN", name), h.p(folder, name + suffix))


def _ledger_find(h, src, ictl):
    for r in h.ledger:
        if r["SRCID"] == src and r["ICTL"] == ictl:
            return r
    return None


def _file_reject(rejs, ictl, code, now, batch):
    rejs.append({"REC": "R", "ICTL": ictl, "SEQ": 0, "ACT": "", "DOC": "", "LIN": 0,
                 "ITM": "", "QTY": 0, "RCD": code, "BTCH": batch, "PDAT": now[0], "IMG": ""})


def _process_file(h, text, hdr, name, now, confs, rejs, summ):
    """Process one in-sequence file. Always consumes the control number."""
    src, ictl = hdr["SRC"], hdr["ICTL"]
    lines = [x for x in text.split("\n") if x != ""]
    nrec = nok = nrj = 0
    disp = "OK"
    trailer = None
    try:
        if lines[-1][:1] != "T" or len(lines[-1].rstrip("\r")) != RECLEN:
            raise LayoutError("F02")
        trailer = TRAILER.unpack(lines[-1][:TRAILER.width])
    except (LayoutError, IndexError):
        _file_reject(rejs, ictl, "F02", now, h.batch)
        disp = "RJ"
    detail_lines = lines[1:-1] if trailer else []
    if disp == "OK":
        # count and hash check on what the sender wrote
        if trailer["NREC"] != len(detail_lines) or \
                trailer["HASH"] != hash_total(detail_lines):
            _file_reject(rejs, ictl, "F03", now, h.batch)
            disp = "RJ"
    if disp == "OK":
        for pos, ln in enumerate(detail_lines, 1):
            nrec += 1
            rec, code = None, None
            try:
                rec = DETAIL.unpack(ln)
                if rec["REC"] != "D":
                    raise LayoutError("R01")
                ops.apply_act(h, rec, now)
            except LayoutError as e:
                code = e.code
            except ops.Reject as e:
                code = e.code
            base = rec or DETAIL.blank()
            seq = base["SEQ"] if rec else pos
            if code:
                nrj += 1
                rejs.append({"REC": "R", "ICTL": ictl, "SEQ": seq, "ACT": base["ACT"],
                             "DOC": base["DOC"], "LIN": base["LIN"], "ITM": base["ITM"],
                             "QTY": base["QTY"], "RCD": code, "BTCH": h.batch,
                             "PDAT": now[0], "IMG": ln[:RECLEN]})
            else:
                nok += 1
                confs.append({"REC": "C", "ICTL": ictl, "SEQ": seq, "ACT": base["ACT"],
                              "DOC": base["DOC"], "LIN": base["LIN"], "ITM": base["ITM"],
                              "QTY": base["QTY"], "RSLT": "OK", "BTCH": h.batch,
                              "PDAT": now[0]})
    else:
        nrj = 1
    summ.ok += nok
    summ.rej += nrj
    h.ledger.append({"SRCID": src, "ICTL": ictl, "CKSM": checksum(text), "BTCH": h.batch,
                     "DISP": disp, "NREC": nrec, "NOK": nok, "NRJ": nrj, "PDAT": now[0]})
    row = h.src[src]
    row["LAST"] = ictl
    row["NEXT"] = ictl + 1
    os.replace(h.p("IN", name), h.p("ARCH", name))
    summ.files += 1


def run_batch(h, now, trigger="OPER"):
    """Run one batch. now = ('YYYYMMDD', 'HHMM'). Returns a Summary."""
    h.batch += 1
    h.stamp = h.batch
    summ = Summary(h.batch)
    log(h, now, f"BATCH {h.batch:08d} START TRIGGER={trigger}")
    summ.released = _release_staged(h)

    if in_window(h, now):
        summ.window = True
        log(h, now, "BATCH WINDOW - INBOUND FILES NOT PROCESSED")
    else:
        _process_inbound(h, now, summ)

    h.stamp = h.batch + 1
    h.save()
    log(h, now, f"BATCH {h.batch:08d} END {summ}")
    return summ


def _process_inbound(h, now, summ):
    confs, rejs = {}, {}
    held_srcs = set()
    for name in sorted(os.listdir(h.p("IN"))):
        path = h.p("IN", name)
        if not path.is_file():
            continue
        text = path.read_text(encoding="latin-1")
        hdr = _parse_header(text)
        if hdr is None:
            _move(h, name, "ERR")
            h.raise_alarm("A03", "", 0, f"UNREADABLE {name}", now)
            continue
        src, ictl = hdr["SRC"], hdr["ICTL"]
        if src not in h.src:
            _move(h, name, "ERR")
            h.raise_alarm("A04", src, ictl, f"UNKNOWN SOURCE {src}", now)
            continue
        cf, rj = confs.setdefault(src, []), rejs.setdefault(src, [])
        if name != f"{src}.{ictl:08d}":
            _file_reject(rj, ictl, "F07", now, h.batch)
            _move(h, name, "ERR")
            summ.rej += 1
            continue
        if src in held_srcs:
            summ.held += 1
            continue
        row = h.src[src]
        if ictl < row["NEXT"]:
            led = _ledger_find(h, src, ictl)
            if led is not None and led["CKSM"] != checksum(text):
                _file_reject(rj, ictl, "F08", now, h.batch)
                h.raise_alarm("A02", src, ictl, f"{src} CTL {ictl} CONTENT DIFFERS", now)
                _move(h, name, "ERR")
            else:
                _file_reject(rj, ictl, "F04", now, h.batch)
                _move(h, name, "ARCH", f".DUP{h.batch:08d}")
                summ.dups += 1
            summ.rej += 1
        elif ictl > row["NEXT"]:
            h.raise_alarm("A01", src, row["NEXT"],
                          f"{src} EXPECTED {row['NEXT']} GOT {ictl}", now)
            held_srcs.add(src)
            summ.held += 1
        else:
            _process_file(h, text, hdr, name, now, cf, rj, summ)
            _close_gap_alarm(h, src, row["NEXT"])
    _stage_results(h, now, confs, rejs)


def _close_gap_alarm(h, src, new_next):
    for a in h.alarms:
        if a["ALCD"] == "A01" and a["SRCID"] == src and a["ALST"] == "OP" \
                and new_next > a["ICTL"]:
            a["ALST"] = "CL"


def _stage_results(h, now, confs, rejs):
    for src in sorted(set(confs) | set(rejs)):
        row = h.src[src]
        for kind, rows, lay, key in (("CF", confs[src], CONF, "OCF"),
                                     ("RJ", rejs[src], REJ, "ORJ")):
            if not rows:
                continue
            row[key] += 1
            head = {"REC": "H", "SRC": src, "OCTL": row[key], "KIND": kind,
                    "BTCH": h.batch, "PDAT": now[0]}
            name = f"{src}.{kind[0]}{row[key]:08d}"
            write_out(h.p("STAGE", name), OUT_HEADER, head, lay, rows)


def skip_gap(h, src, now, operator_note="OPERATOR SKIP"):
    """Operator action: give up on missing files and resume at the lowest
    held control number. Skipped numbers go into the ledger as disp SK."""
    row = h.src[src]
    held = []
    for name in os.listdir(h.p("IN")):
        if name.startswith(src + "."):
            try:
                held.append(int(name.split(".")[1]))
            except ValueError:
                pass
    held = [c for c in held if c > row["NEXT"]]
    if not held:
        return False
    target = min(held)
    for c in range(row["NEXT"], target):
        h.ledger.append({"SRCID": src, "ICTL": c, "CKSM": "", "BTCH": h.batch, "DISP": "SK",
                         "NREC": 0, "NOK": 0, "NRJ": 0, "PDAT": now[0]})
    row["NEXT"] = target
    _close_gap_alarm(h, src, target)
    log(h, now, f"{operator_note} {src} NEXT={target}")
    h.save()
    return True


def clear_alarm(h, alno):
    for a in h.alarms:
        if a["ALNO"] == alno and a["ALST"] == "OP":
            a["ALST"] = "CL"
            h.save()
            return True
    return False
