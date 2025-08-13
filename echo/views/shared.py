# echosu/views/shared.py

GAME_MODE_MAPPING = {
    'GameMode.OSU': 'osu',
    'GameMode.TAIKO': 'taiko',
    'GameMode.CATCH': 'fruits',
    'GameMode.MANIA': 'mania',
}

# ---------------------------------------------------------------------------
# Tag → filter mapping helpers used by beatmap cards
# ---------------------------------------------------------------------------

# Canonical mapping from tag names to which attribute filters they suggest
TAG_FILTER_MAPPING = {
    'streams': ['bpm'],
    'speed': ['bpm'],
    'reading': ['ar'],
    'precision': ['cs'],
    'farm': ['accuracy', 'length', 'pp'],
}


def compute_attribute_windows(beatmap):
    """Compute default min/max windows around a beatmap's attributes.

    Returns a dict like {
      'star_min': ..., 'star_max': ...,
      'bpm_min': ...,  'bpm_max':  ...,
      'ar_min': ...,   'ar_max':   ...,
      'drain_min': ...,'drain_max':...,
      'cs_min': ...,   'cs_max':   ...,
      'accuracy_min': ...,'accuracy_max': ...,
      'length_min': ..., 'length_max': ...,
    }
    """
    # Star rating window (always present; fall back to sensible defaults)
    current_star = getattr(beatmap, 'difficulty_rating', None)
    if current_star is None:
        star_min = 0.0
        star_max = 10.0
    else:
        star_min = max(0.0, current_star - (current_star * 0.09))
        star_max = min(15.0, current_star + (current_star * 0.09))
        if star_min < 0.4:
            star_min = 0.4
            star_max = 0.4

    # BPM window
    current_bpm = getattr(beatmap, 'bpm', None)
    if current_bpm is None:
        bpm_min = None
        bpm_max = None
    else:
        bpm_min = max(0.0, current_bpm - 10.0)
        bpm_max = max(0.0, current_bpm + 10.0)

    # AR window (bounded to 0..10)
    ar_value = getattr(beatmap, 'ar', None)
    if ar_value is None:
        ar_min = None
        ar_max = None
    else:
        ar_delta = (1 - (ar_value - 1) * (1 - 0.3) / (10 - 1))
        ar_min = max(0.0, ar_value - ar_delta)
        ar_max = min(10.0, ar_value + ar_delta)

    # HP/Drain window (bounded to 0..10)
    drain_value = getattr(beatmap, 'drain', None)
    if drain_value is None:
        drain_min = None
        drain_max = None
    else:
        drain_min = max(0.0, drain_value - 0.8)
        drain_max = min(10.0, drain_value + 0.8)

    # CS window (bounded to 0..10)
    cs_value = getattr(beatmap, 'cs', None)
    if cs_value is None:
        cs_min = None
        cs_max = None
    else:
        cs_min = max(0.0, cs_value - (cs_value * 0.09))
        cs_max = min(10.0, cs_value + (cs_value * 0.09))

    # Accuracy/OD window (bounded to 0..10)
    acc_value = getattr(beatmap, 'accuracy', None)
    if acc_value is None:
        accuracy_min = None
        accuracy_max = None
    else:
        acc_delta = (1 - (acc_value - 1) * (1 - 0.4) / (10 - 1))
        accuracy_min = max(0.0, acc_value - acc_delta)
        accuracy_max = min(10.0, acc_value + acc_delta)

    # Length window (seconds)
    total_length_value = getattr(beatmap, 'total_length', None)
    if total_length_value is None:
        length_min = None
        length_max = None
    else:
        length_min = int(max(0, total_length_value - (total_length_value * 0.3)))
        length_max = int(max(0, total_length_value + (total_length_value * 0.3)))

    # PP window (prefer stored DB fields; fall back gracefully)
    pp_value = getattr(beatmap, 'pp', None)
    if pp_value is None:
        # Prefer pp_nomod if present, otherwise use the max across modded fields
        pp_nomod = getattr(beatmap, 'pp_nomod', None)
        if pp_nomod is not None:
            pp_value = float(pp_nomod)
        else:
            modded_vals = [
                getattr(beatmap, 'pp_hd', None), getattr(beatmap, 'pp_hr', None),
                getattr(beatmap, 'pp_dt', None), getattr(beatmap, 'pp_ht', None),
                getattr(beatmap, 'pp_ez', None), getattr(beatmap, 'pp_fl', None),
            ]
            modded_vals = [float(v) for v in modded_vals if v is not None]
            pp_value = max(modded_vals) if modded_vals else None

    if pp_value is None:
        pp_min = None
        pp_max = None
    else:
        pp_min = max(0.0, pp_value - (pp_value * 0.15))
        pp_max = max(0.0, pp_value + (pp_value * 0.15))

    return {
        'star_min': star_min, 'star_max': star_max,
        'bpm_min': bpm_min, 'bpm_max': bpm_max,
        'ar_min': ar_min, 'ar_max': ar_max,
        'drain_min': drain_min, 'drain_max': drain_max,
        'cs_min': cs_min, 'cs_max': cs_max,
        'accuracy_min': accuracy_min, 'accuracy_max': accuracy_max,
        'length_min': length_min, 'length_max': length_max,
        'pp_min': pp_min, 'pp_max': pp_max,
    }


def derive_filters_from_tags(tag_names):
    """Given a list of tag names, return a unique set of attribute filter keys.

    For example: ['streams', 'aim'] -> {'bpm', 'ar', 'cs'}
    """
    suggested = set()
    for name in tag_names or []:
        key = (name or '').strip().lower()
        for attr in TAG_FILTER_MAPPING.get(key, []):
            suggested.add(attr)
    return suggested


def build_similar_maps_query(filters_to_apply, windows, tags_query_string):
    """Build the search URL parameters string for the Find Similar Maps link.

    filters_to_apply: iterable like {'bpm','ar','cs'}
    windows: dict from compute_attribute_windows
    tags_query_string: string of tags to include in the 'query=' parameter

    Returns a tuple (query_param, extra_params_dict)
    where query_param is a string suitable for 'query=' and extra_params_dict
    contains additional GET params such as star_min/star_max.
    """
    parts = []
    # Always include tags if present
    if tags_query_string:
        parts.append(tags_query_string)

    # Comparison fragments use the syntax parsed by handle_attribute_queries
    def _has_numbers(*keys):
        for k in keys:
            v = windows.get(k)
            if v is None:
                return False
        return True

    if 'bpm' in filters_to_apply and _has_numbers('bpm_min', 'bpm_max'):
        parts.append(f"BPM>={int(windows['bpm_min'])}")
        parts.append(f"BPM<={int(windows['bpm_max'])}")
    if 'ar' in filters_to_apply and _has_numbers('ar_min', 'ar_max'):
        parts.append(f"AR>={windows['ar_min']:.1f}")
        parts.append(f"AR<={windows['ar_max']:.1f}")
    if 'cs' in filters_to_apply and _has_numbers('cs_min', 'cs_max'):
        parts.append(f"CS>={windows['cs_min']:.1f}")
        parts.append(f"CS<={windows['cs_max']:.1f}")
    if 'drain' in filters_to_apply and _has_numbers('drain_min', 'drain_max'):
        parts.append(f"HP>={windows['drain_min']:.1f}")
        parts.append(f"HP<={windows['drain_max']:.1f}")
    if 'accuracy' in filters_to_apply and _has_numbers('accuracy_min', 'accuracy_max'):
        parts.append(f"OD>={windows['accuracy_min']:.1f}")
        parts.append(f"OD<={windows['accuracy_max']:.1f}")
    if 'length' in filters_to_apply and _has_numbers('length_min', 'length_max'):
        parts.append(f"LENGTH>={int(windows['length_min'])}")
        parts.append(f"LENGTH<={int(windows['length_max'])}")
    if 'pp' in filters_to_apply and _has_numbers('pp_min', 'pp_max'):
        parts.append(f"PP>={windows['pp_min']:.1f}")
        parts.append(f"PP<={windows['pp_max']:.1f}")

    query = ' '.join(parts).strip()

    # Always carry star window as explicit params for slider defaults
    extra = {
        'star_min': f"{float(windows.get('star_min', 0.0)):.2f}",
        'star_max': f"{float(windows.get('star_max', 10.0)):.2f}",
    }
    return query, extra


def format_length_hms(total_seconds):
    """Format seconds into H:MM:SS (S) string.

    Returns '-' if value is missing/invalid.
    """
    try:
        t = int(total_seconds or 0)
    except Exception:
        return '-'
    hours = t // 3600
    minutes = (t % 3600) // 60
    seconds = t % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d} ({t})"
    return f"{minutes}:{seconds:02d} ({t})"
