"""Command line: python -m legacy_wms <host-dir> <command> [args]

  seed DATASET.json      build master files from the canonical dataset
  src SRCID              register an integration source (first control no = 1)
  batch                  run one batch now
  extract D|F            build delta or full extract files
  alarms                 list operator alarms
  tui                    open the terminal screens
"""
import datetime
import sys

from . import batch as B
from . import extract as X
from .seed import seed_from_file, SeedError
from .store import Host


def clock():
    n = datetime.datetime.now()
    return n.strftime("%Y%m%d"), n.strftime("%H%M")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    h = Host.open(argv[0])
    cmd, args = argv[1], argv[2:]
    if cmd == "seed" and args:
        try:
            seed_from_file(h, args[0])
        except SeedError as e:
            print("SEED STOPPED:", e)
            return 1
        print("SEED OK")
    elif cmd == "src" and args:
        h.add_source(args[0])
        h.save()
    elif cmd == "batch":
        print(B.run_batch(h, clock(), "OPER"))
    elif cmd == "extract":
        mode = (args[0] if args else "D").upper()
        for p in X.build_extract(h, clock(), mode):
            print(p.name)
        h.save()
    elif cmd == "alarms":
        for a in h.alarms:
            print(a)
    elif cmd == "tui":
        from .tui import run_curses
        run_curses(h, clock)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
