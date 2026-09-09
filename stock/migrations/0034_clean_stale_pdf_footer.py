from django.db import migrations

def clean_stale_footers(apps, schema_editor):
    ModeleDocumentMagasin = apps.get_model('stock', 'ModeleDocumentMagasin')
    for m in ModeleDocumentMagasin.objects.all():
        cfg = m.config or {}
        if isinstance(cfg, dict) and 'pied_de_page' in cfg and isinstance(cfg['pied_de_page'], dict):
            if 'texte_personnalise' in cfg['pied_de_page']:
                del cfg['pied_de_page']['texte_personnalise']
                m.config = cfg
                m.save()

def reverse_noop(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0033_familleparametre'),
    ]

    operations = [
        migrations.RunPython(clean_stale_footers, reverse_noop),
    ]
