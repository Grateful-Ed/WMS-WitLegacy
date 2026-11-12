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

All files are ASCII text. Every record in a file has the same length, except extract files: their header and trailer are not padded to the table width (section 5). Records end with a line feed. Text is upper case. There are no nulls: text uses spaces, numbers use zero fill. Dates are `YYYYMMDD`. Times are `HHMM`.

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
* **Whole-file refusals.** The file **name** (`SOURCE.NNNNNNNN`) says who sent it and which number it is.
  * Name cannot be read (for example `notes.txt`): file to `ERR/`, alarm `A03`.
  * Source in the name is not registered: file to `ERR/`, alarm `A04`.
  * Header unreadable (garbage, empty, bad header date) and the number is the next expected: file to `ERR/`, alarm `A03` kept, the number is **used up** (ledger row `UR`), no result file (the sender is not trusted). The sender's next file processes normally.
  * Header says another source or number than the name (`F07`): the reject goes under the **name's** source. If it is that source's next number, the number is used up. The header's source is not touched.
  * A late file for a number the operator skipped is a duplicate: archived, reject `F04`, no `A02`.
  Operators register sources first (Batch Control option 7, or `python -m legacy_wms HOSTDIR src SOURCEID`).
* **Commit.** Master data, ledger and control files are saved at the end of the batch. Files are replaced, never edited in place.

## 3. Inbound file (outside layer to host)

File name: `SOURCE.NNNNNNNN`. Every record is 151 characters (header and trailer are space filled to that length). One header, then detail records, then one trailer.

Header (`REC` = `H`):

| Field | Pos | Len | Kind |
|---|---|---|---|
| REC | 1 | 1 | A |
| SRC | 2 | 8 | A |
| ICTL | 10 | 8 | N |
| FDAT | 18 | 8 | D |
| FTIM | 26 | 4 | N |

Record length: 29.

Detail (`REC` = `D`). One act per record. Fields not used by an act are spaces or zeros.

| Field | Pos | Len | Kind |
|---|---|---|---|
| REC | 1 | 1 | A |
| SEQ | 2 | 6 | N |
| ACT | 8 | 4 | A |
| USR | 12 | 8 | A |
| DOC | 20 | 12 | A |
| LIN | 32 | 4 | N |
| ITM | 36 | 20 | A |
| QTY | 56 | 9 | N |
| SGN | 65 | 1 | A |
| FLC | 66 | 12 | A |
| TLC | 78 | 12 | A |
| DOR | 90 | 6 | A |
| RSN | 96 | 2 | A |
| FLG | 98 | 2 | A |
| ADT | 100 | 8 | D |
| ATM | 108 | 4 | N |
| TXT | 112 | 40 | A |

Record length: 151.

Trailer (`REC` = `T`). `NREC` is the number of detail records. `HASH` is the sum of the `QTY` field of all detail records (a non-numeric `QTY` counts as 0), modulo 10^12.

| Field | Pos | Len | Kind |
|---|---|---|---|
| REC | 1 | 1 | A |
| NREC | 2 | 6 | N |
| HASH | 8 | 12 | N |

Record length: 19.

### Acts

| Code | Meaning |
|---|---|
| ADJT | INVENTORY ADJUST |
| CNTS | COUNT SUBMIT |
| EXCP | LOG EXCEPTION |
| LABR | LABOR START/END |
| LOAD | PUT DELIVERY ON LOAD |
| PACK | PACK ORDER (MAKES DELIVERY) |
| PICK | PICK TO ORDER |
| PUTA | PUTAWAY DOCK TO BIN |
| RCPT | RECEIVE TO DOCK |
| RLSE | RELEASE ORDER |
| SHIP | SHIP LOAD |
| SHRT | SHORT AN ORDER LINE |

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

Names: `SOURCE.Cnnnnnnnn` (confirm) and `SOURCE.Rnnnnnnnn` (reject). The number is the output control number for that source and kind (it counts up with no gaps). A file is written only when it has records. One file per source per batch, covering all inbound files of that batch. Records are 82 characters (confirm) or 234 characters (reject); header and trailer are space filled to that length.

Header (both kinds, `KIND` = `CF` or `RJ`):

| Field | Pos | Len | Kind |
|---|---|---|---|
| REC | 1 | 1 | A |
| SRC | 2 | 8 | A |
| OCTL | 10 | 8 | N |
| KIND | 18 | 2 | A |
| BTCH | 20 | 8 | N |
| PDAT | 28 | 8 | D |

Record length: 35.

Confirm detail (`REC` = `C`, `RSLT` = `OK`):

| Field | Pos | Len | Kind |
|---|---|---|---|
| REC | 1 | 1 | A |
| ICTL | 2 | 8 | N |
| SEQ | 10 | 6 | N |
| ACT | 16 | 4 | A |
| DOC | 20 | 12 | A |
| LIN | 32 | 4 | N |
| ITM | 36 | 20 | A |
| QTY | 56 | 9 | N |
| RSLT | 65 | 2 | A |
| BTCH | 67 | 8 | N |
| PDAT | 75 | 8 | D |

Record length: 82.

Reject detail (`REC` = `R`). `RCD` is the reason code. `IMG` is the original record as received, so the sender can correct it. A file-level reject has `SEQ` = 0 and a blank `IMG`.

| Field | Pos | Len | Kind |
|---|---|---|---|
| REC | 1 | 1 | A |
| ICTL | 2 | 8 | N |
| SEQ | 10 | 6 | N |
| ACT | 16 | 4 | A |
| DOC | 20 | 12 | A |
| LIN | 32 | 4 | N |
| ITM | 36 | 20 | A |
| QTY | 56 | 9 | N |
| RCD | 65 | 3 | A |
| BTCH | 68 | 8 | N |
| PDAT | 76 | 8 | D |
| IMG | 84 | 151 | A |

Record length: 234.

Trailer:

| Field | Pos | Len | Kind |
|---|---|---|---|
| REC | 1 | 1 | A |
| NREC | 2 | 8 | N |

Record length: 9.

### Reject codes

| Code | Meaning |
|---|---|
| B01 | UNKNOWN ITEM |
| B02 | ITEM NOT ACTIVE |
| B03 | UNKNOWN LOCATION |
| B04 | LOCATION BLOCKED |
| B05 | OVER LOCATION CAPACITY |
| B06 | INSUFFICIENT STOCK |
| B07 | UNKNOWN ORDER |
| B08 | ORDER STATUS WRONG FOR ACT |
| B09 | ORDER LINE NOT FOUND OR OVER QTY |
| B10 | UNKNOWN DOOR |
| B11 | DOOR CLOSED OR WRONG TYPE |
| B12 | ORDER NOT READY FOR ACT |
| B14 | PALLET ALREADY EXISTS |
| B15 | UNKNOWN USER |
| B16 | USER ALREADY ON A TASK |
| B17 | USER HAS NO OPEN TASK |
| B18 | UNKNOWN ASN |
| B19 | ASN NOT ARRIVED OR ALREADY RECEIVED |
| B20 | OVER RECEIPT |
| B21 | UNKNOWN PALLET OR WRONG PALLET TYPE |
| B23 | UNKNOWN DELIVERY |
| B24 | UNKNOWN LOAD |
| B25 | LOAD NOT OPEN FOR THIS ACT |
| F02 | TRAILER MISSING OR BAD |
| F03 | TRAILER COUNT OR HASH MISMATCH |
| F04 | DUPLICATE OR SKIPPED FILE - NOT PROCESSED |
| F07 | FILE NAME DOES NOT MATCH HEADER |
| F08 | SAME CONTROL NO, DIFFERENT CONTENT |
| R01 | BAD RECORD (LENGTH, TYPE, OR HOST COULD NOT PROCESS IT) |
| R02 | UNKNOWN ACT CODE |
| R03 | NON-NUMERIC IN NUMERIC FIELD |
| R04 | BAD DATE |
| R05 | QUANTITY MUST BE GREATER THAN ZERO |
| R06 | BAD REASON OR FLAG CODE |
| R07 | REQUIRED FIELD BLANK |

### Operator alarm codes

Alarms are kept in `CTL/ALARM.DAT` and shown on the terminal (main menu shows the open count).

| Code | Meaning |
|---|---|
| A01 | GAP IN CONTROL NUMBER SEQUENCE - FILES HELD |
| A02 | RE-SENT FILE HAS DIFFERENT CONTENT |
| A03 | UNREADABLE FILE MOVED TO ERR |
| A04 | FILE FROM UNKNOWN SOURCE |

## 5. Extract files (host to outside layer)

One file per table: `TBL.Xnnnnnnnn` in `OUT/`, `nnnnnnnn` = extract control number for that table. First line is the header, last line is the trailer, lines between are table records in the table layout (section 6). Header and trailer are not padded.

* **Full** (`MODE` = `F`): every row of the table.
* **Delta** (`MODE` = `D`): rows whose last-change batch number (`LCB`) is newer than the last extract of that table. `FBCH` in the header is the batch number the delta starts after. A delta can repeat a row it already sent. The reader replaces rows by key. A full extract plus all deltas after it rebuilds the table. A delta built before any full extract has zero rows by design: build a full extract first. Rows are never deleted (stock rows go to quantity zero).
* Extract jobs run from Batch Control (options 2 and 3) or `python -m legacy_wms HOSTDIR extract D|F`. Build a full extract first.
* `LCB` is the batch number in which the row last changed. Terminal changes made between batches carry the next batch number.

Header:

| Field | Pos | Len | Kind |
|---|---|---|---|
| REC | 1 | 1 | A |
| TBLN | 2 | 3 | A |
| XCTL | 5 | 8 | N |
| MODE | 13 | 1 | A |
| ASOF | 14 | 8 | D |
| BTCH | 22 | 8 | N |
| FBCH | 30 | 8 | N |

Record length: 37.

Trailer: same as the result file trailer (above).

## 6. Master tables (extract layouts)

Field names are 4 characters. All tables end with `LCB`. Keys are the ids from the canonical dataset, in upper case.

### WHS  (key: WHID)

| Field | Pos | Len | Kind |
|---|---|---|---|
| WHID | 1 | 8 | A |
| WHNM | 9 | 30 | A |
| WHTZ | 39 | 4 | A |
| SDAT | 43 | 8 | D |
| STIM | 51 | 4 | N |
| LCB | 55 | 8 | N |

Record length: 62.

### ZON  (key: ZNID)

| Field | Pos | Len | Kind |
|---|---|---|---|
| ZNID | 1 | 2 | A |
| ZNDS | 3 | 20 | A |
| ZNTY | 23 | 2 | A |
| LCB | 25 | 8 | N |

Record length: 32.

### DEP  (key: DPID)

| Field | Pos | Len | Kind |
|---|---|---|---|
| DPID | 1 | 3 | A |
| DPDS | 4 | 20 | A |
| LCB | 24 | 8 | N |

Record length: 31.

### ITM  (key: ITNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| ITNO | 1 | 20 | A |
| ITDS | 21 | 30 | A |
| IUOM | 51 | 2 | A |
| ICSQ | 53 | 5 | N |
| IWGT | 58 | 7 | N |
| IPBN | 65 | 12 | A |
| ITST | 77 | 2 | A |
| LCB | 79 | 8 | N |

Record length: 86.

### LOC  (key: LCNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| LCNO | 1 | 12 | A |
| LCZN | 13 | 2 | A |
| LCAI | 15 | 2 | A |
| LCPS | 17 | 2 | A |
| LCCP | 19 | 9 | N |
| LCST | 28 | 2 | A |
| LCB | 30 | 8 | N |

Record length: 37.

### DOR  (key: DRNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| DRNO | 1 | 6 | A |
| DRDS | 7 | 20 | A |
| DRDI | 27 | 2 | A |
| DRST | 29 | 2 | A |
| DRRT | 31 | 2 | A |
| DRRF | 33 | 12 | A |
| LCB | 45 | 8 | N |

Record length: 52.

### APT  (key: APNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| APNO | 1 | 8 | A |
| DRNO | 9 | 6 | A |
| ADIR | 15 | 2 | A |
| RFTY | 17 | 2 | A |
| RFNO | 19 | 12 | A |
| SDAT | 31 | 8 | D |
| STIM | 39 | 4 | N |
| EDAT | 43 | 8 | D |
| ETIM | 51 | 4 | N |
| APST | 55 | 2 | A |
| LCB | 57 | 8 | N |

Record length: 64.

### ASH  (key: ASNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| ASNO | 1 | 8 | A |
| SUPL | 9 | 30 | A |
| ASST | 39 | 2 | A |
| DRNO | 41 | 6 | A |
| APNO | 47 | 8 | A |
| ARDT | 55 | 8 | D |
| ARTM | 63 | 4 | N |
| LCB | 67 | 8 | N |

Record length: 74.

### ASL  (key: ASNO, LNNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| ASNO | 1 | 8 | A |
| LNNO | 9 | 4 | N |
| ITNO | 13 | 20 | A |
| EXQT | 33 | 9 | N |
| RCQT | 42 | 9 | N |
| LCB | 51 | 8 | N |

Record length: 58.

### PAL  (key: PLNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| PLNO | 1 | 8 | A |
| PDIR | 9 | 2 | A |
| LANE | 11 | 8 | A |
| PLST | 19 | 2 | A |
| ASNO | 21 | 8 | A |
| ASLN | 29 | 4 | N |
| DLNO | 33 | 8 | A |
| LCB | 41 | 8 | N |

Record length: 48.

### INV  (key: LCNO, ITNO, IVST)

| Field | Pos | Len | Kind |
|---|---|---|---|
| LCNO | 1 | 12 | A |
| ITNO | 13 | 20 | A |
| IVST | 33 | 2 | A |
| ONHD | 35 | 9 | N |
| LCB | 44 | 8 | N |

Record length: 51.

### TRN  (key: LGNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| LGNO | 1 | 9 | A |
| LGDT | 10 | 8 | D |
| LGTM | 18 | 4 | N |
| LGTY | 22 | 2 | A |
| ITNO | 24 | 20 | A |
| FLOC | 44 | 12 | A |
| TLOC | 56 | 12 | A |
| QTY | 68 | 9 | N |
| REF | 77 | 12 | A |
| LCB | 89 | 8 | N |

Record length: 96.

### OHD  (key: ORNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| ORNO | 1 | 8 | A |
| CUNM | 9 | 30 | A |
| ORST | 39 | 2 | A |
| WVNO | 41 | 8 | A |
| DLNO | 49 | 8 | A |
| SHDT | 57 | 8 | D |
| LCB | 65 | 8 | N |

Record length: 72.

### OLN  (key: ORNO, LNNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| ORNO | 1 | 8 | A |
| LNNO | 9 | 4 | N |
| ITNO | 13 | 20 | A |
| OQTY | 33 | 9 | N |
| PQTY | 42 | 9 | N |
| SQTY | 51 | 9 | N |
| LNST | 60 | 2 | A |
| LCB | 62 | 8 | N |

Record length: 69.

### WAV  (key: WVNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| WVNO | 1 | 8 | A |
| WVST | 9 | 2 | A |
| RLDT | 11 | 8 | D |
| RLTM | 19 | 4 | N |
| LCB | 23 | 8 | N |

Record length: 30.

### DLV  (key: DLNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| DLNO | 1 | 8 | A |
| ORNO | 9 | 8 | A |
| DLST | 17 | 2 | A |
| LDNO | 19 | 8 | A |
| SHDT | 27 | 8 | D |
| SHTM | 35 | 4 | N |
| LCB | 39 | 8 | N |

Record length: 46.

### LDS  (key: LDNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| LDNO | 1 | 8 | A |
| DRNO | 9 | 6 | A |
| CARR | 15 | 30 | A |
| LDST | 45 | 2 | A |
| APNO | 47 | 8 | A |
| SEAL | 55 | 12 | A |
| SHDT | 67 | 8 | D |
| SHTM | 75 | 4 | N |
| LCB | 79 | 8 | N |

Record length: 86.

### TSK  (key: TKNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| TKNO | 1 | 8 | A |
| TKTY | 9 | 2 | A |
| TKST | 11 | 2 | A |
| ZNID | 13 | 2 | A |
| ASGN | 15 | 8 | A |
| WVNO | 23 | 8 | A |
| ORNO | 31 | 8 | A |
| LNNO | 39 | 4 | N |
| ITNO | 43 | 20 | A |
| QTY | 63 | 9 | N |
| FBIN | 72 | 12 | A |
| TBIN | 84 | 12 | A |
| PLNO | 96 | 8 | A |
| CCNO | 104 | 8 | A |
| BNNO | 112 | 12 | A |
| CRDT | 124 | 8 | D |
| CRTM | 132 | 4 | N |
| CPDT | 136 | 8 | D |
| CPTM | 144 | 4 | N |
| CPBY | 148 | 8 | A |
| LCB | 156 | 8 | N |

Record length: 163.

### CCN  (key: CCNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| CCNO | 1 | 8 | A |
| BNNO | 9 | 12 | A |
| ITNO | 21 | 20 | A |
| CCST | 41 | 2 | A |
| TKNO | 43 | 8 | A |
| SQTY | 51 | 9 | N |
| CQTY | 60 | 9 | N |
| CVAR | 69 | 10 | S |
| LCB | 79 | 8 | N |

Record length: 86.

### EXC  (key: EXNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| EXNO | 1 | 8 | A |
| EXKD | 9 | 2 | A |
| EXEN | 11 | 2 | A |
| EXEI | 13 | 12 | A |
| EXSV | 25 | 1 | A |
| EXRS | 26 | 60 | A |
| EXST | 86 | 2 | A |
| EXDT | 88 | 8 | D |
| EXTM | 96 | 4 | N |
| EXBY | 100 | 8 | A |
| LCB | 108 | 8 | N |

Record length: 115.

### USR  (key: USNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| USNO | 1 | 8 | A |
| USNM | 9 | 30 | A |
| USDP | 39 | 3 | A |
| USZN | 42 | 2 | A |
| USSH | 44 | 2 | A |
| USST | 46 | 2 | A |
| LCB | 48 | 8 | N |

Record length: 55.

### LBL  (key: LBNO)

| Field | Pos | Len | Kind |
|---|---|---|---|
| LBNO | 1 | 8 | N |
| USNO | 9 | 8 | A |
| TKCD | 17 | 2 | A |
| SDAT | 19 | 8 | D |
| STIM | 27 | 4 | N |
| EDAT | 31 | 8 | D |
| ETIM | 39 | 4 | N |
| UNIT | 43 | 9 | N |
| LBST | 52 | 2 | A |
| LCB | 54 | 8 | N |

Record length: 61.

### COD  (key: TBLN, CODE)

| Field | Pos | Len | Kind |
|---|---|---|---|
| TBLN | 1 | 6 | A |
| CODE | 7 | 3 | A |
| CDSC | 10 | 40 | A |
| LCB | 50 | 8 | N |

Record length: 57.


Notes:

* `INV` holds stock by location, item and stock status. Locations are bins, pallets, or pick locations `PK-<order>`.
* `TRN` is the stock ledger. Opening rows come from the dataset. The host adds one row for each stock movement (`RC`, `PU`, `AJ`, `PI`, `PK`, `SH`) with ids `LG-nnnnnn`.
* Orders belong to a wave through `OHD.WVNO`. Deliveries belong to a load through `DLV.LDNO`. Pallets belong to a delivery through `PAL.DLNO`.
* Cycle counts (`CCN`): a quantity of 0 with status `OP` means not yet counted. The status tells it apart from a true zero count. A recount submit updates the same count record.
* `COD` is the code table dump (section 8). Decode every 2-character code from it.

## 7. Control files

### SRC - source control (CTL/SRC.DAT)

| Field | Pos | Len | Kind |
|---|---|---|---|
| SRCID | 1 | 8 | A |
| NEXT | 9 | 8 | N |
| LAST | 17 | 8 | N |
| OCF | 25 | 8 | N |
| ORJ | 33 | 8 | N |

Record length: 40.

### LDG - file ledger (CTL/LEDGER.DAT)

| Field | Pos | Len | Kind |
|---|---|---|---|
| SRCID | 1 | 8 | A |
| ICTL | 9 | 8 | N |
| CKSM | 17 | 8 | A |
| BTCH | 25 | 8 | N |
| DISP | 33 | 2 | A |
| NREC | 35 | 6 | N |
| NOK | 41 | 6 | N |
| NRJ | 47 | 6 | N |
| PDAT | 53 | 8 | D |

Record length: 60.

### ALM - operator alarms (CTL/ALARM.DAT)

| Field | Pos | Len | Kind |
|---|---|---|---|
| ALNO | 1 | 8 | N |
| ALCD | 9 | 3 | A |
| ALDT | 12 | 8 | D |
| ALTM | 20 | 4 | N |
| SRCID | 24 | 8 | A |
| ICTL | 32 | 8 | N |
| ALST | 40 | 2 | A |
| ALTX | 42 | 40 | A |

Record length: 81.

### EXT - extract control (CTL/EXTCTL.DAT)

| Field | Pos | Len | Kind |
|---|---|---|---|
| TBLN | 1 | 3 | A |
| XCTL | 4 | 8 | N |
| LBCH | 12 | 8 | N |

Record length: 19.


## 8. Code tables

**ADJ_REASONS**

| Code | Meaning |
|---|---|
| 01 | COUNT CORRECTION |
| 02 | DAMAGE |
| 03 | FOUND |
| 04 | LOST |
| 05 | OTHER |

**APST**

| Code | Meaning |
|---|---|
| AR | ARRIVED |
| CP | COMPLETED |
| SC | SCHEDULED |

**ASST**

| Code | Meaning |
|---|---|
| AR | ARRIVED |
| RC | RECEIVED |
| RG | RECEIVING |
| SC | SCHEDULED |

**CCST**

| Code | Meaning |
|---|---|
| CM | COUNT MATCHED |
| OP | OPEN |
| RC | VARIANCE - RECOUNT |

**DLST**

| Code | Meaning |
|---|---|
| PK | PACKED |
| SH | SHIPPED |

**DRDI**

| Code | Meaning |
|---|---|
| IN | INBOUND |
| OU | OUTBOUND |

**DRST**

| Code | Meaning |
|---|---|
| CL | CLOSED |
| FR | FREE |
| OC | OCCUPIED |

**EXEN**

| Code | Meaning |
|---|---|
| AS | ASN |
| BN | BIN |
| IT | ITEM |
| OR | ORDER |
| OT | OTHER |

**EXKD**

| Code | Meaning |
|---|---|
| CV | COUNT VARIANCE |
| DM | DAMAGE |
| LB | LOCATION BLOCKED |
| OR | OVER RECEIPT |
| OT | OTHER |
| SR | SHORT RECEIPT |

**EXST**

| Code | Meaning |
|---|---|
| CL | CLOSED |
| OP | OPEN |

**EXSV**

| Code | Meaning |
|---|---|
| H | HIGH |
| L | LOW |
| M | MEDIUM |

**ITST**

| Code | Meaning |
|---|---|
| AC | ACTIVE |
| IA | INACTIVE |

**IVST**

| Code | Meaning |
|---|---|
| AV | AVAILABLE IN BIN |
| PK | PICKED FOR ORDER |
| PP | ON INBOUND PALLET |
| SL | ON OUTBOUND PALLET |

**LABR_FLAGS**

| Code | Meaning |
|---|---|
| EN | END |
| ST | START |

**LBST**

| Code | Meaning |
|---|---|
| CL | CLOSED |
| OP | OPEN |

**LCST**

| Code | Meaning |
|---|---|
| AV | AVAILABLE |
| BL | BLOCKED |

**LDST**

| Code | Meaning |
|---|---|
| LG | LOADING |
| PL | PLANNED |
| SH | SHIPPED |

**LGTY**

| Code | Meaning |
|---|---|
| AJ | ADJUSTMENT |
| OP | OPENING BALANCE |
| PI | PICK |
| PK | PACK |
| PU | PUTAWAY |
| RC | RECEIPT |
| SH | SHIP |

**LNST**

| Code | Meaning |
|---|---|
| OP | OPEN |
| PA | PART PICKED |
| PD | PICKED |
| SX | SHORTED |

**ORST**

| Code | Meaning |
|---|---|
| CN | CANCELLED |
| NW | NEW/OPEN |
| PD | PICKED |
| PI | PICKING |
| PK | PACKED |
| RL | RELEASED |
| SH | SHIPPED |

**PLST**

| Code | Meaning |
|---|---|
| PC | PUTAWAY COMPLETE |
| PP | PUTAWAY PENDING |
| SH | SHIPPED |
| SL | STAGED FOR LOAD |

**RFTY**

| Code | Meaning |
|---|---|
| AS | ASN |
| LD | LOAD |

**TASKS**

| Code | Meaning |
|---|---|
| CN | COUNTING |
| OT | OTHER |
| PI | PICKING |
| PK | PACKING |
| PU | PUTAWAY |
| RC | RECEIVING |
| SH | SHIPPING |

**TKST**

| Code | Meaning |
|---|---|
| CP | COMPLETE |
| OP | OPEN |

**TKTY**

| Code | Meaning |
|---|---|
| CN | COUNT |
| PA | PACK |
| PK | PICK |
| PU | PUTAWAY |

**USSH**

| Code | Meaning |
|---|---|
| DY | DAY |
| NT | NIGHT |
| SW | SWING |

**USST**

| Code | Meaning |
|---|---|
| AC | ACTIVE |
| IA | INACTIVE |

**WVST**

| Code | Meaning |
|---|---|
| PL | PLANNED |
| RL | RELEASED |

**ZNTY**

| Code | Meaning |
|---|---|
| OV | OVERFLOW |
| PK | PICK |
| RS | RESERVE |


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
* Known limit: the batch commit is not atomic. File moves and the save of master and control files are separate steps, and an interruption between them can leave them out of step. Counter reconciliation protects the data: when the host opens, every id counter is raised to the highest number in use, and every allocation skips ids already in use, so a lost or old `SEQ.CTL` can never overwrite a live record.
* Tasks close by accumulation: a putaway task closes when the putaway for its pallet and item reaches the task quantity. A pick task closes when picks of that item from that bin for that order reach the task quantity (counted from the ledger).
* PACK is refused (`B12`) when the order's picked quantity is zero (fully shorted).
* ADJT needs `SGN` (`+` or `-`). A blank sign is `R07`.
* An unexpected error in one record rejects that record `R01`, undoes anything it half did, and is written to `BATCH.LOG`. The rest of the batch goes on.
* An F07 file with a number that is not the next expected is rejected and moved to `ERR/` without using a number.
* The `EX-nnn`, `CC-nnn`, `OD-nnnn` and `LG-nnnnnn` ids continue after the highest dataset number.
