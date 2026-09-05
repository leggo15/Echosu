"""
PP Weight Index
---------------
Fits a single expected-PP curve (no buckets) from all maps in the DB.

We use a small polynomial regression in `stars` so the expected pp can be:
- Stored as a single equation (coefficients)
- Evaluated cheaply in Python (Horner)
- Reproduced in SQL using only + and * for sorting/annotation
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import math

from django.db import transaction

from ..models import Beatmap, PpWeightIndex


@dataclass
class FitResult:
    degree: int
    coefficients: list[float]  # c0..cd
    n: int
    star_min: float | None
    star_max: float | None
    rmse_pp: float | None


def _solve_linear_system(A: list[list[float]], b: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting. Returns x or None."""
    n = len(A)
    if n == 0 or any(len(row) != n for row in A) or len(b) != n:
        return None

    # Build augmented matrix
    M = [list(map(float, A[i])) + [float(b[i])] for i in range(n)]

    for col in range(n):
        # Pivot
        pivot_row = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot_row][col]) < 1e-12:
            return None
        if pivot_row != col:
            M[col], M[pivot_row] = M[pivot_row], M[col]

        # Normalize pivot row
        piv = M[col][col]
        inv = 1.0 / piv
        for j in range(col, n + 1):
            M[col][j] *= inv

        # Eliminate
        for r in range(n):
            if r == col:
                continue
            factor = M[r][col]
            if abs(factor) < 1e-18:
                continue
            for j in range(col, n + 1):
                M[r][j] -= factor * M[col][j]

    return [M[i][n] for i in range(n)]


def _eval_poly(coeffs: list[float], x: float) -> float:
    y = 0.0
    for c in reversed(coeffs):
        y = y * x + c
    return y


def fit_pp_weight_index_for_mode(mode: str, degree: int = 4) -> FitResult | None:
    """
    Fit polynomial coefficients for expected pp_nomod vs difficulty_rating for a single mode.
    Uses normal equations built from aggregated sums to avoid storing all points in memory.
    """
    mode_key = (mode or '').strip().lower()
    if not mode_key:
        return None
    d = int(degree)
    if d < 1:
        d = 1
    if d > 8:
        # Keep it small and stable; high degrees are numerically fragile.
        d = 8

    # Normal equations for polynomial regression:
    # A[i,j] = Σ x^(i+j),   b[i] = Σ y * x^i
    size = d + 1
    sum_x_pows = [0.0 for _ in range(2 * d + 1)]  # Σ x^k for k=0..2d
    sum_y_x_pows = [0.0 for _ in range(size)]     # Σ y*x^i for i=0..d

    n = 0
    star_min = None
    star_max = None

    qs = (
        Beatmap.objects
        .filter(mode__iexact=mode_key, difficulty_rating__isnull=False, pp_nomod__isnull=False)
        .values_list('difficulty_rating', 'pp_nomod')
    )
    for stars, pp in qs.iterator(chunk_size=5000):
        try:
            x = float(stars)
            y = float(pp)
        except Exception:
            continue
        if math.isnan(x) or math.isnan(y) or math.isinf(x) or math.isinf(y):
            continue
        n += 1
        if star_min is None or x < star_min:
            star_min = x
        if star_max is None or x > star_max:
            star_max = x
        # powers of x up to 2d
        x_pow = 1.0
        for k in range(0, 2 * d + 1):
            sum_x_pows[k] += x_pow
            x_pow *= x
        x_pow = 1.0
        for i in range(size):
            sum_y_x_pows[i] += y * x_pow
            x_pow *= x

    if n < max(50, size * 10):
        return None

    A = [[0.0 for _ in range(size)] for _ in range(size)]
    for i in range(size):
        for j in range(size):
            A[i][j] = sum_x_pows[i + j]
    b = list(sum_y_x_pows)

    coeffs = _solve_linear_system(A, b)
    if not coeffs:
        return None

    # Compute RMSE in pp space via another streaming pass
    sse = 0.0
    n2 = 0
    for stars, pp in qs.iterator(chunk_size=5000):
        try:
            x = float(stars)
            y = float(pp)
        except Exception:
            continue
        if math.isnan(x) or math.isnan(y) or math.isinf(x) or math.isinf(y):
            continue
        yhat = _eval_poly(coeffs, x)
        err = y - yhat
        sse += err * err
        n2 += 1
    rmse = math.sqrt(sse / n2) if n2 > 0 else None

    return FitResult(
        degree=d,
        coefficients=[float(c) for c in coeffs],
        n=n,
        star_min=star_min,
        star_max=star_max,
        rmse_pp=rmse,
    )


@transaction.atomic
def rebuild_pp_weight_index(modes: Iterable[str] | None = None, degree: int = 4) -> dict[str, FitResult | None]:
    """
    Rebuild and store PP weight index rows (replaces existing).
    Returns per-mode FitResult (or None if insufficient data).
    """
    if modes is None:
        modes = [PpWeightIndex.MODE_OSU, PpWeightIndex.MODE_TAIKO, PpWeightIndex.MODE_CATCH, PpWeightIndex.MODE_MANIA]
    out: dict[str, FitResult | None] = {}
    for mode in modes:
        m = (mode or '').strip().lower()
        fit = fit_pp_weight_index_for_mode(m, degree=degree)
        out[m] = fit
        if fit is None:
            # Leave existing row as-is if present? Requirement says replace if exists.
            # We'll replace with empty coeffs to make the state explicit.
            PpWeightIndex.objects.update_or_create(
                mode=m,
                defaults={
                    'degree': int(degree),
                    'coefficients': [],
                    'source_count': 0,
                    'star_min': None,
                    'star_max': None,
                    'rmse_pp': None,
                },
            )
            continue
        PpWeightIndex.objects.update_or_create(
            mode=m,
            defaults={
                'degree': fit.degree,
                'coefficients': fit.coefficients,
                'source_count': fit.n,
                'star_min': fit.star_min,
                'star_max': fit.star_max,
                'rmse_pp': fit.rmse_pp,
            },
        )
    return out


