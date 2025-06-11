# echosu/views/profile.py
'''
User profile pages and public user-stats view.

Imports are consolidated and ordered, duplicates removed, and single
quotes are used wherever it doesn't require additional escaping.
Business logic is unchanged.
'''

# ---------------------------------------------------------------------------
# Standard library imports
# ---------------------------------------------------------------------------
import json
from collections import Counter

# ---------------------------------------------------------------------------
# Third‑party imports
# ---------------------------------------------------------------------------
import numpy as np
from scipy.spatial.distance import cosine

# ---------------------------------------------------------------------------
# Django imports
# ---------------------------------------------------------------------------
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.shortcuts import redirect, render

# ---------------------------------------------------------------------------
# Local application imports
# ---------------------------------------------------------------------------
from ..models import APIRequestLog, Beatmap, TagApplication

# ---------------------------------------------------------------------------
# Profile view
# ---------------------------------------------------------------------------

@login_required
def profile(request):
    '''Render the logged‑in user’s profile with tagging stats.'''    
    user_tags = (
        TagApplication.objects
        .filter(user=request.user)
        .select_related('beatmap')
    )

    # Accuracy of the user’s tags
    total_tags = user_tags.count()
    agreed_tags = sum(1 for tag_app in user_tags if tag_app.agreed_by_others())
    accuracy = (agreed_tags / total_tags * 100) if total_tags else 0

    # Top‑10 tag distribution for a simple pie chart
    tag_counts = Counter(tag_app.tag.name for tag_app in user_tags)
    most_common = tag_counts.most_common(10)

    context = {
        'user_tags': user_tags,
        'accuracy': accuracy,
        'tag_labels': json.dumps([t for t, _ in most_common]),
        'tag_data': json.dumps([c for _, c in most_common]),
    }

    return render(request, 'profile.html', context)


# ---------------------------------------------------------------------------
# Public & private aggregate stats endpoint
# ---------------------------------------------------------------------------

def user_stats(request):
    '''Public statistic page for any osu! username; shows private data to the owner.'''    
    query = request.GET.get('query', '').strip()
    context = {'query': query}

    if query:
        # ------------------------- Public stats -------------------------
        user_maps = Beatmap.objects.filter(creator=query)
        if user_maps.exists():
            # Tag histogram (top‑20)
            map_tags = (
                TagApplication.objects
                .filter(beatmap__in=user_maps)
                .values('tag__name')
                .annotate(count=Count('beatmap', distinct=True))
                .order_by('-count')[:20]
            )
            tag_labels = [t['tag__name'] for t in map_tags]
            tag_data = [t['count'] for t in map_tags]

            context.update({
                'public_stats_for': query,
                'tag_labels': tag_labels,
                'tag_data': tag_data,
                'tag_pairs': list(zip(tag_labels, tag_data)),
            })

            # Find the most / least representative maps by cosine distance
            beatmap_vectors, beatmap_ids = [], []
            for bm in user_maps:
                bm_tags = (
                    TagApplication.objects
                    .filter(beatmap=bm)
                    .values('tag__name')
                    .annotate(count=Count('id'))
                )
                vec = [next((x['count'] for x in bm_tags if x['tag__name'] == lbl), 0)
                       for lbl in tag_labels]
                beatmap_vectors.append(vec)
                beatmap_ids.append(bm.id)

            if beatmap_vectors:
                avg = np.mean(beatmap_vectors, axis=0)
                dists = [cosine(avg, v) if np.linalg.norm(v) else 1 for v in beatmap_vectors]

                most = Beatmap.objects.get(id=beatmap_ids[int(np.argmin(dists))])
                least = Beatmap.objects.get(id=beatmap_ids[int(np.argmax(dists))])

                context.update({
                    'most_rep_map': most,
                    'least_rep_map': least,
                    'most_rep_tags': list(
                        TagApplication.objects
                        .filter(beatmap=most)
                        .values('tag__name')
                        .annotate(count=Count('id'))
                        .order_by('-count')
                    ),
                    'least_rep_tags': list(
                        TagApplication.objects
                        .filter(beatmap=least)
                        .values('tag__name')
                        .annotate(count=Count('id'))
                        .order_by('-count')
                    ),
                })
        else:
            context['error'] = f"No maps found for '{query}'."

        # ------------------------- Private stats (owner only) ----------
        if request.user.is_authenticated and request.user.username == query:
            apps = (
                TagApplication.objects
                .filter(user=request.user)
                .select_related('beatmap', 'tag')
            )

            # Tags by beatmap for table view
            beatmap_tags = {}
            for a in apps:
                beatmap_tags.setdefault(a.beatmap, []).append(a.tag.name)
            context['beatmap_tags'] = beatmap_tags

            # Recent searches
            context['search_logs'] = (
                APIRequestLog.objects
                .filter(user=request.user, path__icontains='/search_results/')
                .order_by('-timestamp')[:50]
            )

            # Tagging activity over time
            activity = (
                apps
                .annotate(day=TruncDate('created_at'))
                .values('day')
                .annotate(count=Count('id'))
                .order_by('day')
            )
            context.update({
                'activity_days': [e['day'].strftime('%Y-%m-%d') for e in activity],
                'activity_counts': [e['count'] for e in activity],
            })

    return render(request, 'user_stats.html', context)
