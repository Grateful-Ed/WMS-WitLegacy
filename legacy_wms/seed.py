"""Seed step: convert the canonical dataset (JSON) into legacy master files.

Deterministic: same dataset in, byte-identical master files out. Every row
comes from the dataset; nothing is added. Every value is converted to legacy
shape: upper case text, 2-character status codes, YYYYMMDD dates, HHMM times
(seconds dropped), zero-padded numbers, spaces or zeros where the dataset
has null. Weights go from kg to whole grams.
"""
import json
import re
from decimal import Decimal

from . import codes as C
from .fixed import LAYOUTS


class SeedError(Exception):
    pass


def _up(v):
    return re.sub(r"\s+", " ", str(v)).strip().upper() if v is not None else ""


def _date(v):
    if not v:
        return "00000000"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(v))
    if not m:
        raise SeedError(f"cannot read date {v!r}")
    return "".join(m.groups())


def _hhmm(v):
    if not v:
        return 0
    m = re.search(r"T(\d{2}):(\d{2})", str(v))
    if not m:
        raise SeedError(f"cannot read time {v!r}")
    return int(m.group(1) + m.group(2))


def _int(v, what):
    if v is None:
        return 0
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or v != int(v):
        raise SeedError(f"{what}: need a whole number >= 0, got {v!r}")
    return int(v)


def _grams(v):
    return int((Decimal(str(v)) * 1000).to_integral_value())


def _code(table, v, what):
    key = str(v).strip().lower() if v is not None else ""
    try:
        return C.WORDS[table][key]
    except KeyError:
        raise SeedError(f"{what}: no code for {v!r} in table {table}")


from .store import max_number as _maxnum


def _req(ds, name):
    if name not in ds or not isinstance(ds[name], list):
        raise SeedError(f"dataset has no list named {name!r}")
    return ds[name]


COD_NAMES = {"ADJ_REASONS": "ADJRSN", "LABR_FLAGS": "LBFLG", "TASKS": "TASK"}


def seed(host, ds):
    """Fill host master tables from a dataset dict. Raises SeedError."""
    h = host
    h.stamp = 0
    for t in h.t:
        h.t[t] = {}
    h.seq = {n: 0 for n in h.seq}
    h.src, h.ledger, h.alarms, h.ext = {}, [], [], {}

    wh = ds.get("warehouse") or {}
    if wh:
        h.put("WHS", {"WHID": _up(wh.get("id")), "WHNM": _up(wh.get("name")),
                      "WHTZ": _up(wh.get("timezone")), "SDAT": _date(wh.get("seeded_at")),
                      "STIM": _hhmm(wh.get("seeded_at"))})
    for z in _req(ds, "zones"):
        h.put("ZON", {"ZNID": _up(z["id"]), "ZNDS": _up(z["name"]),
                      "ZNTY": _code("ZNTY", z["type"], "zone type")})
    for d in _req(ds, "departments"):
        h.put("DEP", {"DPID": _up(d["id"]), "DPDS": _up(d["name"])})
    for i in _req(ds, "items"):
        h.put("ITM", {"ITNO": _up(i["id"]), "ITDS": _up(i["description"]),
                      "IUOM": _up(i["uom"]), "ICSQ": _int(i.get("case_qty"), "case_qty"),
                      "IWGT": _grams(i.get("weight_kg") or 0), "IPBN": _up(i.get("putaway_bin")),
                      "ITST": _code("ITST", i.get("status", "active"), "item status")})
    for b in _req(ds, "bins"):
        h.put("LOC", {"LCNO": _up(b["id"]), "LCZN": _up(b["zone_id"]), "LCAI": _up(b["aisle"]),
                      "LCPS": _up(b["position"]), "LCCP": _int(b["capacity"], "capacity"),
                      "LCST": _code("LCST", b["status"], "bin status")})
    for d in _req(ds, "doors"):
        h.put("DOR", {"DRNO": _up(d["id"]), "DRDS": _up(d["name"]),
                      "DRDI": _code("DRDI", d["direction"], "door direction"),
                      "DRST": _code("DRST", d["status"], "door status"),
                      "DRRT": _code("RFTY", (d.get("current_ref") or {}).get("type", "asn"),
                                    "door ref type") if d.get("current_ref") else "",
                      "DRRF": _up((d.get("current_ref") or {}).get("id"))})
    for a in _req(ds, "dock_appointments"):
        h.put("APT", {"APNO": _up(a["id"]), "DRNO": _up(a["door_id"]),
                      "ADIR": _code("DRDI", a["direction"], "appointment direction"),
                      "RFTY": _code("RFTY", a["ref_type"], "appointment ref type"),
                      "RFNO": _up(a["ref_id"]), "SDAT": _date(a["start"]),
                      "STIM": _hhmm(a["start"]), "EDAT": _date(a["end"]),
                      "ETIM": _hhmm(a["end"]), "APST": _code("APST", a["status"], "appt status")})
    for a in _req(ds, "asns"):
        h.put("ASH", {"ASNO": _up(a["id"]), "SUPL": _up(a["supplier"]),
                      "ASST": _code("ASST", a["status"], "asn status"),
                      "DRNO": _up(a.get("door_id")), "APNO": _up(a.get("appointment_id")),
                      "ARDT": _date(a.get("arrived_at")), "ARTM": _hhmm(a.get("arrived_at"))})
        for ln in a["lines"]:
            h.put("ASL", {"ASNO": _up(a["id"]), "LNNO": _int(ln["line"], "asn line"),
                          "ITNO": _up(ln["item_id"]),
                          "EXQT": _int(ln["expected_qty"], "expected_qty"),
                          "RCQT": _int(ln["received_qty"], "received_qty")})
    dl_pallet = {}
    for p in _req(ds, "pallets"):
        dl_pallet[p["id"]] = p
        h.put("PAL", {"PLNO": _up(p["id"]), "PDIR": _code("DRDI", p["direction"], "pallet dir"),
                      "LANE": _up(p["lane"]), "PLST": _code("PLST", p["status"], "pallet status"),
                      "ASNO": _up(p.get("asn_id")), "ASLN": _int(p.get("asn_line"), "asn_line"),
                      "DLNO": _up(p.get("delivery_id"))})
    pal_dir = {p["id"]: p["direction"] for p in ds["pallets"]}
    for r in _req(ds, "inventory"):
        loc = r["location_id"]
        if loc in pal_dir:
            st = "PP" if pal_dir[loc] == "inbound" else "SL"
        elif any(b["id"] == loc for b in ds["bins"]):
            st = "AV"
        else:
            raise SeedError(f"inventory names unknown location {loc!r}")
        key = (_up(loc), _up(r["item_id"]), st)
        row = h.get("INV", *key) or {"LCNO": key[0], "ITNO": key[1], "IVST": st, "ONHD": 0}
        row["ONHD"] += _int(r["qty"], "inventory qty")
        h.put("INV", row)
    for g in _req(ds, "ledger"):
        h.put("TRN", {"LGNO": _up(g["id"]), "LGDT": _date(g["at"]), "LGTM": _hhmm(g["at"]),
                      "LGTY": _code("LGTY", g["type"], "ledger type"), "ITNO": _up(g["item_id"]),
                      "FLOC": _up(g.get("from_location")), "TLOC": _up(g.get("to_location")),
                      "QTY": _int(g["qty"], "ledger qty"), "REF": _up(g.get("ref"))})
    for w in _req(ds, "waves"):
        h.put("WAV", {"WVNO": _up(w["id"]), "WVST": _code("WVST", w["status"], "wave status"),
                      "RLDT": _date(w.get("released_at")), "RLTM": _hhmm(w.get("released_at"))})
    for o in _req(ds, "orders"):
        h.put("OHD", {"ORNO": _up(o["id"]), "CUNM": _up(o["customer"]),
                      "ORST": _code("ORST", o["status"], "order status"),
                      "WVNO": _up(o.get("wave_id")), "DLNO": _up(o.get("delivery_id")),
                      "SHDT": "00000000"})
        for ln in o["lines"]:
            q, pq = _int(ln["qty"], "line qty"), _int(ln.get("picked_qty"), "picked_qty")
            h.put("OLN", {"ORNO": _up(o["id"]), "LNNO": _int(ln["line"], "line"),
                          "ITNO": _up(ln["item_id"]), "OQTY": q, "PQTY": pq, "SQTY": 0,
                          "LNST": "OP" if pq == 0 else "PD" if pq >= q else "PA"})
    for d in _req(ds, "deliveries"):
        h.put("DLV", {"DLNO": _up(d["id"]), "ORNO": _up(d["order_id"]),
                      "DLST": _code("DLST", d["status"], "delivery status"),
                      "LDNO": _up(d.get("load_id")), "SHDT": _date(d.get("shipped_at")),
                      "SHTM": _hhmm(d.get("shipped_at"))})
    for l in _req(ds, "loads"):
        h.put("LDS", {"LDNO": _up(l["id"]), "DRNO": _up(l["door_id"]), "CARR": _up(l["carrier"]),
                      "LDST": _code("LDST", l["status"], "load status"),
                      "APNO": _up(l.get("appointment_id")), "SEAL": _up(l.get("seal_no")),
                      "SHDT": _date(l.get("shipped_at")), "SHTM": _hhmm(l.get("shipped_at"))})
    for t in _req(ds, "tasks"):
        typ = _code("TKTY", t["type"], "task type")
        row = {"TKNO": _up(t["id"]), "TKTY": typ, "TKST": _code("TKST", t["status"], "task status"),
               "ZNID": _up(t.get("zone_id")), "ASGN": _up(t.get("assigned_to")),
               "WVNO": _up(t.get("wave_id")), "ORNO": _up(t.get("order_id")),
               "LNNO": _int(t.get("line"), "task line"), "ITNO": _up(t.get("item_id")),
               "QTY": _int(t.get("qty"), "task qty"), "FBIN": "", "TBIN": "",
               "PLNO": _up(t.get("pallet_id")), "CCNO": _up(t.get("cycle_count_id")),
               "BNNO": _up(t.get("bin_id")), "CRDT": _date(t.get("created_at")),
               "CRTM": _hhmm(t.get("created_at")), "CPDT": _date(t.get("completed_at")),
               "CPTM": _hhmm(t.get("completed_at")), "CPBY": _up(t.get("completed_by"))}
        if typ == "PK":
            row["FBIN"], row["TBIN"] = _up(t.get("from_bin")), _up(t.get("to_location"))
        elif typ == "PU":
            row["FBIN"], row["TBIN"] = _up(t.get("from_location")), _up(t.get("to_bin"))
        h.put("TSK", row)
    for c in _req(ds, "cycle_counts"):
        var = c.get("variance")
        h.put("CCN", {"CCNO": _up(c["id"]), "BNNO": _up(c["bin_id"]), "ITNO": _up(c["item_id"]),
                      "CCST": _code("CCST", c["status"], "count status"),
                      "TKNO": _up(c.get("task_id")), "SQTY": _int(c.get("system_qty"), "sys qty"),
                      "CQTY": _int(c.get("counted_qty"), "counted qty"),
                      "CVAR": int(var) if var is not None else 0})
    for e in _req(ds, "exceptions"):
        h.put("EXC", {"EXNO": _up(e["id"]), "EXKD": _code("EXKD", e["kind"], "exception kind"),
                      "EXEN": _code("EXEN", e["entity"], "exception entity"),
                      "EXEI": _up(e["entity_id"]),
                      "EXSV": _code("EXSV", e["severity"], "exception severity"),
                      "EXRS": _up(e["reason"]), "EXST": _code("EXST", e["status"], "exc status"),
                      "EXDT": _date(e["raised_at"]), "EXTM": _hhmm(e["raised_at"]),
                      "EXBY": _up(e.get("raised_by"))})
    for w in _req(ds, "workers"):
        h.put("USR", {"USNO": _up(w["id"]), "USNM": _up(w["name"]),
                      "USDP": _up(w.get("department_id")), "USZN": _up(w.get("zone_id")),
                      "USSH": _code("USSH", w.get("shift", "day"), "shift"),
                      "USST": _code("USST", w["status"], "worker status")})
    # code tables, so a reader can decode every 2-character code
    for name, tbl in C.CODE_TABLES.items():
        for cd, txt in sorted(tbl.items()):
            h.put("COD", {"TBLN": COD_NAMES.get(name, name), "CODE": cd, "CDSC": txt})
    # check references
    for (orno, _), ln in h.t["OLN"].items():
        if h.get("ITM", ln["ITNO"]) is None:
            raise SeedError(f"order {orno} line names unknown item {ln['ITNO']!r}")
    # sequences continue after the highest seeded number
    h.seq["EXC"] = _maxnum(k[0] for k in h.t["EXC"])
    h.seq["CCN"] = _maxnum(k[0] for k in h.t["CCN"])
    h.seq["DLV"] = _maxnum(k[0] for k in h.t["DLV"])
    h.seq["TRN"] = _maxnum(k[0] for k in h.t["TRN"])
    h.seq["PAL"] = _maxnum(k[0] for k in h.t["PAL"])
    h.seq["TSK"] = _maxnum(k[0] for k in h.t["TSK"])
    h.batch = 0
    h.stamp = 1
    for t in LAYOUTS:      # fail early if any value does not fit a layout
        for r in h.t[t].values():
            LAYOUTS[t].pack(r)


def seed_from_file(host, path):
    with open(path, encoding="utf-8") as f:
        ds = json.load(f)
    if not isinstance(ds, dict):
        raise SeedError("dataset must be a JSON object")
    seed(host, ds)
    host.save()
