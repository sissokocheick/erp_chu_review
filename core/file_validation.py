# -*- coding: utf-8 -*-
"""Validation des fichiers uploadés (scans PDF/images, classeurs .xlsx).

Vérifie la taille ET la signature réelle du fichier (magic bytes), pas
seulement l'extension — un .pdf malveillant renommé est refusé.
"""

# Signatures (magic bytes) par format
SIGNATURES = {
    'pdf': b'%PDF',
    'jpg': b'\xff\xd8\xff',
    'jpeg': b'\xff\xd8\xff',
    'png': b'\x89PNG\r\n\x1a\n',
    'xlsx': b'PK\x03\x04',  # archive ZIP (OOXML)
}


def valider_fichier_upload(fichier, extensions, taille_max):
    """Valide un upload : extension autorisée + taille + signature réelle.

    Args:
        fichier: django.core.files.UploadedFile
        extensions: tuple d'extensions SANS point, ex ('pdf', 'jpg', 'png')
        taille_max: taille max en octets

    Returns:
        (ok: bool, message_erreur: str|None)
    """
    if fichier is None:
        return False, "Aucun fichier fourni."

    # 1. Extension
    nom = (fichier.name or '').lower()
    ext = nom.rsplit('.', 1)[-1] if '.' in nom else ''
    if ext not in extensions:
        formats = ', '.join(e.upper() for e in extensions)
        return False, f"Format invalide. Seuls {formats} sont acceptés."

    # 2. Taille
    if fichier.size > taille_max:
        return False, (
            f"Fichier trop lourd ({fichier.size // 1024} Ko > "
            f"{taille_max // 1024} Ko)."
        )

    # 3. Signature (magic bytes)
    signature_attendue = SIGNATURES.get(ext)
    if signature_attendue is not None:
        try:
            fichier.seek(0)
            entete = fichier.read(len(signature_attendue))
            fichier.seek(0)
        except Exception:
            return False, "Fichier illisible."
        if not entete.startswith(signature_attendue):
            return False, (
                "Le contenu du fichier ne correspond pas à son format "
                f"(.{ext}). Fichier refusé."
            )

    return True, None


def valider_scan_document(fichier, taille_max=1024 * 1024):
    """Scans de bons : PDF / JPG / PNG (1 Mo par défaut)."""
    return valider_fichier_upload(fichier, ('pdf', 'jpg', 'jpeg', 'png'), taille_max)


def valider_classeur_xlsx(fichier, taille_max=5 * 1024 * 1024):
    """Imports Excel : .xlsx uniquement (5 Mo par défaut)."""
    return valider_fichier_upload(fichier, ('xlsx',), taille_max)
