# accounts/backends.py
"""
Backend d'authentification multi-tenant.
Vérifie que l'utilisateur appartient bien à l'entreprise sélectionnée.
"""
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from accounts.models import Profil, Entreprise
import logging

logger = logging.getLogger('auth')


class TenantAwareBackend(ModelBackend):
    """
    Backend qui vérifie l'appartenance à l'entreprise lors de l'authentification.
    
    Scénarios gérés :
    1. Username + mot de passe + entreprise → Vérifie exactement ce compte
    2. Username + mot de passe (sans entreprise) → Premier compte trouvé avec ce mot de passe
    3. Username existe dans plusieurs entreprises avec le même mot de passe → Connexion refusée
       (l'utilisateur doit spécifier son entreprise)
    """
    
    def authenticate(self, request, username=None, password=None, entreprise_id=None, **kwargs):
        if username is None or password is None:
            return None
        
        username = username.lower().strip()
        
        # 1. Cherche TOUS les utilisateurs avec ce username (toutes entreprises confondues)
        users = User.objects.filter(
            username__iexact=username,
            is_active=True
        ).select_related('profil__entreprise')
        
        if not users.exists():
            # Aucun utilisateur trouvé → échec
            return None
        
        # 2. Filtre ceux qui ont le bon mot de passe
        matching_users = []
        for user in users:
            if user.check_password(password):
                matching_users.append(user)
        
        if not matching_users:
            # Aucun mot de passe ne correspond → échec
            return None
        
        # 3. Si une entreprise est spécifiée, on filtre par entreprise
        if entreprise_id:
            try:
                entreprise_id = int(entreprise_id)
                for user in matching_users:
                    if hasattr(user, 'profil') and user.profil.entreprise_id == entreprise_id:
                        logger.info(
                            f"✅ Connexion réussie : {user.username} → "
                            f"Entreprise « {user.profil.entreprise.nom} »"
                        )
                        return user
                
                # Aucun utilisateur dans cette entreprise avec ce mot de passe
                logger.warning(
                    f"❌ Échec connexion : {username} existe mais pas dans l'entreprise #{entreprise_id}"
                )
                return None
                
            except (ValueError, TypeError):
                pass
        
        # 4. Pas d'entreprise spécifiée
        if len(matching_users) == 1:
            # Un seul compte correspond → connexion directe
            user = matching_users[0]
            entreprise_nom = user.profil.entreprise.nom if hasattr(user, 'profil') and user.profil else 'Inconnue'
            logger.info(f"✅ Connexion réussie : {user.username} → Entreprise « {entreprise_nom} »")
            return user
        
        # 5. PLUSIEURS comptes avec le même username ET le même mot de passe
        # → On refuse la connexion pour éviter toute ambiguïté
        entreprises = []
        for u in matching_users:
            if hasattr(u, 'profil') and u.profil and u.profil.entreprise:
                entreprises.append(u.profil.entreprise.nom)
        
        logger.warning(
            f"⚠️ Connexion AMBIGUË : {username} existe dans {len(matching_users)} entreprises "
            f"avec le même mot de passe : {', '.join(entreprises)}"
        )
        
        # On stocke l'info dans la session pour afficher un message
        if request:
            request.session['login_entreprises_ambiguës'] = entreprises
        
        return None  # Échec → l'utilisateur doit choisir son entreprise


    def get_user(self, user_id):
        """Récupère un utilisateur par son ID (requis par Django)."""
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None