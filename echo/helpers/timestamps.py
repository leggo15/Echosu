from __future__ import annotations

from typing import List, Tuple, Dict
import math

def normalize_intervals(intervals: List[Tuple[float, float]], total_length_s: float | None = None) -> List[Tuple[float, float]]:
    """Clean and sort intervals; clip to [0, total_length_s] if provided.

    Returns merged non-overlapping list.
    """
    cleaned: List[Tuple[float, float]] = []
    for a, b in intervals or []:
        try:
            a = float(a); b = float(b)
        except Exception:
            continue
        if total_length_s is not None:
            a = max(0.0, min(a, float(total_length_s)))
            b = max(0.0, min(b, float(total_length_s)))
        if a == b:
            continue
        if a > b:
            a, b = b, a
        cleaned.append((a, b))
    if not cleaned:
        return []
    cleaned.sort()
    merged: List[Tuple[float, float]] = []
    cs, ce = cleaned[0]
    for s, e in cleaned[1:]:
        if s <= ce:
            ce = max(ce, e)
        else:
            merged.append((cs, ce))
            cs, ce = s, e
    merged.append((cs, ce))
    return merged


def consensus_intervals(user_intervals: List[List[Tuple[float, float]]], threshold_ratio: float,
                        total_length_s: float | None = None) -> List[Tuple[float, float]]:
    """Compute consensus coverage given multiple users' intervals.

    Returns segments where coverage >= threshold_ratio of users.
    """
    if not user_intervals:
        return []
    # Flatten events
    events: List[Tuple[float, int]] = []
    for intervals in user_intervals:
        for s, e in normalize_intervals(intervals, total_length_s):
            events.append((s, +1))
            events.append((e, -1))
    if not events:
        return []
    events.sort()
    num_users = len(user_intervals)
    # Use ceiling so that 50% of 5 users -> 3 (not 2). Avoid banker's rounding.
    needed = max(1, int(math.ceil(num_users * float(threshold_ratio))))
    # Product decision: when exactly two users provided intervals and the threshold is
    # 50% or lower, require both to agree to show overlap (strict intersection for 2 users).
    if num_users == 2 and threshold_ratio <= 0.5:
        needed = 2
    on = 0
    res: List[Tuple[float, float]] = []
    prev_t = events[0][0]
    active = False
    for t, delta in events:
        if t > prev_t:
            if active:
                res.append((prev_t, t))
        on += delta
        active = on >= needed
        prev_t = t
    return normalize_intervals(res, total_length_s)



