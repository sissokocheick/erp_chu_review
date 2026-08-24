"""
Indexes de performance pour PostgreSQL.
Optimise les pages les plus lentes identifiées par le benchmark avec 915K+ records.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0005_alter_bonmouvement_options'),
    ]

    operations = [
        # ═══════════════════════════════════════════════════════════════════
        # Bons de mouvement (200K+ lignes)
        # ═══════════════════════════════════════════════════════════════════
        migrations.AddIndex(
            model_name='bonmouvement',
            index=models.Index(fields=['type_bon', 'date_bon'], name='idx_bon_type_date'),
        ),
        migrations.AddIndex(
            model_name='bonmouvement',
            index=models.Index(fields=['magasin'], name='idx_bon_magasin'),
        ),
        migrations.AddIndex(
            model_name='bonmouvement',
            index=models.Index(fields=['statut_validation'], name='idx_bon_statut'),
        ),
        migrations.AddIndex(
            model_name='bonmouvement',
            index=models.Index(
                fields=['type_bon'],
                condition=models.Q(is_deleted=False),
                name='idx_bon_type_active',
            ),
        ),

        # ═══════════════════════════════════════════════════════════════════
        # Lignes de bons (500K+ lignes)
        # ═══════════════════════════════════════════════════════════════════
        migrations.AddIndex(
            model_name='lignebon',
            index=models.Index(fields=['bon'], name='idx_ligne_bon'),
        ),
        migrations.AddIndex(
            model_name='lignebon',
            index=models.Index(fields=['article'], name='idx_ligne_article'),
        ),

        # ═══════════════════════════════════════════════════════════════════
        # Stock items (100K+ lignes)
        # ═══════════════════════════════════════════════════════════════════
        migrations.AddIndex(
            model_name='stockitem',
            index=models.Index(fields=['article'], name='idx_stockitem_article'),
        ),
        migrations.AddIndex(
            model_name='stockitem',
            index=models.Index(fields=['magasin'], name='idx_stockitem_magasin'),
        ),

        # ═══════════════════════════════════════════════════════════════════
        # Articles (100K+ lignes)
        # ═══════════════════════════════════════════════════════════════════
        migrations.AddIndex(
            model_name='article',
            index=models.Index(fields=['famille'], name='idx_article_famille'),
        ),

        # ═══════════════════════════════════════════════════════════════════
        # Mouvements (dashboard, historique)
        # ═══════════════════════════════════════════════════════════════════
        migrations.AddIndex(
            model_name='mouvement',
            index=models.Index(fields=['type_mouvement', 'date_mouvement'], name='idx_mouv_type_date'),
        ),
        migrations.AddIndex(
            model_name='mouvement',
            index=models.Index(fields=['magasin'], name='idx_mouv_magasin'),
        ),

        # ═══════════════════════════════════════════════════════════════════
        # Demandes (10K+ lignes)
        # ═══════════════════════════════════════════════════════════════════
        migrations.AddIndex(
            model_name='demandemateriel',
            index=models.Index(fields=['statut'], name='idx_demande_statut'),
        ),
        migrations.AddIndex(
            model_name='demandemateriel',
            index=models.Index(fields=['date_demande'], name='idx_demande_date'),
        ),

        # ═══════════════════════════════════════════════════════════════════
        # Commandes
        # ═══════════════════════════════════════════════════════════════════
        migrations.AddIndex(
            model_name='commande',
            index=models.Index(fields=['statut_validation'], name='idx_cmd_statut'),
        ),
    ]
