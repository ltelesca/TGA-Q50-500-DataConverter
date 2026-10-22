"""Reader for TA Instruments Q-series raw data files (.001, .002, ...).

File layout (reverse-engineered from TGA Q500 files written by Q Series
software, validated against Universal Analysis text exports):

  1. UTF-16-LE text header (with BOM), CRLF-separated "Key value" lines
     (Sample, Size, Nsig, Sig1..SigN, OrgMethod, Date, Time, ...).
  2. A form-feed character U+000C (bytes 0C 00).
  3. One byte: number of signals N (matches the header's "Nsig").
  4. Records of N little-endian float32 values each, in header Sig order.
     Special records have a negative first value:
        -3   gas-switch event, second value = new gas number (1 or 2)
        -100 end of data; everything after it is housekeeping and ignored.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

END_MARKER = -100.0
GAS_EVENT = -3.0
RAW_EXT = re.compile(r"\.\d{3}$")  # .001, .002, ... .999


class TGAFormatError(Exception):
    pass


@dataclass
class TGARun:
    path: Path
    header: list[tuple[str, str]]
    signals: list[str]
    rows: list[tuple[float, ...]]
    gas: list[int | None]  # active gas for each row (None if unknown)
    gas_events: list[tuple[float, int]] = field(default_factory=list)  # (time, gas)
    event_rows: list[int] = field(default_factory=list)  # row index where each switch occurred
    complete: bool = True  # False if the end-of-data marker was missing

    def get(self, key: str, default: str = "") -> str:
        for k, v in self.header:
            if k == key:
                return v
        return default

    def get_all(self, key: str) -> list[str]:
        return [v for k, v in self.header if k == key]

    @property
    def sample_mass_mg(self) -> float | None:
        m = re.match(r"\s*([-+0-9.eE]+)\s*mg", self.get("Size"))
        return float(m.group(1)) if m else None


def is_raw_file(path: str | Path) -> bool:
    """True if the file is a TA Q-series raw data file, judged by its content.

    The extension is not reliable: users often name runs with dots
    ("6.27 MgCl 1 180") or rename files, so a raw file may not end in .001.
    Text exports from Universal Analysis also start with the same header
    but are tab-separated, so they are rejected.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(512)
    except OSError:
        return False
    if not head.startswith(b"\xff\xfe"):
        return False
    text = head[2:].decode("utf-16-le", errors="replace")
    return text.split("\r", 1)[0] in ("CLOSED", "ACTIVE", "OPEN") and "\t" not in text


def has_run_number(path: str | Path) -> bool:
    """True if the file name ends in a run number such as .001 or .002."""
    return bool(RAW_EXT.search(str(path)))


def _parse_header(text: str) -> list[tuple[str, str]]:
    out = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            continue
        key, _, val = line.partition(" ")
        out.append((key, val.strip()))
    return out


def read_tga(path: str | Path) -> TGARun:
    path = Path(path)
    data = path.read_bytes()
    if not data.startswith(b"\xff\xfe"):
        raise TGAFormatError("not a TA Instruments raw data file (no UTF-16 header)")

    # Find the U+000C separator on a UTF-16 code-unit boundary.
    pos = 2
    while True:
        pos = data.find(b"\x0c\x00", pos)
        if pos < 0:
            raise TGAFormatError("header terminator not found")
        if pos % 2 == 0:
            break
        pos += 1

    header = _parse_header(data[2:pos].decode("utf-16-le", errors="replace"))
    hdr = dict(header)
    signals = [v for k, v in header if re.fullmatch(r"Sig\d+", k)]
    nsig = data[pos + 2]
    try:
        hdr_nsig = int(hdr.get("Nsig", "0"))
    except ValueError:
        hdr_nsig = 0
    if nsig == 0 or (hdr_nsig and hdr_nsig != nsig) or len(signals) != nsig:
        raise TGAFormatError(
            f"inconsistent signal count (byte={nsig}, Nsig={hdr_nsig}, Sig lines={len(signals)})"
        )

    body = data[pos + 3:]
    rec = 4 * nsig
    n = len(body) // rec
    unpack = struct.Struct("<" + "f" * nsig).unpack_from

    # Initial gas: first "Select gas N" in the method, if any.
    gas: int | None = None
    for step in (v for k, v in header if k == "OrgMethod"):
        m = re.search(r"Select gas (\d)", step)
        if m:
            gas = int(m.group(1))
            break

    rows, gas_col, event_idx = [], [], []
    ended = False
    for i in range(n):
        r = unpack(body, i * rec)
        t = r[0]
        if t == END_MARKER:
            ended = True
            break
        if t < 0:
            if t == GAS_EVENT:
                gas = int(round(r[1]))
                event_idx.append((len(rows), gas))
            continue  # unknown event codes are skipped
        rows.append(r)
        gas_col.append(gas)

    if not rows:
        raise TGAFormatError("file contains no data points")

    # Event time = time of the first data point recorded after the switch.
    events = [(rows[i][0], g) for i, g in event_idx if i < len(rows)]
    event_rows = sorted({i for i, _ in event_idx if 0 < i < len(rows)})
    return TGARun(path, header, signals, rows, gas_col, events, event_rows, complete=ended)
