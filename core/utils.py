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
        from core.models import ConfigurationHopital
        # ✅ CORRECTION MONO-TENANT : DocumentGenerator() sans argument
        # utilisait un fallback first() supprimé. On passe explicitement
        # le singleton ConfigurationHopital.
        gen = DocumentGenerator(entreprise=ConfigurationHopital.get_instance())
        return gen.render_bytes(template_name, context_dict)
    except ImportError:
        pass

    # Fallback legacy (WeasyPrint direct)
    html_string = render_to_string(template_name, context_dict)
    pdf_file = HTML(string=html_string).write_pdf()
    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response
