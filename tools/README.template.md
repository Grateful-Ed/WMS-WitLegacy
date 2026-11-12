# WMS-WitLegacy

A generic legacy warehouse management system (AS/400-era, PKMS class). It is a mock host for integration testing.

It is legacy in its **architecture**: files and batches only. There is no REST, no JSON API, no webhook, no event, no UUID and no millisecond time. Python 3 standard library only.

**This README is the integration contract.** Layout and code tables below are generated from the code (`python3 tools/make_readme.py`). A test fails if they drift.

## 1. How it works

```
 outside layer                          HOST (this program)                      outside layer
 -------------                          -------------------                      -------------
 write file to IN/  ---------------->   waits. Nothing runs on arrival.
                                        operator (or timer) runs the BATCH:
                                          1. release staged results to OUT/
                                          2. (not in nightly window) process IN/
                                             files in file order
                                          3. stage new CF/RJ result files
                                        results go to STAGE/ ------------>  appear in OUT/ at the
                                                                            NEXT batch (one batch later)
                                        EXTRACT job writes tables ------->  OUT/  (full or delta)
```

Folders under the host directory:

| Folder | Use |
|---|---|
| `IN/` | Drop folder. The outside layer writes inbound files here. |
| `STAGE/` | Result files made by this batch. Not yet visible to the outside layer. |
| `OUT/` | Released result files (confirm, reject) and extract files. |
| `ARCH/` | Processed inbound files. Re-sent copies get the suffix `.DUPnnnnnnnn`. |
| `ERR/` | Files that were refused as a whole (unreadable, unknown source, wrong name, different content). |
| `MASTER/` | Master files, one fixed-width file per table (`ITM.DAT` ...). |
| `CTL/` | Control files: batch number, sequences, sources, ledger, alarms, extract control, window. |
| `LOG/` | `BATCH.LOG`. |

All files are ASCII text. Every record in a file has the same length. Records end with a line feed. Text is upper case. There are no nulls: text uses spaces, numbers use zero fill. Dates are `YYYYMMDD`. Times are `HHMM`.

Field kinds: `A` text (left aligned, space filled) - `N` unsigned number (right aligned, zero filled) - `S` signed number (first character `+` or `-`, then zero filled digits) - `D` date `YYYYMMDD` (`00000000` means none).

## 2. Batch rules

* **Nothing is processed on arrival.** A batch is run by an operator (terminal, Batch Control, option 1; or `python -m legacy_wms HOSTDIR batch`) or by a timer that calls the same job.
* **Latency is counted in batches.** An act sent now lands in the next batch. Its confirm or reject record is written to `STAGE/` in that batch and appears in `OUT/` at the batch after it.
* **Nightly window.** Default `2200` up to (not including) `0500`. In the window a batch does not process `IN/` at all. It still releases staged results. The window is held in `CTL/WINDOW.CTL` (8 digits: start HHMM, end HHMM). Extracts may still be built in the window.
* **Strict file order.** Files are processed in file name order. File name is `SOURCE.NNNNNNNN` (source id, dot, control number), so order within a source is control number order.
* **Control numbers.** Each source has its own sequence, starting at 1, no gaps.
  * Next expected number: processed. Used up even if the file was rejected as a whole.
  * Lower than expected (re-send): not processed. Same content: reject record `F04`. Different content: reject record `F08`, alarm `A02`, file to `ERR/`.
  * Higher than expected (gap): alarm `A01`. The file and every later file of that source are **held** in `IN/`. Other sources continue. If the missing file arrives, the next batch processes it and the held files in order, and the alarm closes. The operator can instead choose **Skip gap** (Batch Control option 5): the missing numbers are written to the ledger as `SK` and processing resumes at the lowest held file.
* **Partial failure.** Each detail record is validated and applied alone. Bad records go to the reject file with a code. The rest of the file still processes. A file-level fault (trailer missing `F02`, count or hash mismatch `F03`, name not equal to header `F07`) rejects the whole file.
* **Unknown source** (`A04`) or **unreadable file** (`A03`): file moved to `ERR/`, alarm raised, no result file (the sender cannot be identified or trusted). Operators register sources first (Batch Control option 7, or `python -m legacy_wms HOSTDIR src SOURCEID`).
* **Commit.** Master data, ledger and control files are saved at the end of the batch. Files are replaced, never edited in place.

## 3. Inbound file (outside layer to host)

File name: `SOURCE.NNNNNNNN`. Every record is {{RECLEN}} characters (header and trailer are space filled to that length). One header, then detail records, then one trailer.

Header (`REC` = `H`):

{{LAYOUT:HEADER}}

Detail (`REC` = `D`). One act per record. Fields not used by an act are spaces or zeros.

{{LAYOUT:DETAIL}}

Trailer (`REC` = `T`). `NREC` is the number of detail records. `HASH` is the sum of the `QTY` field of all detail records (a non-numeric `QTY` counts as 0), modulo 10^12.

{{LAYOUT:TRAILER}}

### Acts

{{ACTS}}

Field use by act (USR is required on every act and must be a known user):

| ACT | Fields used | Effect |
|---|---|---|
| RCPT | DOC=ASN no, LIN=ASN line, ITM, QTY, DOR=inbound door, TLC=new pallet no | Creates inbound pallet in `STG-<door>` lane, stock status `PP`. ASN becomes `RG`, or `RC` when every line is complete. |
| PUTA | ITM, QTY, FLC=pallet, TLC=bin | Moves stock from pallet to bin (status `AV`). Pallet becomes `PC` when empty. Closes the open putaway task for that pallet and item. |
| ADJT | ITM, FLC=bin, QTY, SGN (`+` or `-`), RSN (adjust reason) | Adds or removes bin stock. |
| RLSE | DOC=order | `NW` to `RL`. |
| PICK | DOC=order, LIN (0 = any), ITM, QTY, FLC=bin | Bin stock moves to pick location `PK-<order>` (status `PK`). Line and order status advance. Closes the matching pick task. When the last line is picked (or shorted) the order is `PD` and the host makes one open pack task (`TKTY` = `PA`) for it. |
| SHRT | DOC=order, LIN | Shorts the rest of a line (`SX`). |
| PACK | DOC=order | Order `PD` to `PK`. Makes delivery `OD-nnnn` and the next outbound pallet `PAL-nnn` (status `SL`, `PAL.DLNO` = the delivery). The order's picked stock moves from `PK-<order>` to the pallet (stock status `SL`). Closes the open pack task. |
| LOAD | DOC=delivery, TLC=load | Puts a packed delivery on a load. Load becomes `LG`. The delivery's pallets move to the lane `STG-<load door>`. |
| SHIP | DOC=load, DOR=outbound door of the load, TLC=seal no | Ships the load. Deliveries, orders, pallets (to `SH`), appointment advance. Pallet stock goes to zero. |
| CNTS | ITM, FLC=bin, QTY=counted | Writes the count (opens a new `CC-nnn` if none open). A variance makes exception kind `CV`. |
| EXCP | RSN=kind, FLG=entity, DOC=entity id, SGN=severity, TXT | Logs an exception. |
| LABR | FLG (`ST`/`EN`), RSN=task (start), QTY=units (end) | Labor start or end. One open task per user. |

ADJT reason codes (RSN): 01 count correction, 02 damage, 03 found, 04 lost, 05 other. Task codes (RSN for LABR start) are in the `TASK` table below.

## 4. Result files (host to outside layer)

Names: `SOURCE.Cnnnnnnnn` (confirm) and `SOURCE.Rnnnnnnnn` (reject). The number is the output control number for that source and kind (it counts up with no gaps). A file is written only when it has records. One file per source per batch, covering all inbound files of that batch. Records are {{CONFLEN}} characters (confirm) or {{REJLEN}} characters (reject); header and trailer are space filled to that length.

Header (both kinds, `KIND` = `CF` or `RJ`):

{{LAYOUT:OUT_HEADER}}

Confirm detail (`REC` = `C`, `RSLT` = `OK`):

{{LAYOUT:CONF}}

Reject detail (`REC` = `R`). `RCD` is the reason code. `IMG` is the original record as received, so the sender can correct it. A file-level reject has `SEQ` = 0 and a blank `IMG`.

{{LAYOUT:REJ}}

Trailer:

{{LAYOUT:OUT_TRAILER}}

### Reject codes

{{REJECTS}}

### Operator alarm codes

Alarms are kept in `CTL/ALARM.DAT` and shown on the terminal (main menu shows the open count).

{{ALARMS}}

## 5. Extract files (host to outside layer)

One file per table: `TBL.Xnnnnnnnn` in `OUT/`, `nnnnnnnn` = extract control number for that table. First line is the header, last line is the trailer, lines between are table records in the table layout (section 6). Header and trailer are not padded.

* **Full** (`MODE` = `F`): every row of the table.
* **Delta** (`MODE` = `D`): rows whose last-change batch number (`LCB`) is newer than the last extract of that table. `FBCH` in the header is the batch number the delta starts after. A delta can repeat a row it already sent. The reader replaces rows by key. A full extract plus all deltas after it rebuilds the table. Rows are never deleted (stock rows go to quantity zero).
* Extract jobs run from Batch Control (options 2 and 3) or `python -m legacy_wms HOSTDIR extract D|F`. Build a full extract first.
* `LCB` is the batch number in which the row last changed. Terminal changes made between batches carry the next batch number.

Header:

{{LAYOUT:EXT_HEADER}}

Trailer: same as the result file trailer (above).

## 6. Master tables (extract layouts)

Field names are 4 characters. All tables end with `LCB`. Keys are the ids from the canonical dataset, in upper case.

{{MASTER}}

Notes:

* `INV` holds stock by location, item and stock status. Locations are bins, pallets, or pick locations `PK-<order>`.
* `TRN` is the stock ledger. Opening rows come from the dataset. The host adds one row for each stock movement (`RC`, `PU`, `AJ`, `PI`, `PK`, `SH`) with ids `LG-nnnnnn`.
* Orders belong to a wave through `OHD.WVNO`. Deliveries belong to a load through `DLV.LDNO`. Pallets belong to a delivery through `PAL.DLNO`.
* `COD` is the code table dump (section 8). Decode every 2-character code from it.

## 7. Control files

{{CONTROL}}

## 8. Code tables

{{STATUS}}

Location keys: pick location = `PK-` + order number. Staging lane = `STG-` + door number.

## 9. Operator terminal

```
python3 -m legacy_wms HOSTDIR tui
```

80 x 24 character screens. Green on black when the terminal supports colour. `F3` leaves. `F12` goes back. `ENTER` submits. If the keyboard has no function keys, `ESC` works as `F12`.

Main menu: 1 Receiving, 2 Putaway, 3 Inventory (inquiry by item, by bin, adjust), 4 Orders, 5 Picking, 6 Packing, 7 Shipping (load, ship), 8 Cycle counts, 9 Exceptions, 10 Labor, 11 Batch control (run batch, extracts, alarms, skip gap, clear alarm, register source, file queues, batch log).

The operator works directly in the host. Terminal entries use the same rules as batch records and show reject codes at once (line 23).

## 10. Run it

```
python3 -m legacy_wms HOSTDIR seed data/canonical_dataset.json
python3 -m legacy_wms HOSTDIR src EXT00001
python3 -m legacy_wms HOSTDIR batch
python3 -m legacy_wms HOSTDIR extract F
python3 -m legacy_wms HOSTDIR tui
python3 -m unittest discover -s tests
```

`flatfile.py` has `build_inbound()` and `read_records()`, a reference writer and reader for the outside layer.

## 11. Seed

`data/canonical_dataset.json` is the canonical warehouse. `legacy_wms/seed.py` converts every value into legacy shape (upper case, code tables, `YYYYMMDD`, zero padding, weights in grams). It adds nothing. A value it has no code for stops the seed with a message. The same dataset always gives byte-identical master files.

The dataset block `labor_overload` is a scenario note, not warehouse state. It is not loaded. The same condition shows in the data: zone ZB has 14 open pick tasks in `TSK` and 2 workers in `USR`.

## 12. Decisions the specification did not make

* Language and storage: Python 3, standard library only. Master data is fixed-width files, not a database.
* Dataset ids are kept as keys (upper case). They are not renumbered.
* The host never sends data on its own. A reader gets files in `OUT/`.
* Results come one batch later, by design.
* The nightly window does not stop extracts.
* Control numbers are per source, file names carry them, and a rejected file still uses its number.
* Deltas can repeat rows (at-least-once). Readers replace by key.
* Seconds in dataset times are dropped (`HHMM`).
* Waves are not changed by acts. Wave and order status change only by `RLSE`, `PICK`, `SHRT`, `PACK`, `LOAD`, `SHIP`.
* PACK makes the outbound pallet (like the dataset's own packed deliveries). Its lane is blank until LOAD sets `STG-<load door>`. One pallet carries all the stock of the order.
* The pack move (`PK-<order>` to pallet) writes one `TRN` row per item, type `PK`, from the pick location to the pallet, `REF` = order.
* The pack task is made when the order becomes fully picked. Zone = zone of the last bin picked (blank if the last step was a `SHRT`). It is unassigned. `QTY` = total picked. `FBIN` = `PK-<order>`. `TBIN` and `PLNO` are filled when PACK closes it.
* Pallet ids and task ids continue after the highest dataset number (`PAL-nnn`, `TK-nnnn`). A minted id skips any id already in use.
* Unknown source or unreadable file gives an alarm and no result file.
* The `EX-nnn`, `CC-nnn`, `OD-nnnn` and `LG-nnnnnn` ids continue after the highest dataset number.
