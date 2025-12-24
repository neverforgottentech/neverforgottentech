# neverforgotten/adapters.py
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model
from django.contrib import messages

class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Custom adapter to automatically connect social accounts
    to existing users with the same email address.
    """
    
    def pre_social_login(self, request, sociallogin):
        """
        Connect social account to existing user if email matches.
        """
        user = sociallogin.user
        
        # If user already logged in, do nothing
        if user.id:
            return
        
        email = user.email
        if not email:
            return
        
        # Check if user with this email already exists
        try:
            existing_user = get_user_model().objects.get(email=email)
            
            # Connect the social account to existing user
            sociallogin.connect(request, existing_user)
            
            # Show success message
            messages.info(
                request, 
                f"Connected your Google account to existing account for {email}."
            )
            
        except get_user_model().DoesNotExist:
            # New user, proceed normally
            pass