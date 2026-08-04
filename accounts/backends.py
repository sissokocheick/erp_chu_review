from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()


class StandardBackend(ModelBackend):
    """
    ✅ CORRECTION : backend d'authentification standard Django.
    Le TenantAwareBackend est supprimé (mono-tenant).
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if username is None or password is None:
            return None
        try:
            user = User._default_manager.get_by_natural_key(username)
        except User.DoesNotExist:
            # Run the default password hasher once to reduce the timing
            # difference between an existing and a non-existing user.
            User().set_password(password)
        else:
            if user.check_password(password) and self.user_can_authenticate(user):
                return user
