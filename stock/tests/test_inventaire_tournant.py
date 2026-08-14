# -*- coding: utf-8 -*-
"""
Tests de l'inventaire tournant : planification de rotation par famille/zone,
génération automatique de campagnes ciblées, échéances, activation/pause.

Couvertures :
- création d'un plan (modèle + service)
- génération PAR_FAMILLE : seules les familles cibles sont comptées
- génération PAR_ZONE : toutes les familles du magasin
- échéance mise à jour après génération (aujourd'hui + fréquence)
- refus de générer un plan inactif ou sans familles
- vues : liste, création, génération manuelle, bascule statut
- quantité théorique = stock actuel du magasin (isolation)
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from stock.models import (
    Article, Magasin, PlanInventaireTournant, CampagneInventaire,
    LigneInventaire, StockItem, FamilleArticle,
)
from stock.services.inventaire_service import InventaireService
from stock.tests import factories

User = get_user_model()


class InventaireTournantBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='tournant', password='tournant2026')
        self.user.profil.doit_changer_mdp = False
        self.user.profil.save(update_fields=['doit_changer_mdp'])

        self.magasin = factories.creer_magasin(nom='Magasin Rotation')
        self.user.profil.magasins_autorises.add(self.magasin)

        self.fam_med = factories.creer_famille(code='MEDR', intitule='Médicaments')
        self.fam_mat = factories.creer_famille(code='MATR', intitule='Matériel')
        self.fam_bur = factories.creer_famille(code='BURR', intitule='Bureau')

        self.art_med = Article.objects.create(
            famille=self.fam_med, designation='Paracétamol',
            reference='ROT-MED-1', prix_reference=Decimal('100'))
        self.art_mat = Article.objects.create(
            famille=self.fam_mat, designation='Seringue',
            reference='ROT-MAT-1', prix_reference=Decimal('250'))
        self.art_bur = Article.objects.create(
            famille=self.fam_bur, designation='Ramette',
            reference='ROT-BUR-1', prix_reference=Decimal('30'))

        # Stock dans le magasin (et un autre magasin pour tester l'isolation)
        self.autre_mag = factories.creer_magasin(nom='Autre Magasin')
        self.user.profil.magasins_autorises.add(self.autre_mag)
        StockItem.objects.create(
            article=self.art_med, magasin=self.magasin,
            quantite_physique=40, valeur_cmup=Decimal('100'))
        StockItem.objects.create(
            article=self.art_mat, magasin=self.magasin,
            quantite_physique=15, valeur_cmup=Decimal('250'))
        StockItem.objects.create(
            article=self.art_bur, magasin=self.magasin,
            quantite_physique=7, valeur_cmup=Decimal('30'))
        # Stock dans l'autre magasin (ne doit pas compter)
        StockItem.objects.create(
            article=self.art_med, magasin=self.autre_mag,
            quantite_physique=999, valeur_cmup=Decimal('100'))

        self.client.force_login(self.user)
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin.id)
        session.save()

    def _creer_plan(self, type_rotation='PAR_FAMILLE', familles=None,
                    frequence=90, statut='ACTIF'):
        plan = PlanInventaireTournant.objects.create(
            titre='Rotation Trimestrielle',
            magasin=self.magasin,
            type_rotation=type_rotation,
            frequence_jours=frequence,
            statut=statut,
            cree_par=self.user,
            prochaine_echeance=timezone.now().date(),
        )
        if familles is not None:
            plan.familles_cibles.set(familles)
        return plan


class ServiceInventaireTournantTest(InventaireTournantBase):
    """Génération de campagnes ciblées via le service."""

    def test_generation_par_famille_ne_compte_que_les_familles_cibles(self):
        plan = self._creer_plan(familles=[self.fam_med, self.fam_mat])
        campagne = InventaireService.generer_campagne_tournante(plan, self.user)

        self.assertEqual(campagne.type_campagne, 'PAR_FAMILLE')
        lignes = list(campagne.lignes_inventaire.select_related('article'))
        self.assertEqual(len(lignes), 2)  # Paracétamol + Seringue, pas la Ramette
        by_art = {l.article_id: l for l in lignes}
        self.assertEqual(by_art[self.art_med.id].quantite_theorique, 40)
        self.assertEqual(by_art[self.art_mat.id].quantite_theorique, 15)

    def test_generation_par_zone_compte_toutes_les_familles(self):
        plan = self._creer_plan(type_rotation='PAR_ZONE')
        campagne = InventaireService.generer_campagne_tournante(plan, self.user)

        self.assertEqual(campagne.lignes_inventaire.count(), 3)
        by_art = {
            l.article_id: l
            for l in campagne.lignes_inventaire.select_related('article')
        }
        # Isolation : le stock de l'autre magasin (999) ne compte pas
        self.assertEqual(by_art[self.art_med.id].quantite_theorique, 40)

    def test_echeance_mise_a_jour_apres_generation(self):
        plan = self._creer_plan(familles=[self.fam_med], frequence=30)
        avant = plan.prochaine_echeance
        InventaireService.generer_campagne_tournante(plan, self.user)
        plan.refresh_from_db()

        attendu = timezone.now().date() + timezone.timedelta(days=30)
        self.assertEqual(plan.prochaine_echeance, attendu)
        self.assertIsNotNone(plan.dernier_comptage)
        self.assertNotEqual(plan.prochaine_echeance, avant)

    def test_refus_generation_plan_inactif(self):
        plan = self._creer_plan(familles=[self.fam_med], statut='INACTIF')
        with self.assertRaises(ValidationError):
            InventaireService.generer_campagne_tournante(plan, self.user)

    def test_refus_generation_sans_familles(self):
        plan = self._creer_plan(familles=[])
        with self.assertRaises(ValidationError):
            InventaireService.generer_campagne_tournante(plan, self.user)

    def test_campagne_generee_liee_au_magasin_du_plan(self):
        plan = self._creer_plan(familles=[self.fam_med])
        campagne = InventaireService.generer_campagne_tournante(plan, self.user)
        self.assertEqual(campagne.magasin, self.magasin)

    def test_generation_creer_une_nouvelle_campagne_a_chaque_fois(self):
        plan = self._creer_plan(familles=[self.fam_med])
        c1 = InventaireService.generer_campagne_tournante(plan, self.user)
        c2 = InventaireService.generer_campagne_tournante(plan, self.user)
        self.assertNotEqual(c1.id, c2.id)
        self.assertEqual(CampagneInventaire.objects.count(), 2)


class VuesInventaireTournantTest(InventaireTournantBase):
    """Vues : liste, création, génération manuelle, bascule statut."""

    def test_page_liste_charge(self):
        self._creer_plan(familles=[self.fam_med])
        resp = self.client.get(reverse('liste_plans_inventaire_tournant'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Rotation Trimestrielle')
        self.assertContains(resp, 'Inventaire Tournant')

    def test_page_liste_affiche_badge_echeance(self):
        plan = self._creer_plan(familles=[self.fam_med])
        plan.prochaine_echeance = timezone.now().date() - timezone.timedelta(days=1)
        plan.save()
        resp = self.client.get(reverse('liste_plans_inventaire_tournant'))
        self.assertContains(resp, 'Échue')

    def test_creation_plan_via_post(self):
        resp = self.client.post(reverse('liste_plans_inventaire_tournant'), {
            'titre': 'Rotation Mensuelle',
            'magasin_id': self.magasin.id,
            'type_rotation': 'PAR_FAMILLE',
            'frequence_jours': '30',
            'familles_ids': [self.fam_med.id, self.fam_mat.id],
        })
        self.assertEqual(resp.status_code, 302)
        plan = PlanInventaireTournant.objects.get(titre='Rotation Mensuelle')
        self.assertEqual(plan.frequence_jours, 30)
        self.assertEqual(plan.familles_cibles.count(), 2)
        self.assertEqual(plan.prochaine_echeance, timezone.now().date())

    def test_creation_plan_sans_titre_refuse(self):
        resp = self.client.post(reverse('liste_plans_inventaire_tournant'), {
            'magasin_id': self.magasin.id,
            'type_rotation': 'PAR_FAMILLE',
            'frequence_jours': '30',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(PlanInventaireTournant.objects.count(), 0)

    def test_creation_plan_frequence_invalide_refusee(self):
        resp = self.client.post(reverse('liste_plans_inventaire_tournant'), {
            'titre': 'Plan Invalide',
            'magasin_id': self.magasin.id,
            'type_rotation': 'PAR_FAMILLE',
            'frequence_jours': 'abc',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(PlanInventaireTournant.objects.count(), 0)

    def test_generation_manuelle_redirige_vers_saisie(self):
        plan = self._creer_plan(familles=[self.fam_med])
        resp = self.client.get(reverse('generer_campagne_tournante', args=[plan.id]))
        self.assertEqual(resp.status_code, 302)
        campagne = CampagneInventaire.objects.latest('id')
        self.assertEqual(campagne.lignes_inventaire.count(), 1)
        # Redirige vers la saisie de la campagne créée
        self.assertIn(f'/inventaires/{campagne.id}/saisir/', resp.url)

    def test_generation_plan_inactif_refusee(self):
        plan = self._creer_plan(familles=[self.fam_med], statut='INACTIF')
        resp = self.client.get(reverse('generer_campagne_tournante', args=[plan.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(CampagneInventaire.objects.count(), 0)

    def test_bascule_statut_actif_pause(self):
        plan = self._creer_plan(familles=[self.fam_med])
        resp = self.client.get(reverse('basculer_statut_plan', args=[plan.id]))
        self.assertEqual(resp.status_code, 302)
        plan.refresh_from_db()
        self.assertEqual(plan.statut, 'INACTIF')

        resp = self.client.get(reverse('basculer_statut_plan', args=[plan.id]))
        plan.refresh_from_db()
        self.assertEqual(plan.statut, 'ACTIF')

    def test_liste_filtree_par_magasin_actif(self):
        self._creer_plan(familles=[self.fam_med])
        plan_autre = PlanInventaireTournant.objects.create(
            titre='Plan Autre Magasin',
            magasin=self.autre_mag,
            cree_par=self.user,
        )
        resp = self.client.get(reverse('liste_plans_inventaire_tournant'))
        self.assertContains(resp, 'Rotation Trimestrielle')
        self.assertNotContains(resp, 'Plan Autre Magasin')
        self.assertIn(plan_autre.id, PlanInventaireTournant.objects.all().values_list('id', flat=True))

    def test_page_rendue_sans_plan(self):
        resp = self.client.get(reverse('liste_plans_inventaire_tournant'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Aucun plan')

    def test_creation_plan_sans_famille_avertit(self):
        resp = self.client.post(reverse('liste_plans_inventaire_tournant'), {
            'titre': 'Plan Sans Famille',
            'magasin_id': self.magasin.id,
            'type_rotation': 'PAR_FAMILLE',
            'frequence_jours': '60',
        })
        self.assertEqual(resp.status_code, 302)
        plan = PlanInventaireTournant.objects.get(titre='Plan Sans Famille')
        self.assertEqual(plan.familles_cibles.count(), 0)


class AutomatisationInventaireTournantTest(InventaireTournantBase):
    """Management command + génération à la connexion."""

    def _plan_echu(self, **kwargs):
        plan = self._creer_plan(familles=[self.fam_med], **kwargs)
        plan.prochaine_echeance = timezone.now().date() - timezone.timedelta(days=1)
        plan.save(update_fields=['prochaine_echeance'])
        return plan

    def test_command_generer_les_plans_echus(self):
        from io import StringIO
        from django.core.management import call_command

        self._plan_echu()
        self._plan_echu()
        plan_futur = self._creer_plan(familles=[self.fam_mat])
        plan_futur.prochaine_echeance = timezone.now().date() + timezone.timedelta(days=30)
        plan_futur.save(update_fields=['prochaine_echeance'])
        plan_pause = self._plan_echu(statut='INACTIF')

        out = StringIO()
        call_command('generer_inventaires_tournants', stdout=out)

        self.assertEqual(CampagneInventaire.objects.count(), 2)
        self.assertEqual(out.getvalue().count('✅'), 2)
        # Les plans échus ont vu leur échéance repoussée
        for plan in (plan_futur, plan_pause):
            plan.refresh_from_db()
        self.assertEqual(plan_futur.prochaine_echeance,
                         timezone.now().date() + timezone.timedelta(days=30))
        self.assertEqual(plan_pause.prochaine_echeance,
                         timezone.now().date() - timezone.timedelta(days=1))

    def test_command_dry_run_ne_genere_rien(self):
        from io import StringIO
        from django.core.management import call_command

        self._plan_echu()
        out = StringIO()
        call_command('generer_inventaires_tournants', dry_run=True, stdout=out)
        self.assertEqual(CampagneInventaire.objects.count(), 0)
        self.assertIn('dry-run', out.getvalue().lower())

    def test_command_sans_plan_echu_ne_genere_rien(self):
        from io import StringIO
        from django.core.management import call_command

        self._creer_plan(familles=[self.fam_med])  # échéance aujourd'hui = généré ?
        plan_futur = self._creer_plan(familles=[self.fam_mat])
        plan_futur.prochaine_echeance = timezone.now().date() + timezone.timedelta(days=15)
        plan_futur.save(update_fields=['prochaine_echeance'])

        out = StringIO()
        call_command('generer_inventaires_tournants', stdout=out)
        # Le plan avec échéance = aujourd'hui est bien considéré échu (<= aujourd'hui)
        self.assertEqual(CampagneInventaire.objects.count(), 1)

    def test_connexion_genere_les_plans_echus(self):
        # Déconnecter le client force_login du setUp pour tester le vrai login
        self.client.logout()
        self._plan_echu()
        resp = self.client.post(reverse('accounts:custom_login'), {
            'username': 'tournant',
            'password': 'tournant2026',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(CampagneInventaire.objects.count(), 1)

    def test_connexion_sans_plan_echu_ne_genere_rien(self):
        self.client.logout()
        plan = self._creer_plan(familles=[self.fam_med])
        plan.prochaine_echeance = timezone.now().date() + timezone.timedelta(days=10)
        plan.save(update_fields=['prochaine_echeance'])

        resp = self.client.post(reverse('accounts:custom_login'), {
            'username': 'tournant',
            'password': 'tournant2026',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(CampagneInventaire.objects.count(), 0)
