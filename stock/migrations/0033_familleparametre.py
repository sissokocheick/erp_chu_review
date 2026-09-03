from django.db import migrations, models


def seed_famille_parametres(apps, schema_editor):
    FamilleParametre = apps.get_model('stock', 'FamilleParametre')
    FamilleArticle = apps.get_model('stock', 'FamilleArticle')

    defaults = {
        'TYPE_FAMILLE': ('MED', 'MAT', 'BUR', 'TEC'),
        'VALORISATION': ('CMUP', 'FIFO', 'LIFO'),
        'CATEGORIE': (),
        'LIGNE_BUDGETAIRE': (),
    }
    for type_parametre, valeurs in defaults.items():
        for valeur in valeurs:
            FamilleParametre.objects.get_or_create(
                type_parametre=type_parametre,
                valeur=valeur,
                defaults={'actif': True},
            )

    legacy_fields = {
        'TYPE_FAMILLE': 'type_famille',
        'VALORISATION': 'methode_valorisation',
        'CATEGORIE': 'categorie',
        'LIGNE_BUDGETAIRE': 'ligne_budgetaire',
    }
    for type_parametre, field_name in legacy_fields.items():
        valeurs = (
            FamilleArticle.objects
            .exclude(**{f'{field_name}__isnull': True})
            .exclude(**{field_name: ''})
            .values_list(field_name, flat=True)
            .distinct()
        )
        for valeur in valeurs:
            FamilleParametre.objects.get_or_create(
                type_parametre=type_parametre,
                valeur=valeur,
                defaults={'actif': True},
            )


class Migration(migrations.Migration):
    dependencies = [
        ('stock', '0032_type_famille_valorisation_dynamiques'),
    ]

    operations = [
        migrations.CreateModel(
            name='FamilleParametre',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('type_parametre', models.CharField(choices=[('TYPE_FAMILLE', 'Type de famille'), ('VALORISATION', 'Méthode de valorisation'), ('CATEGORIE', 'Catégorie'), ('LIGNE_BUDGETAIRE', 'Ligne budgétaire')], db_index=True, max_length=30)),
                ('valeur', models.CharField(max_length=100)),
                ('actif', models.BooleanField(db_index=True, default=True)),
                ('date_creation', models.DateTimeField(auto_now_add=True)),
                ('date_modification', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Paramètre de famille',
                'verbose_name_plural': 'Paramètres de familles',
                'ordering': ['type_parametre', 'valeur'],
            },
        ),
        migrations.AddConstraint(
            model_name='familleparametre',
            constraint=models.UniqueConstraint(fields=('type_parametre', 'valeur'), name='unique_famille_parametre_valeur'),
        ),
        migrations.RunPython(seed_famille_parametres, migrations.RunPython.noop),
    ]
