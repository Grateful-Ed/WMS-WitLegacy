"""Code tables. These tables are part of the integration contract (see README)."""

# Act codes (inbound detail records).
ACTS = {
    "RCPT": "RECEIVE TO DOCK",
    "PUTA": "PUTAWAY DOCK TO BIN",
    "ADJT": "INVENTORY ADJUST",
    "RLSE": "RELEASE ORDER",
    "PICK": "PICK TO ORDER",
    "SHRT": "SHORT AN ORDER LINE",
    "PACK": "PACK ORDER (MAKES DELIVERY)",
    "LOAD": "PUT DELIVERY ON LOAD",
    "SHIP": "SHIP LOAD",
    "CNTS": "COUNT SUBMIT",
    "EXCP": "LOG EXCEPTION",
    "LABR": "LABOR START/END",
}

# Reject codes (reject file). F=file, R=record layout, B=business rule.
REJECTS = {
    "F02": "TRAILER MISSING OR BAD",
    "F03": "TRAILER COUNT OR HASH MISMATCH",
    "F04": "DUPLICATE OR SKIPPED FILE - NOT PROCESSED",
    "F07": "FILE NAME DOES NOT MATCH HEADER",
    "F08": "SAME CONTROL NO, DIFFERENT CONTENT",
    "R01": "BAD RECORD (LENGTH, TYPE, OR HOST COULD NOT PROCESS IT)",
    "R02": "UNKNOWN ACT CODE",
    "R03": "NON-NUMERIC IN NUMERIC FIELD",
    "R04": "BAD DATE",
    "R05": "QUANTITY MUST BE GREATER THAN ZERO",
    "R06": "BAD REASON OR FLAG CODE",
    "R07": "REQUIRED FIELD BLANK",
    "B01": "UNKNOWN ITEM",
    "B02": "ITEM NOT ACTIVE",
    "B03": "UNKNOWN LOCATION",
    "B04": "LOCATION BLOCKED",
    "B05": "OVER LOCATION CAPACITY",
    "B06": "INSUFFICIENT STOCK",
    "B07": "UNKNOWN ORDER",
    "B08": "ORDER STATUS WRONG FOR ACT",
    "B09": "ORDER LINE NOT FOUND OR OVER QTY",
    "B10": "UNKNOWN DOOR",
    "B11": "DOOR CLOSED OR WRONG TYPE",
    "B12": "ORDER NOT READY FOR ACT",
    "B14": "PALLET ALREADY EXISTS",
    "B15": "UNKNOWN USER",
    "B16": "USER ALREADY ON A TASK",
    "B17": "USER HAS NO OPEN TASK",
    "B18": "UNKNOWN ASN",
    "B19": "ASN NOT ARRIVED OR ALREADY RECEIVED",
    "B20": "OVER RECEIPT",
    "B21": "UNKNOWN PALLET OR WRONG PALLET TYPE",
    "B23": "UNKNOWN DELIVERY",
    "B24": "UNKNOWN LOAD",
    "B25": "LOAD NOT OPEN FOR THIS ACT",
}

# Operator alarm codes (ALARM file and terminal).
ALARMS = {
    "A01": "GAP IN CONTROL NUMBER SEQUENCE - FILES HELD",
    "A02": "RE-SENT FILE HAS DIFFERENT CONTENT",
    "A03": "UNREADABLE FILE MOVED TO ERR",
    "A04": "FILE FROM UNKNOWN SOURCE",
}

# Two-character status codes. Each table: code -> text. Seed maps dataset words.
ZNTY = {"RS": "RESERVE", "PK": "PICK", "OV": "OVERFLOW"}
DRDI = {"IN": "INBOUND", "OU": "OUTBOUND"}
DRST = {"FR": "FREE", "OC": "OCCUPIED", "CL": "CLOSED"}
ADIR = DRDI
RFTY = {"AS": "ASN", "LD": "LOAD"}
APST = {"SC": "SCHEDULED", "AR": "ARRIVED", "CP": "COMPLETED"}
ASST = {"SC": "SCHEDULED", "AR": "ARRIVED", "RG": "RECEIVING", "RC": "RECEIVED"}
PDIR = DRDI
PLST = {"PP": "PUTAWAY PENDING", "SL": "STAGED FOR LOAD", "PC": "PUTAWAY COMPLETE",
        "SH": "SHIPPED"}
LCST = {"AV": "AVAILABLE", "BL": "BLOCKED"}
ITST = {"AC": "ACTIVE", "IA": "INACTIVE"}
IVST = {"AV": "AVAILABLE IN BIN", "PP": "ON INBOUND PALLET", "SL": "ON OUTBOUND PALLET",
        "PK": "PICKED FOR ORDER"}
ORST = {"NW": "NEW/OPEN", "RL": "RELEASED", "PI": "PICKING", "PD": "PICKED",
        "PK": "PACKED", "SH": "SHIPPED", "CN": "CANCELLED"}
LNST = {"OP": "OPEN", "PA": "PART PICKED", "PD": "PICKED", "SX": "SHORTED"}
WVST = {"PL": "PLANNED", "RL": "RELEASED"}
DLST = {"PK": "PACKED", "SH": "SHIPPED"}
LDST = {"PL": "PLANNED", "LG": "LOADING", "SH": "SHIPPED"}
TKTY = {"PK": "PICK", "PU": "PUTAWAY", "CN": "COUNT", "PA": "PACK"}
TKST = {"OP": "OPEN", "CP": "COMPLETE"}
CCST = {"OP": "OPEN", "CM": "COUNT MATCHED", "RC": "VARIANCE - RECOUNT"}
EXKD = {"DM": "DAMAGE", "LB": "LOCATION BLOCKED", "CV": "COUNT VARIANCE",
        "SR": "SHORT RECEIPT", "OR": "OVER RECEIPT", "SP": "SHORT PICK/SHIPMENT",
        "OT": "OTHER"}
EXEN = {"AS": "ASN", "BN": "BIN", "OR": "ORDER", "IT": "ITEM", "OT": "OTHER"}
EXSV = {"L": "LOW", "M": "MEDIUM", "H": "HIGH"}
EXST = {"OP": "OPEN", "CL": "CLOSED"}
USSH = {"DY": "DAY", "SW": "SWING", "NT": "NIGHT"}
USST = {"AC": "ACTIVE", "IA": "INACTIVE"}
LBST = {"OP": "OPEN", "CL": "CLOSED"}
LGTY = {"OP": "OPENING BALANCE", "RC": "RECEIPT", "PU": "PUTAWAY", "AJ": "ADJUSTMENT",
        "PI": "PICK", "PK": "PACK", "SH": "SHIP"}

# Reason code for ADJT (RSN field).
ADJ_REASONS = {"01": "COUNT CORRECTION", "02": "DAMAGE", "03": "FOUND",
               "04": "LOST", "05": "OTHER"}
# Task codes for LABR (RSN field).
TASKS = {"RC": "RECEIVING", "PU": "PUTAWAY", "PI": "PICKING", "PK": "PACKING",
         "SH": "SHIPPING", "CN": "COUNTING", "OT": "OTHER"}
LABR_FLAGS = {"ST": "START", "EN": "END"}

# Dataset word -> code (seed step). Unknown words stop the seed.
WORDS = {
    "ZNTY": {"reserve": "RS", "pick": "PK", "overflow": "OV"},
    "DRDI": {"inbound": "IN", "outbound": "OU"},
    "DRST": {"free": "FR", "occupied": "OC", "closed": "CL"},
    "RFTY": {"asn": "AS", "load": "LD"},
    "APST": {"scheduled": "SC", "arrived": "AR", "completed": "CP"},
    "ASST": {"scheduled": "SC", "arrived": "AR", "receiving": "RG", "received": "RC"},
    "PLST": {"putaway_pending": "PP", "staged_for_load": "SL"},
    "LCST": {"active": "AV", "blocked": "BL"},
    "ITST": {"active": "AC", "inactive": "IA"},
    "ORST": {"open": "NW", "released": "RL", "picking": "PI", "picked": "PD",
             "packed": "PK", "shipped": "SH", "cancelled": "CN"},
    "WVST": {"planned": "PL", "released": "RL"},
    "DLST": {"packed": "PK", "shipped": "SH"},
    "LDST": {"planned": "PL", "loading": "LG", "shipped": "SH"},
    "TKTY": {"pick": "PK", "putaway": "PU", "count": "CN", "pack": "PA"},
    "TKST": {"open": "OP", "completed": "CP"},
    "CCST": {"open": "OP"},
    "EXKD": {"damage": "DM", "location_blocked": "LB", "count_variance": "CV",
             "short_receipt": "SR", "over_receipt": "OR", "short_pick": "SP",
             "other": "OT"},
    "EXEN": {"asn": "AS", "bin": "BN", "order": "OR", "item": "IT", "other": "OT"},
    "EXSV": {"low": "L", "medium": "M", "high": "H"},
    "EXST": {"open": "OP", "closed": "CL"},
    "USSH": {"day": "DY", "swing": "SW", "night": "NT"},
    "USST": {"active": "AC", "inactive": "IA"},
    "LGTY": {"opening": "OP", "receipt": "RC", "putaway": "PU", "adjustment": "AJ",
             "pick": "PI", "pack": "PK", "ship": "SH"},
}

# Every code table, for the COD file: name -> dict.
CODE_TABLES = {n: v for n, v in sorted(globals().items())
               if n.isupper() and isinstance(v, dict) and n not in
               ("WORDS", "ACTS", "REJECTS", "ALARMS", "CODE_TABLES")
               and n not in ("ADIR", "PDIR")}

PICK_PREFIX = "PK-"    # pick (order) location key = PK- + order number
LANE_PREFIX = "STG-"   # staging lane = STG- + door number
