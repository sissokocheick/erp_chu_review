# core/utils.py — CORRIGÉ (mono-tenant v1)
from django.http import HttpResponse
from django.template.loader import render_to_string
from weasyprint import HTML
import warnings


def generer_pdf(template_name, context_dict, filename="document.pdf"):
    """
    ⚠️ DEPRECATED : Cette fonction est obsolète et sera supprimée.
    Utiliser DocumentGenerator.render_bytes() à la place.
    """
    warnings.warn(
        "generer_pdf est déprécié et sera supprimé. "
        "Utiliser DocumentGenerator.render_bytes() à la place.",
        DeprecationWarning,
        stacklevel=2
    )

    try:
        from core.pdf_service import DocumentGenerator
        # Mono-tenant : DocumentGenerator utilise lui-même le singleton
        # ConfigurationHopital pour la configuration de l'établissement.
        gen = DocumentGenerator()
        return gen.render_bytes(template_name, context_dict)
    except ImportError:
        pass

    # Fallback legacy (WeasyPrint direct)
    html_string = render_to_string(template_name, context_dict)
    pdf_file = HTML(string=html_string).write_pdf()
    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response
