"""Warehouse operations. Both the batch job and the terminal call apply_act().

Every act validates first and changes data last, so a reject leaves no trace.
"""
import copy

from . import codes as C


class Reject(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _need(cond, code):
    if not cond:
        raise Reject(code)


def loc_total(h, lcno):
    return sum(r["ONHD"] for k, r in h.t["INV"].items() if k[0] == lcno)


def _on_hand(h, lcno, itno, ivst):
    row = h.get("INV", lcno, itno, ivst)
    return row["ONHD"] if row else 0


def _inv_add(h, lcno, itno, ivst, qty):
    row = h.get("INV", lcno, itno, ivst)
    if row is None:
        _need(qty >= 0, "B06")
        row = {"LCNO": lcno, "ITNO": itno, "IVST": ivst, "ONHD": 0, "LCB": 0}
    _need(row["ONHD"] + qty >= 0, "B06")
    row["ONHD"] += qty
    h.put("INV", row)  # zero rows stay, so delta extracts show the change


def _trn(h, now, typ, itno, floc, tloc, qty, ref):
    h.put("TRN", {"LGNO": h.alloc("TRN"), "LGDT": now[0], "LGTM": int(now[1]), "LGTY": typ,
                  "ITNO": itno, "FLOC": floc, "TLOC": tloc, "QTY": qty, "REF": ref})


def _item(h, itno, active=True):
    it = h.get("ITM", itno)
    _need(it is not None, "B01")
    if active:
        _need(it["ITST"] == "AC", "B02")
    return it


def _bin(h, lcno):
    loc = h.get("LOC", lcno)
    _need(loc is not None, "B03")
    return loc


def _bin_for_add(h, lcno, qty):
    loc = _bin(h, lcno)
    _need(loc["LCST"] == "AV", "B04")
    if loc["LCCP"] > 0:
        _need(loc_total(h, lcno) + qty <= loc["LCCP"], "B05")
    return loc


def _door(h, drno, direction):
    d = h.get("DOR", drno)
    _need(d is not None, "B10")
    _need(d["DRST"] != "CL" and d["DRDI"] == direction, "B11")
    return d


def _order(h, orno):
    o = h.get("OHD", orno)
    _need(o is not None, "B07")
    return o


def _lines(h, orno):
    return [r for k, r in sorted(h.t["OLN"].items()) if k[0] == orno]


def _complete_task(h, row, rec, adate, atime):
    row.update({"TKST": "CP", "CPDT": adate, "CPTM": atime, "CPBY": rec["USR"]})
    h.touch(row)


def _moved(h, typ, itno, floc, ref):
    """Quantity already moved by earlier acts of this type (from the ledger)."""
    return sum(r["QTY"] for r in h.t["TRN"].values()
               if r["LGTY"] == typ and r["ITNO"] == itno and r["FLOC"] == floc
               and r["REF"] == ref)


def _open_tasks(h, tkty):
    return [r for k, r in sorted(h.t["TSK"].items())
            if r["TKTY"] == tkty and r["TKST"] == "OP"]


def _eval_order_picked(h, o, now, last_bin=""):
    """When the last line is picked or shorted the order is PD and the host
    makes one open pack task for it (zone of the last bin picked, unassigned)."""
    ls = _lines(h, o["ORNO"])
    if ls and all(l["LNST"] in ("PD", "SX") for l in ls) and o["ORST"] != "PD":
        o["ORST"] = "PD"
        if sum(l["PQTY"] for l in ls) == 0:      # nothing picked: nothing to pack
            h.touch(o)
            return
        loc = h.get("LOC", last_bin) if last_bin else None
        h.put("TSK", {"TKNO": h.alloc("TSK"), "TKTY": "PA", "TKST": "OP",
                      "ZNID": loc["LCZN"] if loc else "", "ASGN": "", "WVNO": o["WVNO"],
                      "ORNO": o["ORNO"], "LNNO": 0, "ITNO": "",
                      "QTY": sum(l["PQTY"] for l in ls), "FBIN": C.PICK_PREFIX + o["ORNO"],
                      "TBIN": "", "PLNO": "", "CCNO": "", "BNNO": "",
                      "CRDT": now[0], "CRTM": int(now[1]), "CPDT": "00000000", "CPTM": 0,
                      "CPBY": ""})
    h.touch(o)


def _new_pallet_no(h):
    return h.alloc("PAL")


def _log_exception(h, kind, entity, eid, sev, text, rec, now):
    h.put("EXC", {"EXNO": h.alloc("EXC"), "EXKD": kind, "EXEN": entity, "EXEI": eid,
                  "EXSV": sev, "EXRS": text[:60], "EXST": "OP", "EXDT": now[0],
                  "EXTM": int(now[1]), "EXBY": rec["USR"]})


def apply_act(h, rec, now):
    """Apply one act record (dict with DETAIL fields). Raises Reject(code)."""
    act = rec["ACT"]
    _need(act in C.ACTS, "R02")
    _need(rec["USR"] != "", "B15")
    _need(h.get("USR", rec["USR"]) is not None, "B15")
    adate = rec["ADT"] if rec["ADT"] != "00000000" else now[0]
    atime = rec["ATM"] if rec["ATM"] else int(now[1])
    _ACT_FUNCS[act](h, rec, adate, atime, (adate, f"{atime:04d}"))


def apply_act_safe(h, rec, now, log=None):
    """apply_act, but an unexpected error rejects the record (R01) and rolls
    back anything it half did. Rejects and layout errors pass through."""
    snap = copy.deepcopy((h.t, h.seq, h.alarms, h.ledger, h.src, h.ext))
    try:
        apply_act(h, rec, now)
    except Reject:
        raise
    except Exception as e:      # noqa: BLE001 - one bad record must not stop the batch
        t, seq, alarms, ledger, src, ext = snap      # restore in place: no stale references
        for name in h.t:
            h.t[name] = t[name]
        h.seq.clear()
        h.seq.update(seq)
        h.alarms[:] = alarms
        h.ledger[:] = ledger
        h.src.clear()
        h.src.update(src)
        h.ext.clear()
        h.ext.update(ext)
        if log:
            log(f"UNEXPECTED ERROR IN ACT {rec.get('ACT')} SEQ {rec.get('SEQ')}: "
                f"{type(e).__name__} {e}")
        raise Reject("R01")


def _qty_pos(rec):
    _need(rec["QTY"] > 0, "R05")


def _rcpt(h, rec, adate, atime, now):
    _need(rec["DOC"] != "" and rec["ITM"] != "" and rec["DOR"] != "" and rec["TLC"] != "", "R07")
    _need(rec["LIN"] > 0, "R07")
    _qty_pos(rec)
    asn = h.get("ASH", rec["DOC"])
    _need(asn is not None, "B18")
    _need(asn["ASST"] in ("AR", "RG"), "B19")
    line = h.get("ASL", rec["DOC"], rec["LIN"])
    _need(line is not None and line["ITNO"] == rec["ITM"], "B09")
    _item(h, rec["ITM"])
    _door(h, rec["DOR"], "IN")
    _need(line["RCQT"] + rec["QTY"] <= line["EXQT"], "B20")
    _need(h.get("PAL", rec["TLC"]) is None, "B14")
    h.put("PAL", {"PLNO": rec["TLC"], "PDIR": "IN", "LANE": C.LANE_PREFIX + rec["DOR"],
                  "PLST": "PP", "ASNO": rec["DOC"], "ASLN": rec["LIN"], "DLNO": ""})
    _inv_add(h, rec["TLC"], rec["ITM"], "PP", rec["QTY"])
    line["RCQT"] += rec["QTY"]
    h.touch(line)
    asn["ASST"] = "RC" if all(
        l["RCQT"] >= l["EXQT"] for k, l in h.t["ASL"].items() if k[0] == rec["DOC"]) else "RG"
    h.touch(asn)
    _trn(h, now, "RC", rec["ITM"], "", rec["TLC"], rec["QTY"], rec["DOC"])


def _puta(h, rec, adate, atime, now):
    _need(rec["ITM"] != "" and rec["FLC"] != "" and rec["TLC"] != "", "R07")
    _qty_pos(rec)
    _item(h, rec["ITM"], active=False)
    pal = h.get("PAL", rec["FLC"])
    _need(pal is not None and pal["PDIR"] == "IN", "B21")
    _bin_for_add(h, rec["TLC"], rec["QTY"])
    _need(_on_hand(h, rec["FLC"], rec["ITM"], "PP") >= rec["QTY"], "B06")
    _inv_add(h, rec["FLC"], rec["ITM"], "PP", -rec["QTY"])
    _inv_add(h, rec["TLC"], rec["ITM"], "AV", rec["QTY"])
    if not any(r["ONHD"] for k, r in h.t["INV"].items() if k[0] == rec["FLC"]):
        pal["PLST"] = "PC"
        h.touch(pal)
    done = rec["QTY"] + _moved(h, "PU", rec["ITM"], rec["FLC"], rec["FLC"])
    _trn(h, now, "PU", rec["ITM"], rec["FLC"], rec["TLC"], rec["QTY"], rec["FLC"])
    for t in _open_tasks(h, "PU"):
        if t["PLNO"] == rec["FLC"] and t["ITNO"] == rec["ITM"] and done >= t["QTY"]:
            _complete_task(h, t, rec, adate, atime)
            break


def _adjt(h, rec, adate, atime, now):
    _need(rec["ITM"] != "" and rec["FLC"] != "", "R07")
    _need(rec["SGN"] != "", "R07")
    _need(rec["RSN"] in C.ADJ_REASONS, "R06")
    _need(rec["SGN"] in ("+", "-"), "R06")
    _qty_pos(rec)
    _item(h, rec["ITM"], active=False)
    sign = -1 if rec["SGN"] == "-" else 1
    if sign > 0:
        _bin_for_add(h, rec["FLC"], rec["QTY"])
    else:
        _bin(h, rec["FLC"])
    _inv_add(h, rec["FLC"], rec["ITM"], "AV", sign * rec["QTY"])
    _trn(h, now, "AJ", rec["ITM"], rec["FLC"] if sign < 0 else "",
         rec["FLC"] if sign > 0 else "", rec["QTY"], rec["RSN"])


def _rlse(h, rec, adate, atime, now):
    _need(rec["DOC"] != "", "R07")
    o = _order(h, rec["DOC"])
    _need(o["ORST"] == "NW", "B08")
    o["ORST"] = "RL"
    h.touch(o)


def _find_line(h, rec, o):
    ls = _lines(h, o["ORNO"])
    if rec["LIN"]:
        ls = [l for l in ls if l["LNNO"] == rec["LIN"]]
    if rec["ITM"]:
        ls = [l for l in ls if l["ITNO"] == rec["ITM"]]
    return ls


def _pick(h, rec, adate, atime, now):
    _need(rec["DOC"] != "" and rec["ITM"] != "" and rec["FLC"] != "", "R07")
    _qty_pos(rec)
    o = _order(h, rec["DOC"])
    _need(o["ORST"] in ("RL", "PI"), "B08")
    cands = [l for l in _find_line(h, rec, o)
             if l["LNST"] in ("OP", "PA") and l["OQTY"] - l["PQTY"] - l["SQTY"] >= rec["QTY"]]
    _need(cands, "B09")
    line = cands[0]
    _bin(h, rec["FLC"])
    _inv_add(h, rec["FLC"], rec["ITM"], "AV", -rec["QTY"])
    ploc = C.PICK_PREFIX + o["ORNO"]
    _inv_add(h, ploc, rec["ITM"], "PK", rec["QTY"])
    line["PQTY"] += rec["QTY"]
    line["LNST"] = "PD" if line["PQTY"] + line["SQTY"] >= line["OQTY"] else "PA"
    h.touch(line)
    o["ORST"] = "PI"
    _eval_order_picked(h, o, now, rec["FLC"])
    _trn(h, now, "PI", rec["ITM"], rec["FLC"], ploc, rec["QTY"], o["ORNO"])
    for t in _open_tasks(h, "PK"):              # a task measures its own line
        if (t["ORNO"], t["LNNO"]) == (o["ORNO"], line["LNNO"]) and line["PQTY"] >= t["QTY"]:
            _complete_task(h, t, rec, adate, atime)
            break


def _shrt(h, rec, adate, atime, now):
    _need(rec["DOC"] != "" and rec["LIN"] != 0, "R07")
    o = _order(h, rec["DOC"])
    _need(o["ORST"] in ("RL", "PI"), "B08")
    ls = [l for l in _find_line(h, rec, o) if l["LNST"] in ("OP", "PA")]
    _need(ls, "B09")
    line = ls[0]
    line["SQTY"] = line["OQTY"] - line["PQTY"]
    line["LNST"] = "SX"
    h.touch(line)
    o["ORST"] = "PI"
    _log_exception(h, "SP", "OR", o["ORNO"], "M",
                   f"SHORT {o['ORNO']} LINE {line['LNNO']} {line['ITNO']} "
                   f"ORDERED {line['OQTY']} PICKED {line['PQTY']}", rec, now)
    for t in _open_tasks(h, "PK"):              # a shorted line is done being picked
        if (t["ORNO"], t["LNNO"]) == (o["ORNO"], line["LNNO"]):
            _complete_task(h, t, rec, adate, atime)
            break
    _eval_order_picked(h, o, now)


def _pack(h, rec, adate, atime, now):
    """Makes the delivery and the outbound pallet it rides on. The order's
    picked stock moves from PK-<order> to the pallet (status SL)."""
    _need(rec["DOC"] != "", "R07")
    o = _order(h, rec["DOC"])
    _need(o["ORST"] == "PD", "B12")
    _need(sum(l["PQTY"] for l in _lines(h, o["ORNO"])) > 0, "B12")   # fully shorted
    dlno = h.alloc("DLV")
    plno = _new_pallet_no(h)
    h.put("DLV", {"DLNO": dlno, "ORNO": o["ORNO"], "DLST": "PK", "LDNO": "",
                  "SHDT": "00000000", "SHTM": 0})
    h.put("PAL", {"PLNO": plno, "PDIR": "OU", "LANE": "", "PLST": "SL", "ASNO": "",
                  "ASLN": 0, "DLNO": dlno})
    ploc = C.PICK_PREFIX + o["ORNO"]
    for k, inv in sorted(h.t["INV"].items()):
        if k[0] == ploc and inv["ONHD"]:
            qty = inv["ONHD"]
            _trn(h, now, "PK", inv["ITNO"], ploc, plno, qty, o["ORNO"])
            _inv_add(h, ploc, inv["ITNO"], inv["IVST"], -qty)
            _inv_add(h, plno, inv["ITNO"], "SL", qty)
    for t in _open_tasks(h, "PA"):
        if t["ORNO"] == o["ORNO"]:
            t["PLNO"], t["TBIN"] = plno, plno
            _complete_task(h, t, rec, adate, atime)
            break
    o["ORST"] = "PK"
    o["DLNO"] = dlno
    h.touch(o)
    ls = _lines(h, o["ORNO"])
    ordered, packed = sum(l["OQTY"] for l in ls), sum(l["PQTY"] for l in ls)
    if packed < ordered:                        # goes out short: flag it, never block it
        _log_exception(h, "SP", "OR", o["ORNO"], "M",
                       f"SHORT PACK {o['ORNO']} ORDERED {ordered} PACKED {packed}", rec, now)


def _load(h, rec, adate, atime, now):
    _need(rec["DOC"] != "" and rec["TLC"] != "", "R07")
    d = h.get("DLV", rec["DOC"])
    _need(d is not None, "B23")
    ld = h.get("LDS", rec["TLC"])
    _need(ld is not None, "B24")
    _need(d["DLST"] == "PK" and d["LDNO"] == "", "B12")
    _need(ld["LDST"] in ("PL", "LG"), "B25")
    d["LDNO"] = ld["LDNO"]
    h.touch(d)
    for k, p in sorted(h.t["PAL"].items()):     # pallet moves to the load's door lane
        if p["DLNO"] == d["DLNO"]:
            p["LANE"] = C.LANE_PREFIX + ld["DRNO"]
            h.touch(p)
    ld["LDST"] = "LG"
    h.touch(ld)


def _ship(h, rec, adate, atime, now):
    _need(rec["DOC"] != "" and rec["DOR"] != "", "R07")
    ld = h.get("LDS", rec["DOC"])
    _need(ld is not None, "B24")
    _need(ld["LDST"] == "LG", "B25")
    _door(h, rec["DOR"], "OU")
    _need(ld["DRNO"] == rec["DOR"], "B11")
    dls = [r for k, r in sorted(h.t["DLV"].items()) if r["LDNO"] == ld["LDNO"]]
    _need(dls and all(d["DLST"] == "PK" for d in dls), "B12")
    for d in dls:
        d["DLST"], d["SHDT"], d["SHTM"] = "SH", adate, atime
        h.touch(d)
        o = h.get("OHD", d["ORNO"])
        if o:
            o["ORST"], o["SHDT"] = "SH", adate
            h.touch(o)
            for k, inv in list(h.t["INV"].items()):
                if k[0] == C.PICK_PREFIX + o["ORNO"] and inv["ONHD"]:
                    _trn(h, now, "SH", inv["ITNO"], inv["LCNO"], "", inv["ONHD"], ld["LDNO"])
                    _inv_add(h, inv["LCNO"], inv["ITNO"], inv["IVST"], -inv["ONHD"])
        for k, p in sorted(h.t["PAL"].items()):
            if p["DLNO"] == d["DLNO"]:
                for ik, inv in list(h.t["INV"].items()):
                    if ik[0] == p["PLNO"] and inv["ONHD"]:
                        _trn(h, now, "SH", inv["ITNO"], inv["LCNO"], "", inv["ONHD"],
                             ld["LDNO"])
                        _inv_add(h, inv["LCNO"], inv["ITNO"], inv["IVST"], -inv["ONHD"])
                p["PLST"] = "SH"
                h.touch(p)
    ld.update({"LDST": "SH", "SEAL": rec["TLC"], "SHDT": adate, "SHTM": atime})
    h.touch(ld)
    ap = h.get("APT", ld["APNO"])
    if ap:
        ap["APST"] = "CP"
        h.touch(ap)


def _cnts(h, rec, adate, atime, now):
    _need(rec["ITM"] != "" and rec["FLC"] != "", "R07")
    _item(h, rec["ITM"], active=False)
    _bin(h, rec["FLC"])
    sysq = _on_hand(h, rec["FLC"], rec["ITM"], "AV")
    var = rec["QTY"] - sysq
    cc = next((r for k, r in sorted(h.t["CCN"].items()) if r["CCST"] in ("OP", "RC")
               and r["BNNO"] == rec["FLC"] and r["ITNO"] == rec["ITM"]), None)
    if cc is None:
        cc = {"CCNO": h.alloc("CCN"), "BNNO": rec["FLC"], "ITNO": rec["ITM"], "CCST": "OP",
              "TKNO": "", "SQTY": 0, "CQTY": 0, "CVAR": 0, "LCB": 0}
    cc.update({"SQTY": sysq, "CQTY": rec["QTY"], "CVAR": var,
               "CCST": "CM" if var == 0 else "RC"})
    h.put("CCN", cc)
    for t in _open_tasks(h, "CN"):
        if t["CCNO"] == cc["CCNO"]:
            _complete_task(h, t, rec, adate, atime)
    if var != 0:
        _log_exception(h, "CV", "BN", rec["FLC"], "M",
                       f"COUNT VARIANCE {var:+d} ITEM {rec['ITM']}", rec, now)


def _excp(h, rec, adate, atime, now):
    _need(rec["RSN"] in C.EXKD, "R06")
    _need(rec["FLG"] in C.EXEN, "R06")
    _need(rec["SGN"] in ("", "L", "M", "H"), "R06")
    _need(rec["DOC"] != "", "R07")
    _log_exception(h, rec["RSN"], rec["FLG"], rec["DOC"], rec["SGN"] or "L", rec["TXT"].upper(),
                   rec, now)


def _labr(h, rec, adate, atime, now):
    _need(rec["FLG"] in C.LABR_FLAGS, "R06")
    open_rows = [r for r in h.t["LBL"].values() if r["USNO"] == rec["USR"] and r["LBST"] == "OP"]
    if rec["FLG"] == "ST":
        _need(rec["RSN"] in C.TASKS, "R06")
        _need(not open_rows, "B16")
        h.put("LBL", {"LBNO": h.alloc("LBL"), "USNO": rec["USR"], "TKCD": rec["RSN"],
                      "SDAT": adate, "STIM": atime, "EDAT": "00000000", "ETIM": 0,
                      "UNIT": 0, "LBST": "OP"})
    else:
        _need(open_rows, "B17")
        r = open_rows[0]
        r.update({"EDAT": adate, "ETIM": atime, "UNIT": rec["QTY"], "LBST": "CL"})
        h.touch(r)


_ACT_FUNCS = {
    "RCPT": _rcpt, "PUTA": _puta, "ADJT": _adjt, "RLSE": _rlse, "PICK": _pick,
    "SHRT": _shrt, "PACK": _pack, "LOAD": _load, "SHIP": _ship, "CNTS": _cnts,
    "EXCP": _excp, "LABR": _labr,
}


def close_exception(h, exno):
    r = h.get("EXC", exno)
    if r is None:
        return False
    r["EXST"] = "CL"
    h.touch(r)
    return True
