from __future__ import annotations

"""
Tag-map (stock-market heatmap) backend helpers.

This module contains the heavy logic that powers the Statistics "Mapper Similarity Map" tab.
The Django view (`statistics_tag_map_data`) should remain a thin wrapper.
"""

from dataclasses import dataclass
from collections import Counter, defaultdict
import math
import re

from django.db.models import Count

from ..models import Beatmap, Tag, TagApplication


@dataclass(frozen=True)
class TagMapParams:
    mode: str
    status_filter: str  # ranked|unranked|all
    view: str  # tagsets|single|overlap
    custom_tagset_raw: str
    consolidation: float
    max_tags: int
    max_mappers: int


class _UnionFind:
    def __init__(self, items):
        self.parent = {i: i for i in items}
        self.rank = {i: 0 for i in items}

    def find(self, x):
        p = self.parent.get(x, x)
        if p != x:
            self.parent[x] = self.find(p)
        return self.parent.get(x, x)

    def union(self, a, b):
        ra = self.find(a)
        rb = self.find(b)
        if ra == rb:
            return
        rka = self.rank.get(ra, 0)
        rkb = self.rank.get(rb, 0)
        if rka < rkb:
            self.parent[ra] = rb
        elif rka > rkb:
            self.parent[rb] = ra
        else:
            self.parent[rb] = ra
            self.rank[ra] = rka + 1


def parse_tagmap_params(request) -> TagMapParams:
    mode = Tag.normalize_mode((request.GET.get('mode') or Tag.MODE_STD).strip())

    status_filter = (request.GET.get('status_filter') or 'ranked').strip().lower()
    if status_filter not in ['ranked', 'unranked', 'all']:
        status_filter = 'ranked'

    view = (request.GET.get('view') or 'tagsets').strip().lower()
    if view not in ['tagsets', 'single', 'overlap']:
        view = 'tagsets'

    custom_tagset_raw = (request.GET.get('custom_tagset') or '').strip()

    # Consolidation is a server-side constant now (kept in params for tuning / future use).
    consolidation = 0.1

    try:
        max_tags = int((request.GET.get('max_tags') or '150').strip())
    except Exception:
        max_tags = 150
    max_tags = max(20, min(400, max_tags))

    try:
        max_mappers = int((request.GET.get('max_mappers') or '60').strip())
    except Exception:
        max_mappers = 60
    max_mappers = max(10, min(200, max_mappers))

    return TagMapParams(
        mode=mode,
        status_filter=status_filter,
        view=view,
        custom_tagset_raw=custom_tagset_raw,
        consolidation=consolidation,
        max_tags=max_tags,
        max_mappers=max_mappers,
    )


def _apply_status_filter(ta, status_filter: str):
    """Mirror search.py's status buckets."""
    if status_filter == 'ranked':
        return ta.filter(beatmap__status__in=['Ranked', 'Approved'])
    if status_filter == 'unranked':
        return ta.filter(beatmap__status__in=['Graveyard', 'WIP', 'Pending', 'Qualified', 'Loved'])
    return ta


def build_base_tagapplication_qs(mode: str, status_filter: str):
    ta = (
        TagApplication.objects
        .filter(true_negative=False, tag__mode=mode)
        .exclude(user__isnull=True, is_prediction=False)
    )
    return _apply_status_filter(ta, status_filter)


def _tokenize_custom_tagset(raw: str) -> tuple[list[str], list[str]]:
    include_names: list[str] = []
    exclude_names: list[str] = []
    if not raw:
        return include_names, exclude_names
    pattern = r'[-.]?"[^"]+"|[-.]?[^"\s]+'
    for match in re.findall(pattern, raw):
        token = (match or '').strip()
        if not token:
            continue
        prefix = ''
        if token[0] in '.-':
            prefix = token[0]
            token = token[1:]
        token = token.strip().strip('"').strip("'").strip().lower()
        if not token:
            continue
        if prefix == '-':
            exclude_names.append(token)
        else:
            include_names.append(token)
    return [t for t in include_names if t], [t for t in exclude_names if t]


def _mapper_by_beatmap_ids(bm_ids: list[int]) -> dict[int, str]:
    mapper_by_bm: dict[int, str] = {}
    for row in Beatmap.objects.filter(id__in=bm_ids).values('id', 'listed_owner', 'creator'):
        bm_pk = int(row.get('id'))
        mapper = (row.get('listed_owner') or row.get('creator') or '').strip()
        mapper_by_bm[bm_pk] = mapper or '(unknown)'
    return mapper_by_bm


def _payload_from_bm_ids(tags_out: list[str], bm_ids: list[int], mapper_by_bm: dict[int, str], max_mappers: int) -> dict:
    m_ctr: Counter[str] = Counter()
    for bid in bm_ids:
        m = mapper_by_bm.get(int(bid))
        if m:
            m_ctr[m] += 1
    return {
        'sets': [{
            'id': 0,
            'tags': tags_out,
            'map_count': int(len(bm_ids)),
            'top_mappers': [{'name': n, 'count': int(c)} for n, c in m_ctr.most_common(max_mappers)],
        }]
    }


def _custom_tagset_payload(ta, mode: str, raw: str, max_mappers: int) -> dict | None:
    include_names, exclude_names = _tokenize_custom_tagset(raw)
    if not include_names:
        return None

    include_tags = list(Tag.objects.filter(mode=mode, name__in=include_names).values_list('id', flat=True))
    exclude_tags = list(Tag.objects.filter(mode=mode, name__in=exclude_names).values_list('id', flat=True))
    if not include_tags:
        return None

    bm_sets: list[set[int]] = []
    for tid in include_tags:
        ids = set(ta.filter(tag_id=int(tid)).values_list('beatmap_id', flat=True).distinct())
        if not ids:
            return None
        bm_sets.append(ids)

    bm_sets.sort(key=lambda s: len(s))
    inter = set(bm_sets[0])
    for s in bm_sets[1:]:
        inter.intersection_update(s)

    if inter and exclude_tags:
        ex_union: set[int] = set()
        for tid in exclude_tags:
            ex_union.update(set(ta.filter(tag_id=int(tid)).values_list('beatmap_id', flat=True).distinct()))
        if ex_union:
            inter.difference_update(ex_union)

    bm_ids = list(inter)
    if not bm_ids:
        return None

    mapper_by_bm = _mapper_by_beatmap_ids(bm_ids)
    return _payload_from_bm_ids(include_names[:], bm_ids, mapper_by_bm, max_mappers)


def _build_candidate_tags(ta, max_tags: int, consolidation: float) -> tuple[list[int], dict[int, int]]:
    min_support = max(2, int(round(3 + 12 * (1.0 - consolidation))))  # 3..15
    support_rows = list(
        ta.values('tag_id')
        .annotate(cnt=Count('beatmap_id', distinct=True))
        .order_by('-cnt')[: max_tags * 3]
    )
    picked = [(int(r['tag_id']), int(r['cnt'])) for r in support_rows if int(r.get('cnt') or 0) >= min_support]
    if len(picked) < min(25, max_tags):
        picked = [(int(r['tag_id']), int(r['cnt'])) for r in support_rows[:max_tags]]
    picked = picked[:max_tags]
    tag_support: dict[int, int] = {tid: cnt for tid, cnt in picked}
    tag_ids: list[int] = list(tag_support.keys())
    return tag_ids, tag_support


def _build_bm_tags(ta, tag_ids: list[int]) -> dict[int, list[int]]:
    bm_tags: dict[int, list[int]] = defaultdict(list)
    for bm_id, tag_id in (
        ta.filter(tag_id__in=tag_ids)
        .values_list('beatmap_id', 'tag_id')
        .distinct()
        .iterator(chunk_size=5000)
    ):
        try:
            bm_tags[int(bm_id)].append(int(tag_id))
        except Exception:
            continue
    return bm_tags


def _compute_pair_counts(bm_tags: dict[int, list[int]]) -> Counter[tuple[int, int]]:
    pair_counts: Counter[tuple[int, int]] = Counter()
    for tags in bm_tags.values():
        if not tags or len(tags) < 2:
            continue
        uniq = sorted(set(tags))
        if len(uniq) < 2:
            continue
        for i in range(len(uniq)):
            a = uniq[i]
            for j in range(i + 1, len(uniq)):
                b = uniq[j]
                pair_counts[(a, b)] += 1
    return pair_counts


def _npmi_neighbors(
    pair_counts: Counter[tuple[int, int]],
    tag_support: dict[int, int],
    total_maps: int,
    consolidation: float,
) -> tuple[dict[int, list[tuple[int, float, int]]], float, int]:
    # Thresholds
    edge_threshold = max(0.05, 0.35 - (0.30 * consolidation))
    min_pair = max(2, int(round(2 + 8 * (1.0 - consolidation))))  # 2..10
    k = max(3, min(24, int(round(4 + 14 * consolidation))))

    eps = 1e-12
    neigh: dict[int, list[tuple[int, float, int]]] = defaultdict(list)
    for (a, b), c in pair_counts.items():
        if c < min_pair:
            continue
        ca = tag_support.get(a) or 0
        cb = tag_support.get(b) or 0
        if not ca or not cb:
            continue
        pab = float(c) / float(total_maps)
        if pab <= 0.0:
            continue
        pa = float(ca) / float(total_maps)
        pb = float(cb) / float(total_maps)
        try:
            pmi = math.log((pab + eps) / ((pa * pb) + eps))
            denom = -math.log(pab + eps)
            npmi = float(pmi / denom) if denom > 0 else 0.0
        except Exception:
            continue
        if npmi < edge_threshold:
            continue
        neigh[int(a)].append((int(b), npmi, int(c)))
        neigh[int(b)].append((int(a), npmi, int(c)))

    top: dict[int, list[tuple[int, float, int]]] = {}
    for t, lst in neigh.items():
        lst.sort(key=lambda x: (x[1], x[2]), reverse=True)
        top[t] = lst[:k]
    return top, edge_threshold, min_pair


def _mutual_knn_components(tag_ids: list[int], top: dict[int, list[tuple[int, float, int]]]) -> list[list[int]]:
    top_set: dict[int, set[int]] = {t: {o for (o, _, _) in lst} for t, lst in top.items()}
    uf = _UnionFind(tag_ids)
    for a, lst in top.items():
        aset = top_set.get(a) or set()
        for b, _, _ in lst:
            if b in aset and a in (top_set.get(b) or set()):
                uf.union(a, b)
    comps: dict[int, list[int]] = defaultdict(list)
    for tid in tag_ids:
        comps[int(uf.find(tid))].append(int(tid))
    return list(comps.values())


def build_tagmap_payload(request) -> dict:
    p = parse_tagmap_params(request)
    ta = build_base_tagapplication_qs(p.mode, p.status_filter)
    total_maps = ta.values('beatmap_id').distinct().count()
    if not total_maps:
        return {'sets': []}

    # Custom tagset overrides all other views (single sector)
    if p.custom_tagset_raw:
        payload = _custom_tagset_payload(ta, p.mode, p.custom_tagset_raw, p.max_mappers)
        if payload:
            return payload
        return {'sets': []}

    tag_ids, tag_support = _build_candidate_tags(ta, p.max_tags, p.consolidation)
    if not tag_ids:
        return {'sets': []}

    tag_name_map: dict[int, str] = {
        int(t['id']): str(t['name'])
        for t in Tag.objects.filter(id__in=tag_ids).values('id', 'name')
    }

    bm_tags = _build_bm_tags(ta, tag_ids)
    if not bm_tags:
        return {'sets': []}

    # View: single tag (overlapping)
    if p.view == 'single':
        bm_ids_all = list(bm_tags.keys())
        mapper_by_bm = _mapper_by_beatmap_ids(bm_ids_all)
        tag_map_counts: Counter[int] = Counter()
        mapper_counts_by_tag: dict[int, Counter[str]] = defaultdict(Counter)
        for bm_id, tags in bm_tags.items():
            mapper = mapper_by_bm.get(int(bm_id)) or '(unknown)'
            for tid in set(tags or []):
                tag_map_counts[int(tid)] += 1
                mapper_counts_by_tag[int(tid)][mapper] += 1

        sets = []
        next_id = 0
        max_sets_single = max(6, min(120, int(round(18 + 90 * (1.0 - p.consolidation)))))
        for tid, cnt in tag_map_counts.most_common():
            name = tag_name_map.get(int(tid))
            if not name:
                continue
            m_ctr = mapper_counts_by_tag.get(int(tid)) or Counter()
            sets.append({
                'id': next_id,
                'tags': [name],
                'map_count': int(cnt),
                'top_mappers': [{'name': n, 'count': int(c)} for n, c in m_ctr.most_common(p.max_mappers)],
            })
            next_id += 1
            if len(sets) >= max_sets_single:
                break
        return {'sets': sets}

    # Shared graph material
    pair_counts = _compute_pair_counts(bm_tags)
    top, _, _ = _npmi_neighbors(pair_counts, tag_support, total_maps, p.consolidation)

    # View: overlap (overlapping tagsets by intersection)
    if p.view == 'overlap':
        tag_to_bm: dict[int, set[int]] = {int(t): set() for t in tag_ids}
        for bm_id, tags in bm_tags.items():
            for tid in set(tags or []):
                if tid in tag_to_bm:
                    tag_to_bm[tid].add(int(bm_id))

        bm_ids_all = list(bm_tags.keys())
        mapper_by_bm = _mapper_by_beatmap_ids(bm_ids_all)

        components = sorted(
            _mutual_knn_components(tag_ids, top),
            key=lambda comp: sum(int(tag_support.get(t) or 0) for t in comp),
            reverse=True,
        )

        max_macro = max(6, min(30, int(round(10 + 12 * p.consolidation))))
        max_pairs = max(40, min(220, int(round(90 + 80 * (1.0 - p.consolidation)))))
        macro_size = max(3, min(6, int(round(4 + 2 * p.consolidation))))

        tagsets: list[list[int]] = []
        seen: set[tuple[int, ...]] = set()

        # Macro cores (seed + strongest neighbors)
        for comp in components[: max_macro * 2]:
            comp_sorted = sorted(comp, key=lambda t: int(tag_support.get(int(t)) or 0), reverse=True)
            if not comp_sorted:
                continue
            seed = int(comp_sorted[0])
            core = [seed]
            for o, _, _ in (top.get(seed) or []):
                if o in comp and o not in core:
                    core.append(int(o))
                if len(core) >= macro_size:
                    break
            sig = tuple(sorted(set(core)))
            if len(sig) < 2 or sig in seen:
                continue
            seen.add(sig)
            tagsets.append(list(sig))
            if len(tagsets) >= max_macro:
                break

        # Pairs: sort edges by (npmi, cooc)
        pair_edges: list[tuple[float, int, int, int]] = []
        for a, lst in top.items():
            for b, npmi, cooc in lst:
                if a == b:
                    continue
                x, y = (a, b) if a < b else (b, a)
                pair_edges.append((float(npmi), int(cooc), int(x), int(y)))
        pair_edges.sort(reverse=True)

        min_pair = max(2, int(round(2 + 8 * (1.0 - p.consolidation))))
        for _, _, x, y in pair_edges:
            sig2 = (x, y)
            if sig2 in seen:
                continue
            bm_x = tag_to_bm.get(x) or set()
            bm_y = tag_to_bm.get(y) or set()
            if not bm_x or not bm_y:
                continue
            if len(bm_x) > len(bm_y):
                bm_x, bm_y = bm_y, bm_x
            inter = [bid for bid in bm_x if bid in bm_y]
            if len(inter) < min_pair:
                continue
            seen.add(sig2)
            tagsets.append([x, y])
            if len(tagsets) >= (max_macro + max_pairs):
                break

        sets = []
        next_id = 0
        for ts in tagsets:
            bm_sets = [tag_to_bm.get(int(t)) or set() for t in ts]
            if any(not s for s in bm_sets):
                continue
            bm_sets.sort(key=lambda s: len(s))
            base = bm_sets[0]
            inter_ids = [bid for bid in base if all(bid in s for s in bm_sets[1:])]
            if not inter_ids:
                continue
            m_ctr: Counter[str] = Counter()
            for bid in inter_ids:
                m = mapper_by_bm.get(int(bid))
                if m:
                    m_ctr[m] += 1
            tags_out = [tag_name_map.get(int(t)) for t in ts]
            tags_out = [t for t in tags_out if t]
            if not tags_out:
                continue
            sets.append({
                'id': next_id,
                'tags': tags_out,
                'map_count': int(len(inter_ids)),
                'top_mappers': [{'name': n, 'count': int(c)} for n, c in m_ctr.most_common(p.max_mappers)],
            })
            next_id += 1

        sets.sort(key=lambda s: int(s.get('map_count') or 0), reverse=True)
        return {'sets': sets}

    # Default view: tagsets (disjoint)
    CONS_STRICT_EPS = 0.01
    CONS_MEGA_EPS = 0.99
    if p.consolidation <= CONS_STRICT_EPS:
        components = [[int(t)] for t in tag_ids]
    elif p.consolidation >= CONS_MEGA_EPS:
        components = [list(tag_ids)]
    else:
        components = sorted(
            _mutual_knn_components(tag_ids, top),
            key=lambda comp: sum(int(tag_support.get(t) or 0) for t in comp),
            reverse=True,
        )

    max_sets = max(6, min(80, int(round(12 + 48 * (1.0 - p.consolidation)))))
    components = components[: max_sets * 3]

    inv_log_support: dict[int, float] = {}
    for tid, cnt in tag_support.items():
        try:
            inv_log_support[int(tid)] = 1.0 / max(1e-6, math.log(2.0 + float(cnt)))
        except Exception:
            inv_log_support[int(tid)] = 1.0

    comp_by_tag: dict[int, int] = {}
    for idx, comp in enumerate(components):
        for tid in comp:
            comp_by_tag[int(tid)] = idx

    comp_bm_ids: dict[int, list[int]] = defaultdict(list)
    for bm_id, tags in bm_tags.items():
        scores: dict[int, float] = defaultdict(float)
        for tid in set(tags or []):
            ci = comp_by_tag.get(int(tid))
            if ci is None:
                continue
            scores[int(ci)] += float(inv_log_support.get(int(tid), 1.0))
        if not scores:
            continue
        best_idx = max(scores.items(), key=lambda kv: kv[1])[0]
        comp_bm_ids[int(best_idx)].append(int(bm_id))

    all_assigned_ids: list[int] = []
    for ids in comp_bm_ids.values():
        all_assigned_ids.extend(ids)
    if not all_assigned_ids:
        return {'sets': []}

    mapper_by_bm = _mapper_by_beatmap_ids(all_assigned_ids)
    max_set_size = max(4, min(14, int(round(6 + 6 * p.consolidation))))

    sets = []
    next_id = 0
    for idx, comp in enumerate(components):
        bm_ids = comp_bm_ids.get(idx) or []
        if not bm_ids:
            continue
        top_tags = sorted(comp, key=lambda t: int(tag_support.get(int(t)) or 0), reverse=True)[:max_set_size]
        tags_out = [tag_name_map.get(int(t)) for t in top_tags]
        tags_out = [t for t in tags_out if t]
        m_ctr: Counter[str] = Counter()
        for bm_id in bm_ids:
            m = mapper_by_bm.get(int(bm_id))
            if m:
                m_ctr[m] += 1
        sets.append({
            'id': next_id,
            'tags': tags_out,
            'map_count': int(len(bm_ids)),
            'top_mappers': [{'name': n, 'count': int(c)} for n, c in m_ctr.most_common(p.max_mappers)],
        })
        next_id += 1
        if len(sets) >= max_sets:
            break

    sets.sort(key=lambda s: int(s.get('map_count') or 0), reverse=True)
    return {'sets': sets}


