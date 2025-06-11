# echosu/views/settings.py

# Django imports
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction

# REST framework imports
from rest_framework.authtoken.models import Token

# Local application imports
from ..models import TagApplication, CustomToken # Assuming CustomToken is in your models


# ----------------------------- Settings View ----------------------------- #

@login_required
def settings(request):
    if request.method == 'POST' and 'generate_token' in request.POST:
        CustomToken.objects.filter(user=request.user).delete()
        token, raw_key = CustomToken.create_token(request.user)
        print(f"raw_key passed to template from view: {raw_key}")
        return render(request, 'settings.html', {'full_key': raw_key, 'user': request.user})
    else:
        return render(request, 'settings.html', {'user': request.user})




from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction


@login_required
def confirm_data_deletion(request):
    return render(request, 'confirm_data_deletion.html')

@login_required
def delete_user_data(request):
    if request.method == 'POST':
        user = request.user
        try:
            with transaction.atomic():
                # Delete user's tag applications
                TagApplication.objects.filter(user=user).delete()

                # Delete other related data if necessary
                # For example, user profile
                if hasattr(user, 'profile'):
                    user.profile.delete()

                # Do NOT delete the user account

            messages.success(request, 'Your contributions have been successfully deleted.')
            return redirect('settings')

        except Exception as e:
            messages.error(request, 'An error occurred while deleting your data.')
            print(e)
            return redirect('settings')
    else:
        return redirect('settings')