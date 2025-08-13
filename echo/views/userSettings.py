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

# ---------------------------------------------------------------------------
# Local application imports
# ---------------------------------------------------------------------------
from ..models import CustomToken, TagApplication


# ----------------------------- Settings Views ----------------------------- #

@login_required
def settings(request):
    if request.method == 'POST' and 'generate_token' in request.POST:
        CustomToken.objects.filter(user=request.user).delete()
        token, raw_key = CustomToken.create_token(request.user)
        return render(request, 'settings.html', {'full_key': raw_key, 'user': request.user})
    return render(request, 'settings.html', {'user': request.user})


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
