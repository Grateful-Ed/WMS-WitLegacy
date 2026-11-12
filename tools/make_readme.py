"""Build README.md from the code, so the contract cannot drift from the software.
Run:  python3 tools/make_readme.py            (writes README.md)
Test: tests/test_readme.py fails if README.md is out of date."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from legacy_wms import codes as C  # noqa: E402
from legacy_wms import fixed as F  # noqa: E402

TEMPLATE = (ROOT / "tools" / "README.template.md").read_text()


def layout_table(lay):
    out = ["| Field | Pos | Len | Kind |", "|---|---|---|---|"]
    pos = 1
    for n, w, k in lay.fields:
        out.append(f"| {n} | {pos} | {w} | {k} |")
        pos += w
    out.append(f"\nRecord length: {lay.width}.")
    return "\n".join(out)


def code_table(d):
    return "| Code | Meaning |\n|---|---|\n" + "\n".join(f"| {k} | {v} |" for k, v in sorted(d.items()))


def build():
    text = TEMPLATE
    subs = {"DETAIL": F.DETAIL, "HEADER": F.HEADER, "TRAILER": F.TRAILER, "CONF": F.CONF,
            "REJ": F.REJ, "OUT_HEADER": F.OUT_HEADER, "OUT_TRAILER": F.OUT_TRAILER,
            "EXT_HEADER": F.EXT_HEADER}
    for k, lay in subs.items():
        text = text.replace("{{LAYOUT:%s}}" % k, layout_table(lay))
    master = []
    for name, lay in F.LAYOUTS.items():
        master.append(f"### {name}  (key: {', '.join(F.KEYS[name])})\n\n{layout_table(lay)}\n")
    text = text.replace("{{MASTER}}", "\n".join(master))
    ctl = []
    for title, lay in (("SRC - source control (CTL/SRC.DAT)", F.SRC),
                       ("LDG - file ledger (CTL/LEDGER.DAT)", F.LDG),
                       ("ALM - operator alarms (CTL/ALARM.DAT)", F.ALM),
                       ("EXT - extract control (CTL/EXTCTL.DAT)", F.EXT)):
        ctl.append(f"### {title}\n\n{layout_table(lay)}\n")
    text = text.replace("{{CONTROL}}", "\n".join(ctl))
    text = text.replace("{{RECLEN}}", str(F.RECLEN)).replace("{{CONFLEN}}", str(F.CONF.width)).replace("{{REJLEN}}", str(F.REJ.width))
    text = text.replace("{{ACTS}}", code_table(C.ACTS))
    text = text.replace("{{REJECTS}}", code_table(C.REJECTS))
    text = text.replace("{{ALARMS}}", code_table(C.ALARMS))
    status = []
    for name, tbl in C.CODE_TABLES.items():
        status.append(f"**{name}**\n\n{code_table(tbl)}\n")
    text = text.replace("{{STATUS}}", "\n".join(status))
    return text


if __name__ == "__main__":
    (ROOT / "README.md").write_text(build())
    print("README.md written")
