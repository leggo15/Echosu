"""Utilities for computing and caching osu! difficulty time-series using rosu-pp.

This module downloads .osu files to the configured default storage (S3 in prod),
parses them with rosu_pp_py, computes binned mean strains for aim and speed, and
persists the resulting time-series as JSON files in S3 rather than the database.
"""

from __future__ import annotations

import math
import json
import tempfile
from typing import Dict, List, Optional

import requests
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

try:
    import rosu_pp_py as rosu
except Exception:  # pragma: no cover - handled gracefully in callers
    rosu = None  # type: ignore


OSU_DOWNLOAD_URL_TMPL = "https://osu.ppy.sh/osu/{beatmap_id}"
STORAGE_OSU_DIR = "beatmaps/osu_files"
STORAGE_TS_DIR = "beatmaps/timeseries"


def _storage_key_for_osu(beatmap_id: str | int) -> str:
    return f"{STORAGE_OSU_DIR}/{beatmap_id}.osu"


def _timeseries_storage_key(beatmap_id: str | int, window_seconds: int, mods: Optional[str]) -> str:
    mods_token = (mods or "").strip().upper() or "NOMOD"
    return f"{STORAGE_TS_DIR}/{beatmap_id}/w{int(window_seconds)}_{mods_token}.json"


def ensure_osu_file_available(beatmap_id: str | int) -> Optional[str]:
    """Ensure the .osu file exists in default storage; return storage name.

    Returns None on failure.
    """
    name = _storage_key_for_osu(beatmap_id)
    try:
        if not default_storage.exists(name):
            url = OSU_DOWNLOAD_URL_TMPL.format(beatmap_id=beatmap_id)
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200 or not resp.content:
                return None
            default_storage.save(name, ContentFile(resp.content))
        return name
    except Exception:
        return None


def _bin_mean(values: List[float], bin_size: int) -> List[float]:
    if bin_size <= 0:
        return []
    n_full = (len(values) // bin_size) * bin_size
    means: List[float] = []
    for i in range(0, n_full, bin_size):
        window = values[i : i + bin_size]
        means.append(sum(window) / float(bin_size))
    return means


def _first_last_hitobject_ms_from_osu(osu_bytes: bytes) -> tuple[float, float]:
    """Parse raw .osu to get earliest and latest HitObject times in ms.

    Returns (0.0, 0.0) on failure.
    """
    first_ms: Optional[float] = None
    last_ms: Optional[float] = None
    try:
        text = osu_bytes.decode('utf-8', errors='ignore')
        lines = text.splitlines()
        in_hit = False
        for line in lines:
            s = line.strip()
            if not s:
                continue
            if s.startswith('[') and s.endswith(']'):
                in_hit = (s.lower() == '[hitobjects]')
                continue
            if not in_hit:
                continue
            parts = s.split(',')
            if len(parts) >= 3:
                try:
                    t = float(parts[2])
                    if first_ms is None or t < first_ms:
                        first_ms = t
                    if last_ms is None or t > last_ms:
                        last_ms = t
                except Exception:
                    pass
    except Exception:
        return 0.0, 0.0
    return float(first_ms or 0.0), float(last_ms or 0.0)


def compute_timeseries_from_osu_bytes(
    osu_bytes: bytes,
    window_seconds: int = 5,
    mods: Optional[str] = None,
) -> Optional[Dict]:
    """Compute 10-second mean strains (aim, speed, total) using rosu.

    Returns a JSON-serialisable dict or None on failure.
    """
    if rosu is None:
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=".osu", delete=True) as tmp:
            tmp.write(osu_bytes)
            tmp.flush()

            bm = rosu.Beatmap(path=tmp.name)

            # Apply mods if provided (string acronyms like "DT", "HR", "EZ", "HT", "FL")
            # This affects strain computation (AR/CS/OD/HP, speed mods, etc.).
            try:
                diff = rosu.Difficulty(mods=mods) if mods else rosu.Difficulty()
            except Exception:
                diff = rosu.Difficulty()
            # Compute modded star rating for proper Y scaling on the frontend
            try:
                diff_attrs = diff.calculate(bm)
                stars_val = float(getattr(diff_attrs, "stars", 0.0) or 0.0)
            except Exception:
                stars_val = 0.0
            strains = diff.strains(bm)

            section_ms: float = float(strains.section_length)
            # Determine how many strain sections fit into the requested window
            # and compute the effective window size in seconds based on the
            # integer bin size actually used.
            bin_size_float = (window_seconds * 1000.0) / section_ms
            bin_size = max(1, int(round(bin_size_float)))
            if bin_size <= 0:
                return None

            aim = list(map(float, list(strains.aim)))
            speed = list(map(float, list(strains.speed)))

            aim_binned = _bin_mean(aim, bin_size)
            speed_binned = _bin_mean(speed, bin_size)
            # Align length
            n = min(len(aim_binned), len(speed_binned))
            aim_binned = aim_binned[:n]
            speed_binned = speed_binned[:n]
            total_binned_all = [a + s for a, s in zip(aim_binned, speed_binned)]

            # Center time of each window (relative timeline from first object)
            effective_window_s = (bin_size * section_ms) / 1000.0


            mods_up = (mods or "").upper()
            clock_rate = 1.0
            times_rel = [((i + 0.5) * effective_window_s) / clock_rate for i in range(n)]

            # Determine first/last hitobject times to trim/stretch accurately
            t0_ms, t_last_ms = _first_last_hitobject_ms_from_osu(osu_bytes)
            # Determine clock rate from speed mods for correct time scaling on the X axis
            mods_up = (mods or "").upper()
            clock_rate = 1.0
            if "DT" in mods_up:
                clock_rate = 1.5
            elif "HT" in mods_up:
                clock_rate = 0.75
            # Convert hitobject times to seconds under the applied clock rate
            t0_s = (t0_ms / 1000.0) / clock_rate if t0_ms else 0.0
            t_end_s = (t_last_ms / 1000.0) / clock_rate if t_last_ms else 0.0
            tmax_rel_s = max(0.0, t_end_s - t0_s)

            # Clip bins to slightly beyond last object by half-window to avoid overshoot
            keep_idx = [i for i, t in enumerate(times_rel) if t <= (tmax_rel_s + (effective_window_s * 0.5))]
            if keep_idx:
                times_s = [times_rel[i] for i in keep_idx]
                aim_binned = [aim_binned[i] for i in keep_idx]
                speed_binned = [speed_binned[i] for i in keep_idx]
                total_binned = [total_binned_all[i] for i in keep_idx]
            else:
                times_s = times_rel
                total_binned = total_binned_all

            return {
                "version": 3,
                "window_s": window_seconds,
                "section_ms": section_ms,
                "t0_s": t0_s,
                "t_end_s": t_end_s,
                "times_s": times_s,
                "aim": aim_binned,
                "speed": speed_binned,
                "total": total_binned,
                "effective_window_s": effective_window_s,
                # Expose clock rate so the frontend can align tag overlays with the modded timeline
                "clock_rate": clock_rate,
                # Provide modded star rating so the frontend can scale Y correctly
                "stars": stars_val,
            }
    except Exception:
        return None


def get_or_compute_timeseries(
    beatmap,
    window_seconds: int = 5,
    mods: Optional[str] = None,
) -> Optional[Dict]:
    """Fetch or compute the timeseries for a Beatmap instance.

    Persistence strategy:
      - Prefer reading from S3 (default_storage) at a deterministic path
      - If missing, compute from the .osu file and write JSON to S3
      - For legacy installs, if a DB-cached nomod timeseries exists, return it
        and opportunistically upload it to S3 for future requests
    """
    # Only compute for osu! standard for now
    if getattr(beatmap, "mode", None) and str(beatmap.mode).lower() not in ("osu", "standard", "std", "0"):
        return None

    # Prefer S3-cached JSON
    key = _timeseries_storage_key(beatmap.beatmap_id, window_seconds, mods)
    try:
        if default_storage.exists(key):
            with default_storage.open(key, "rb") as fh:
                data = fh.read()
                try:
                    return json.loads(data.decode("utf-8"))
                except Exception:
                    # Corrupt JSON → fall through to recompute
                    pass
    except Exception:
        # Storage access failure → fall through to legacy/compute paths
        pass

    # Legacy fallback: use DB field if present for nomod and seed S3
    if mods in (None, ""):
        legacy = getattr(beatmap, "rosu_timeseries", None)
        if isinstance(legacy, dict):
            try:
                if (
                    "times_s" in legacy
                    and "total" in legacy
                    and int(legacy.get("window_s") or 0) == int(window_seconds)
                    and int(legacy.get("version") or 0) >= 3
                ):
                    try:
                        default_storage.save(key, ContentFile(json.dumps(legacy).encode("utf-8")))
                    except Exception:
                        pass
                    return legacy
            except Exception:
                pass

    storage_name = ensure_osu_file_available(beatmap.beatmap_id)
    if not storage_name:
        return None

    try:
        with default_storage.open(storage_name, "rb") as fh:
            osu_bytes = fh.read()
    except Exception:
        return None

    ts = compute_timeseries_from_osu_bytes(
        osu_bytes,
        window_seconds=window_seconds,
        mods=mods,
    )
    if ts is None:
        return None

    # Persist JSON to S3 for all variants (nomod and modded)
    try:
        try:
            # Ensure stable key without versioned suffixes when FILE_OVERWRITE=False
            default_storage.delete(key)
        except Exception:
            pass
        payload = json.dumps(ts, separators=(",", ":")).encode("utf-8")
        default_storage.save(key, ContentFile(payload))
    except Exception:
        # Best-effort persistence; still return the computed value
        pass
    return ts




def get_or_compute_pp(beatmap, accuracy: float = 100.0, misses: int = 0, lazer: bool = True) -> Optional[float]:
    """Return cached PP if present; otherwise compute with rosu-pp and cache.

    Returns None if rosu is unavailable or computation fails.
    """
    if rosu is None:
        return None

    # Use cached value if available
    cached_pp = getattr(beatmap, 'pp', None)
    try:
        if cached_pp is not None:
            return float(cached_pp)
    except Exception:
        pass

    storage_name = ensure_osu_file_available(beatmap.beatmap_id)
    if not storage_name:
        return None

    try:
        with default_storage.open(storage_name, "rb") as fh:
            osu_bytes = fh.read()

        with tempfile.NamedTemporaryFile(suffix=".osu", delete=True) as tmp:
            tmp.write(osu_bytes)
            tmp.flush()

            bm = rosu.Beatmap(path=tmp.name)
            perf = rosu.Performance(accuracy=accuracy, misses=misses, lazer=lazer)
            attrs = perf.calculate(bm)
            pp_value = getattr(attrs, "pp", None)
            if pp_value is None:
                return None
            try:
                beatmap.pp = float(pp_value)
                beatmap.save(update_fields=["pp"])
            except Exception:
                # Silent failure to avoid impacting request path
                pass
            return float(pp_value)
    except Exception:
        return None


def get_or_compute_modded_pps(
    beatmap,
    accuracy: float = 100.0,
    misses: int = 0,
    lazer: bool = True,
) -> Optional[dict]:
    """Compute and cache PP for common single-mod variants.

    Populates the following fields on the Beatmap model (osu!std only):
      - pp_nomod, pp_hd, pp_hr, pp_dt, pp_ht, pp_ez, pp_fl

    Returns a dict of computed values or None on failure.
    """
    if rosu is None:
        return None

    # Only compute for osu! standard for now
    if getattr(beatmap, "mode", None) and str(beatmap.mode).lower() not in ("osu", "standard", "std", "0"):
        return None

    storage_name = ensure_osu_file_available(beatmap.beatmap_id)
    if not storage_name:
        return None

    try:
        with default_storage.open(storage_name, "rb") as fh:
            osu_bytes = fh.read()

        with tempfile.NamedTemporaryFile(suffix=".osu", delete=True) as tmp:
            tmp.write(osu_bytes)
            tmp.flush()

            bm = rosu.Beatmap(path=tmp.name)

            def _calc(mods=None):
                perf = rosu.Performance(accuracy=accuracy, misses=misses, lazer=lazer, mods=mods)
                attrs = perf.calculate(bm)
                return float(getattr(attrs, "pp", 0.0) or 0.0)

            # Use string acronyms per rosu-pp-py GameMods type
            results = {
                "pp_nomod": _calc(None),
                "pp_hd": _calc("HD"),
                "pp_hr": _calc("HR"),
                "pp_dt": _calc("DT"),
                "pp_ht": _calc("HT"),
                "pp_ez": _calc("EZ"),
                "pp_fl": _calc("FL"),
            }

            # Persist on model
            try:
                for field, value in results.items():
                    setattr(beatmap, field, value)
                beatmap.save(update_fields=list(results.keys()))
            except Exception:
                pass

            return results
    except Exception:
        return None
