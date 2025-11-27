# echosu/views/settings.py
"""Settings views for user account management.
This module provides views for user settings, including generating custom tokens,
confirming data deletion, and deleting user data.
It includes functionality for authenticated users to manage their account settings
and delete their contributions.
"""


# ---------------------------------------------------------------------------
# Django imports
# ---------------------------------------------------------------------------
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.http import JsonResponse

# ---------------------------------------------------------------------------
# Local application imports
# ---------------------------------------------------------------------------
from ..models import CustomToken, TagApplication, UserSettings, ManiaKeyOption


# ----------------------------- Settings Views ----------------------------- #

@login_required
def settings(request):
    mania_key_queryset = list(ManiaKeyOption.objects.order_by('value'))
    mania_key_options = [{'value': opt.value_string, 'label': opt.label} for opt in mania_key_queryset]
    valid_mania_keys = {opt['value'] for opt in mania_key_options}
    valid_mania_keys.add('any')

    if request.method == 'POST':
        # AJAX auto-save of preferences (JSON or form-encoded)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get('content-type', '').startswith('application/json'):
            try:
                payload = request.POST.dict() if request.content_type != 'application/json' else (request.body and __import__('json').loads(request.body.decode('utf-8')) or {})
            except Exception:
                payload = request.POST.dict()
            us, _ = UserSettings.objects.get_or_create(user=request.user)
            changed = []
            # Allowed fields for auto-save
            allowed_bool_fields = {
                'group_related_tags',
                'show_star_rating','show_status','show_cs','show_hp','show_od','show_ar',
                'show_bpm','show_length','show_year','show_playcount','show_favourites',
                'show_genres','show_pp_nm','show_pp_hd','show_pp_hr','show_pp_dt','show_pp_ht','show_pp_ez','show_pp_fl','show_pp_calculator'
            }
            allowed_select_fields = {'tag_category_display', 'default_mode', 'default_mania_keys'}
            valid_modes = {'osu', 'taiko', 'catch', 'mania'}
            for key, val in payload.items():
                if key in allowed_bool_fields:
                    new_val = str(val).lower() in ['1','true','on','yes']
                    if getattr(us, key, None) != new_val:
                        setattr(us, key, new_val)
                        changed.append(key)
                elif key in allowed_select_fields:
                    if key == 'default_mode':
                        new_pref = (val or 'osu').strip().lower()
                        if new_pref not in valid_modes:
                            new_pref = 'osu'
                    elif key == 'default_mania_keys':
                        new_pref = (val or 'any').strip()
                        if new_pref not in valid_mania_keys:
                            new_pref = 'any'
                    else:
                        new_pref = (val or 'none').strip().lower()
                        if new_pref not in ['none','color','lists']:
                            new_pref = 'none'
                    if getattr(us, key, None) != new_pref:
                        setattr(us, key, new_pref)
                        changed.append(key)
            if changed:
                us.save(update_fields=changed)
            return JsonResponse({'ok': True, 'changed': changed})
        # Generate API token
        if 'generate_token' in request.POST:
            CustomToken.objects.filter(user=request.user).delete()
            token, raw_key = CustomToken.create_token(request.user)
            return render(request, 'settings.html', {'full_key': raw_key, 'user': request.user})
        # Save preferences
        if request.POST.get('update_preferences') == '1':
            valid_modes = {'osu', 'taiko', 'catch', 'mania'}
            pref = (request.POST.get('tag_category_display') or 'none').strip().lower()
            if pref not in ['none', 'color', 'lists']:
                pref = 'none'
            us, _ = UserSettings.objects.get_or_create(user=request.user)
            changed = []
            if getattr(us, 'tag_category_display', None) != pref:
                us.tag_category_display = pref
                changed.append('tag_category_display')
            mode_pref = (request.POST.get('default_mode') or 'osu').strip().lower()
            if mode_pref not in valid_modes:
                mode_pref = 'osu'
            if getattr(us, 'default_mode', None) != mode_pref:
                us.default_mode = mode_pref
                changed.append('default_mode')
            mania_pref = (request.POST.get('default_mania_keys') or 'any').strip()
            if mania_pref not in valid_mania_keys:
                mania_pref = 'any'
            if getattr(us, 'default_mania_keys', None) != mania_pref:
                us.default_mania_keys = mania_pref
                changed.append('default_mania_keys')
            # Booleans (in case form posts non-AJAX)
            bool_fields = [
                'group_related_tags','show_star_rating','show_status','show_cs','show_hp','show_od','show_ar',
                'show_bpm','show_length','show_year','show_playcount','show_favourites','show_genres',
                'show_pp_nm','show_pp_hd','show_pp_hr','show_pp_dt','show_pp_ht','show_pp_ez','show_pp_fl','show_pp_calculator'
            ]
            for key in bool_fields:
                if key in request.POST:
                    new_val = str(request.POST.get(key)).lower() in ['1','true','on','yes']
                    if getattr(us, key, None) != new_val:
                        setattr(us, key, new_val)
                        changed.append(key)
            if changed:
                us.save(update_fields=changed)
            return render(request, 'settings.html', {
                'user': request.user,
                'tag_category_display': us.tag_category_display,
                'group_related_tags': us.group_related_tags,
                'default_mode': getattr(us, 'default_mode', 'osu'),
                'default_mania_keys': getattr(us, 'default_mania_keys', 'any'),
                'mania_key_options': mania_key_options,
            })
    # GET
    try:
        user_settings = request.user.settings
        tag_pref = user_settings.tag_category_display
        group_related = bool(getattr(user_settings, 'group_related_tags', False))
        default_mode = getattr(user_settings, 'default_mode', 'osu')
        default_mania_keys = getattr(user_settings, 'default_mania_keys', 'any')
    except Exception:
        tag_pref = 'none'
        group_related = False
        default_mode = 'osu'
        default_mania_keys = 'any'
    return render(request, 'settings.html', {
        'user': request.user,
        'tag_category_display': tag_pref,
        'group_related_tags': group_related,
        'default_mode': default_mode,
        'default_mania_keys': default_mania_keys,
        'mania_key_options': mania_key_options,
    })


@login_required
def confirm_data_deletion(request):
    return render(request, 'confirm_data_deletion.html')


@login_required
def delete_user_data(request):
    if request.method == 'POST':
        user = request.user
        try:
            with transaction.atomic():
                # Delete the user’s tag applications
                TagApplication.objects.filter(user=user).delete()

                # Optionally remove profile but keep the account
                if hasattr(user, 'profile'):
                    user.profile.delete()

            messages.success(request, 'Your contributions have been successfully deleted.')
        except Exception as exc:
            messages.error(request, 'An error occurred while deleting your data.')
        return redirect('settings')

    return redirect('settings')
