# echosu/views/profile.py

# Standard library imports
import json
from collections import Counter

# Third-party imports
import numpy as np
from scipy.spatial.distance import cosine

# Django imports
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.db.models import Count
from django.db.models.functions import TruncDate

# Local application imports
from ..models import Beatmap, TagApplication, APIRequestLog


# ----------------------------- Profile Views ----------------------------- #

def profile(request):
    """
    User profile view displaying tagging statistics.
    """
    if request.user.is_authenticated:
        user_tags = TagApplication.objects.filter(user=request.user).select_related('beatmap')

        # Calculate accuracy of user's tagging
        total_tags = user_tags.count()
        agreed_tags = sum(1 for tag_app in user_tags if tag_app.agreed_by_others())
        accuracy = (agreed_tags / total_tags * 100) if total_tags > 0 else 0

        # Prepare data for the pie chart
        tag_counts = Counter(tag_app.tag.name for tag_app in user_tags)
        most_common_tags = tag_counts.most_common(10)
        tag_labels = [tag for tag, count in most_common_tags]
        tag_data = [count for tag, count in most_common_tags]

        context = {
            'user_tags': user_tags,
            'accuracy': accuracy,
            'tag_labels': json.dumps(tag_labels),
            'tag_data': json.dumps(tag_data),
        }

        return render(request, 'profile.html', context)
    else:
        return redirect('login')  # Redirect to login if user is not authenticated



from django.db.models import Count
from django.db.models.functions import TruncDate
from django.shortcuts import render
from echo.models import Beatmap, TagApplication, APIRequestLog
import numpy as np
from scipy.spatial.distance import cosine

def user_stats(request):
    query = request.GET.get('query', '').strip()
    context = {'query': query}

    if query:
        # PUBLIC STATS
        user_maps = Beatmap.objects.filter(creator=query)
        if user_maps.exists():
            # count distinct maps per tag
            map_tags = (
                TagApplication.objects
                .filter(beatmap__in=user_maps)
                .values('tag__name')
                .annotate(count=Count('beatmap', distinct=True))
                .order_by('-count')[:20]
            )
            tag_labels = [t['tag__name'] for t in map_tags]
            tag_data   = [t['count']      for t in map_tags]

            # make pairs for the template
            tag_pairs = list(zip(tag_labels, tag_data))

            context.update({
                'public_stats_for': query,
                'tag_labels': tag_labels,
                'tag_data': tag_data,
                'tag_pairs': tag_pairs,
            })
            # Representative Maps
            beatmap_vectors = []
            beatmap_ids = []
            for bm in user_maps:
                # build vector over top-20 tags
                tags = (
                    TagApplication.objects
                    .filter(beatmap=bm)
                    .values('tag__name')
                    .annotate(count=Count('id'))
                )
                vec = [ next((x['count'] for x in tags if x['tag__name']==lbl),0)
                        for lbl in tag_labels ]
                beatmap_vectors.append(vec)
                beatmap_ids.append(bm.id)

            avg_vector = np.mean(beatmap_vectors, axis=0) if beatmap_vectors else []
            distances = [
                cosine(avg_vector, v) if np.linalg.norm(v) else 1
                for v in beatmap_vectors
            ]

            if distances:
                most_idx  = int(np.argmin(distances))
                least_idx = int(np.argmax(distances))
                most = Beatmap.objects.get(id=beatmap_ids[most_idx])
                least= Beatmap.objects.get(id=beatmap_ids[least_idx])
                context.update({
                    'most_rep_map':  most,
                    'least_rep_map': least,
                    # collect full tag lists for each
                    'most_rep_tags':  list(
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

        # PRIVATE STATS (only if you’re that user)
        if request.user.is_authenticated and request.user.username == query:
            apps = TagApplication.objects.filter(user=request.user).select_related('beatmap','tag')
            bt = {}
            for a in apps:
                bt.setdefault(a.beatmap, []).append(a.tag.name)
            context['beatmap_tags']   = bt

            logs = (
                APIRequestLog.objects
                .filter(user=request.user, path__icontains='/search_results/')
                .order_by('-timestamp')[:50]
            )
            context['search_logs'] = logs

            activity = (
                apps
                .annotate(day=TruncDate('created_at'))
                .values('day')
                .annotate(count=Count('id'))
                .order_by('day')
            )
            context.update({
                'activity_days':   [e['day'].strftime('%Y-%m-%d') for e in activity],
                'activity_counts': [e['count'] for e in activity],
            })

    return render(request, 'user_stats.html', context)