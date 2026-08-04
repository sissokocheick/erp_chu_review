# Generated manually — creates historical tables for django-simple-history
from django.db import migrations, connection


MODELS_WITH_HISTORY = [
    'Fournisseur',
    'FamilleArticle',
    'Article',
    'Magasin',
    'StockItem',
    'Mouvement',
    'Ajustement',
    'CampagneInventaire',
    'LigneInventaire',
    'BonMouvement',
    'Commande',
    'DemandeMateriel',
    'LivraisonPartielle',
]


def create_historical_tables(apps, schema_editor):
    """Crée les tables historiques manquantes pour django-simple-history."""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public' AND tablename LIKE 'stock_historical%%'
        """)
        existing = {row[0] for row in cursor.fetchall()}

    for model_name in MODELS_WITH_HISTORY:
        hist_name = f'Historical{model_name}'
        table_name = f'stock_historical{model_name.lower()}'

        if table_name in existing:
            print(f"  Table {table_name} existe déjà — ignorée.")
            continue

        try:
            hist_model = apps.get_model('stock', hist_name)
            schema_editor.create_model(hist_model)
            print(f"  ✅ Table {table_name} créée.")
        except LookupError:
            print(f"  ⚠️ Modèle historique {hist_name} introuvable — ignoré.")
        except Exception as e:
            print(f"  ⚠️ Erreur création {table_name}: {e}")


def delete_historical_tables(apps, schema_editor):
    """Reverse : supprime les tables historiques (attention, perte de données)."""
    with connection.cursor() as cursor:
        for model_name in MODELS_WITH_HISTORY:
            table_name = f'stock_historical{model_name.lower()}'
            cursor.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE;')


class Migration(migrations.Migration):
    dependencies = [
        ('stock', '0002_remove_entreprise_id'),
    ]

    operations = [
        migrations.RunPython(
            create_historical_tables,
            reverse_code=delete_historical_tables,
        ),
    ]
