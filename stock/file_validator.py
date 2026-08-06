"""
Module de validation de fichiers uploadés
Sécurité renforcée pour les uploads dans Stock
"""
import magic
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# Whitelist des MIME types autorisés
ALLOWED_MIME_TYPES = {
    'application/pdf',
    'image/jpeg',
    'image/png',
    'image/jpg',
}

# Extension → MIME type attendu
EXTENSION_MIME_MAP = {
    '.pdf': 'application/pdf',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
}

# Taille maximale : 1 Mo
MAX_FILE_SIZE = 1024 * 1024  # 1 Mo


def validate_uploaded_file(file):
    """
    Validation complète d'un fichier uploadé :
    1. Vérification de la taille
    2. Vérification de l'extension
    3. Vérification du MIME type réel (magic bytes)
    4. Cohérence extension/MIME type
    
    Lève ValidationError si le fichier n'est pas sécurisé
    """
    # 1. Vérification taille
    if file.size > MAX_FILE_SIZE:
        raise ValidationError(
            _("Fichier trop lourd (%(size)d Ko). Maximum 1 Mo autorisé."),
            params={'size': file.size // 1024},
        )
    
    # 2. Vérification extension
    filename = file.name.lower()
    allowed_extensions = list(EXTENSION_MIME_MAP.keys())
    if not any(filename.endswith(ext) for ext in allowed_extensions):
        raise ValidationError(
            _("Extension non autorisée. Seuls PDF, JPG et PNG sont acceptés."),
        )
    
    # 3. Détection du vrai MIME type (magic bytes)
    file.seek(0)  # Rewind pour lecture depuis le début
    mime = magic.from_buffer(file.read(1024), mime=True)
    file.seek(0)  # Rewind pour utilisation ultérieure
    
    if mime not in ALLOWED_MIME_TYPES:
        raise ValidationError(
            _("Type de fichier non autorisé détecté : %(mime)s"),
            params={'mime': mime},
        )
    
    # 4. Cohérence extension/MIME type
    ext = '.' + filename.rsplit('.', 1)[-1] if '.' in filename else ''
    expected_mime = EXTENSION_MIME_MAP.get(ext)
    
    if expected_mime and mime != expected_mime:
        raise ValidationError(
            _("Incohérence détectée : extension %(ext)s mais type réel %(mime)s"),
            params={'ext': ext, 'mime': mime},
        )
    
    return True


def validate_image_file(file):
    """Validation spécifique pour les images uniquement"""
    validate_uploaded_file(file)
    # Vérification supplémentaire : c'est bien une image
    file.seek(0)
    mime = magic.from_buffer(file.read(1024), mime=True)
    file.seek(0)
    if not mime.startswith('image/'):
        raise ValidationError(_("Le fichier doit être une image valide."))
    return True
