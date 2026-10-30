"""Run-type detection (ramp vs cycling) and per-run / per-cycle results."""

from __future__ import annotations

import re
from dataclasses import dataclass

# A new cycle starts when the temperature has dropped at least COOL_DROP_C
# below the highest temperature of the current cycle and then rises again by
# at least REHEAT_RISE_C. Isothermal holds, changes of heating rate and small
# dips (e.g. a 10-20 °C cool-down) therefore do not start a new cycle.
COOL_DROP_C = 50.0
REHEAT_RISE_C = 50.0
RESUME_RATE_C_MIN = 0.5  # a cycle starts where the heating rate rises above this (°C/min)
RATE_HALF_WINDOW = 10  # points either side used to judge the heating rate

STANDARD_LOSS_LEVELS = [1.0, 5.0, 10.0, 50.0]

RAMP = "ramp"
CYCLING = "cycling"


def _rate(t: list[float], T: list[float], j: int) -> float:
    a, b = max(0, j - RATE_HALF_WINDOW), min(len(T) - 1, j + RATE_HALF_WINDOW)
    return (T[b] - T[a]) / (t[b] - t[a]) if t[b] != t[a] else 0.0


def detect_cycles(t: list[float], T: list[float]) -> list[tuple[int, int]]:
    """Split a run into cycles. Returns [(start, end), ...] row ranges (end exclusive).

    The boundary is placed where heating resumes, so any hold at the low
    temperature (e.g. a CO2 uptake step) stays in the cycle it follows.
    """
    n = len(T)
    if n == 0:
        return []
    starts = [0]
    peak = T[0]
    cooling = False
    low = low_i = 0
    for i in range(n):
        x = T[i]
        if not cooling:
            if x > peak:
                peak = x
            elif peak - x >= COOL_DROP_C:
                cooling, low, low_i = True, x, i
        else:
            if x < low:
                low, low_i = x, i
            elif x - low >= REHEAT_RISE_C:
                j = i
                while j > low_i and _rate(t, T, j) > RESUME_RATE_C_MIN:
                    j -= 1
                starts.append(j)
                cooling, peak = False, x
    return list(zip(starts, starts[1:] + [n]))


_SETPOINT = re.compile(
    r"(?:Ramp [\d.]+ °C/min(?: res [-\d.]+ °C)? to|Equilibrate at|Jump to|Initial temp) ([-\d.]+) °C"
)


def method_programs_cooling(steps: list[str], start_temp: float) -> bool | None:
    """Does the method programme a cool-down of at least COOL_DROP_C followed by re-heating?

    Returns None when the file has no method steps. Used so that temperature
    drops the method did not ask for (e.g. Hi-Res runs, where the instrument
    slows down or reverses heating during fast mass loss) are not taken as cycles.
    """
    if not steps:
        return None
    peak = start_temp
    cooling = False
    low = 0.0
    for st in steps:
        m = _SETPOINT.search(st)
        if not m:
            continue
        x = float(m.group(1))
        if not cooling:
            if x > peak:
                peak = x
            elif peak - x >= COOL_DROP_C:
                cooling, low = True, x
        else:
            if x < low:
                low = x
            elif x - low >= REHEAT_RISE_C:
                return True
    return False


def parse_loss_levels(text: str) -> list[float]:
    """'2, 5; 20 %' -> [2.0, 5.0, 20.0]. Raises ValueError on bad input."""
    parts = [p for p in re.split(r"[,;\s%]+", text.strip()) if p]
    if not parts:
        raise ValueError("no values")
    vals = []
    for p in parts:
        v = float(p)
        if not 0 < v < 100:
            raise ValueError(f"{p} is not between 0 and 100")
        vals.append(v)
    return sorted(set(vals))


def temperature_at_loss(T: list[float], W: list[float], w_ref: float, loss: float) -> float | None:
    """Temperature where W first drops below w_ref * (1 - loss/100), linearly interpolated."""
    level = w_ref * (1 - loss / 100.0)
    for i in range(1, len(W)):
        if W[i] <= level < W[i - 1]:
            f = (W[i - 1] - level) / (W[i - 1] - W[i])
            return T[i - 1] + f * (T[i] - T[i - 1])
    return None


@dataclass
class SegmentResult:
    start_time: float
    end_time: float
    t_min: float
    t_max: float
    w_start: float
    w_end: float
    t_at_loss: dict[float, float | None]

    @property
    def change_pct(self) -> float:
        return 100.0 * (self.w_end - self.w_start) / self.w_start if self.w_start else float("nan")

    @property
    def residue_pct(self) -> float:
        return 100.0 * self.w_end / self.w_start if self.w_start else float("nan")


def segment_result(t, T, W, a: int, b: int, levels: list[float]) -> SegmentResult:
    Ts, Ws = T[a:b], W[a:b]
    return SegmentResult(
        start_time=t[a],
        end_time=t[b - 1],
        t_min=min(Ts),
        t_max=max(Ts),
        w_start=Ws[0],
        w_end=Ws[-1],
        t_at_loss={x: temperature_at_loss(Ts, Ws, Ws[0], x) for x in levels},
    )


@dataclass
class IntervalLoss:
    t_from: float
    t_to: float
    w_from: float | None = None
    w_to: float | None = None
    start_used: float | None = None  # actual temperature used for 'from' when the segment starts above it

    @property
    def reached(self) -> bool:
        return self.w_from is not None and self.w_to is not None

    @property
    def loss_mg(self) -> float | None:
        return self.w_from - self.w_to if self.reached else None


def _first_upward(T: list[float], W: list[float], target: float, start: int) -> tuple[float, int] | None:
    """Weight where the temperature first rises through `target` at or after index `start`."""
    for i in range(max(start, 1), len(T)):
        if T[i - 1] < target <= T[i]:
            f = (target - T[i - 1]) / (T[i] - T[i - 1])
            return W[i - 1] + f * (W[i] - W[i - 1]), i
    return None


def interval_loss(T: list[float], W: list[float], t_from: float, t_to: float) -> IntervalLoss:
    """Mass lost between the first time the temperature reaches t_from and then t_to (heating only).

    If the segment already starts above t_from (but below t_to), its first point is used
    instead and recorded in start_used.
    """
    res = IntervalLoss(t_from, t_to)
    if not T:
        return res
    if T[0] >= t_from:
        if T[0] >= t_to:
            return res
        res.w_from, i_from, res.start_used = W[0], 0, T[0]
    else:
        hit = _first_upward(T, W, t_from, 1)
        if hit is None:
            return res
        res.w_from, i_from = hit
    hit = _first_upward(T, W, t_to, i_from)
    if hit is None:
        res.w_from = None
        res.start_used = None
        return res
    res.w_to = hit[0]
    return res


# Dry-basis reference. An isothermal hold counts when the method programmes one
# ("Isothermal for N min") at the reference temperature (within HOLD_TOL_C), and it
# is the first time the run gets there. The data then give where the hold ends:
# where the temperature starts moving again (rate above RESUME_RATE_C_MIN) before
# leaving a +-HOLD_EXIT_C band around the reference.
HOLD_TOL_C = 3.0
HOLD_EXIT_C = 10.0
_ISOTHERMAL = re.compile(r"Isothermal for ([\d.]+) min")


@dataclass
class DryReference:
    target: float
    weight: float | None = None       # None = never reached
    hold: bool = False                # True = end of an isothermal hold at the target
    hold_temp: float | None = None    # programmed hold temperature
    hold_min: float | None = None     # programmed hold duration (min)
    time: float | None = None         # time of the reference point (min)


def programmed_hold(steps: list[str], target: float, start_temp: float) -> tuple[float, float] | None:
    """(set temperature, minutes) if the first setpoint at or above the target is an
    isothermal hold within HOLD_TOL_C of it; otherwise None."""
    sp = None
    for st in steps or []:
        m = _SETPOINT.search(st)
        if m:
            if sp is not None:
                return None  # next setpoint without an isothermal step in between
            x = float(m.group(1))
            if x >= target - HOLD_TOL_C and start_temp < target - HOLD_TOL_C:
                if abs(x - target) > HOLD_TOL_C:
                    return None  # first goes past the target without holding at it
                sp = x
            continue
        m = _ISOTHERMAL.search(st)
        if m and sp is not None:
            return sp, float(m.group(1))
    return None


def dry_reference(t: list[float], T: list[float], W: list[float], target: float,
                  steps: list[str] | None = None) -> DryReference:
    """Weight used as 100 % for the dry basis.

    Normally the weight when the temperature first reaches `target` (interpolated).
    If the method holds the sample isothermally at `target` (e.g. a drying step),
    the weight at the end of that hold is used instead.
    """
    ref = DryReference(target)
    n = len(T)
    if n == 0:
        return ref
    if T[0] >= target:
        ref.weight, ref.time = W[0], t[0]
    else:
        for i in range(1, n):
            if T[i] >= target:
                f = (target - T[i - 1]) / (T[i] - T[i - 1]) if T[i] != T[i - 1] else 0.0
                ref.weight = W[i - 1] + f * (W[i] - W[i - 1])
                ref.time = t[i - 1] + f * (t[i] - t[i - 1])
                break
    hold = programmed_hold(steps or [], target, T[0])
    if hold is None or ref.weight is None:
        return ref
    start = next(i for i in range(n) if T[i] >= target - HOLD_TOL_C)
    end = start
    while end + 1 < n and abs(T[end + 1] - target) <= HOLD_EXIT_C:
        end += 1
    # step back to where the temperature started moving again (the next ramp or cool-down)
    while end > start and abs(_rate(t, T, end)) > RESUME_RATE_C_MIN:
        end -= 1
    ref.weight, ref.time, ref.hold = W[end], t[end], True
    ref.hold_temp, ref.hold_min = hold
    return ref


def parse_temperature(text: str) -> float:
    v = float(text.replace(",", ".").strip())
    if not -100 <= v <= 1500:
        raise ValueError(f"{text} °C is out of range")
    return v


def fmt_level(x: float) -> str:
    return f"{x:g}"
