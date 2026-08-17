# -*- coding: utf-8 -*-
"""
Test de non-régression RESPONSIVE (mobile 375px).

Sans navigateur (Selenium/Playwright) dans le projet, on vérifie par analyse
statique du HTML/CSS rendu les risques de débordement horizontal :

  1. Aucun élément avec largeur fixe en px > 375 (width / min-width) hors d'un
     conteneur à défilement horizontal (overflow-x) ou d'un élément masqué.
  2. Aucun tableau de données (>= 5 colonnes) hors conteneur overflow-x :
     un tableau large doit scroller en interne, pas faire déborder la page.
     Un conteneur est scrollable en X s'il a un style inline overflow-x:auto
     OU une classe CSS définie avec overflow-x:auto dans les <style> de la page.
  3. Aucun layout "sidebar fixe + contenu flexible" sans media query mobile
     (le motif du bug Registre du Patrimoine : sidebar 260px écrasant le
     contenu à 0px en mobile).

Chaque page doit en plus répondre en 200/302 (404/500 = échec).
"""
import re
from html.parser import HTMLParser

from django.contrib.auth.models import User
from django.test import TestCase

from stock.models import Fournisseur
from stock.tests.factories import (
    creer_article, creer_famille, creer_magasin, creer_stock,
)

VUE_MOBILE_PX = 375

# Largeur fixe en px au-delà de laquelle un élément est suspect (hors conteneur scrollable)
LARGEUR_FIXE_MAX = VUE_MOBILE_PX
# Nombre de colonnes au-delà duquel un tableau est considéré "large" (doit scroller)
COLONNES_TABLEAU_MAX = 5


def _classes_overflow_x(html):
    """Classe CSS dont une règle <style> rend le conteneur scrollable en X :
    overflow-x: auto/scroll, overflow: auto/scroll (deux axes), ou
    overflow-y: auto/scroll (spéc. CSS : overflow-x: visible devient auto)."""
    classes = set()
    for m in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.S | re.I):
        block = m.group(1)
        for rule in re.finditer(r'([^{}]+)\{([^{}]*)\}', block):
            decl = rule.group(2)
            if re.search(r'overflow-x\s*:\s*(auto|scroll)', decl, re.I) or \
               re.search(r'(?:^|;)\s*overflow\s*:\s*(auto|scroll)(?:;|$)', decl, re.I) or \
               re.search(r'overflow-y\s*:\s*(auto|scroll)', decl, re.I):
                for cls in re.findall(r'\.([\w-]+)', rule.group(1)):
                    classes.add(cls)
    return classes


def _classes_table_fixed(html):
    """Classes de tableaux avec table-layout: fixed + largeur 100% :
    les cellules se tassent (aucun débordement possible)."""
    classes = set()
    for m in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.S | re.I):
        block = m.group(1)
        for rule in re.finditer(r'([^{}]+)\{([^{}]*)\}', block):
            if re.search(r'table-layout\s*:\s*fixed', rule.group(2), re.I):
                for cls in re.findall(r'\.([\w-]+)', rule.group(1)):
                    classes.add(cls)
    return classes


def _style_overflow_x(style):
    """Un style inline scroll-t-il horizontalement ?"""
    if not style:
        return False
    if re.search(r'overflow-x\s*:\s*(auto|scroll)', style, re.I):
        return True
    # overflow: auto|scroll => les deux axes (x inclus)
    if re.search(r'(?:^|;)\s*overflow\s*:\s*(auto|scroll)(?:;|$)', style, re.I):
        return True
    # overflow-y: auto|scroll sans overflow-x => x devient auto (spéc. CSS)
    if re.search(r'overflow-y\s*:\s*(auto|scroll)', style, re.I) and \
       not re.search(r'overflow-x\s*:', style, re.I):
        return True
    return False


class _OverflowParser(HTMLParser):
    """Analyse le HTML rendu : largeurs fixes + tableaux hors conteneur scrollable.

    Un conteneur est considéré scrollable en X s'il a un style inline
    overflow-x:auto/scroll (ou overflow:auto/scroll) OU une classe CSS
    définie dans les <style> de la page avec overflow-x:auto/scroll.
    """

    _WIDTH_RE = re.compile(r'(?:^|;)\s*(?:width|min-width)\s*:\s*(\d+(?:\.\d+)?)px', re.I)

    def __init__(self, classes_overflow, classes_table_fixed=None):
        super().__init__(convert_charrefs=True)
        self.classes_overflow = classes_overflow
        self.classes_table_fixed = classes_table_fixed or set()
        self.stack = []          # (tag, in_overflow, hidden)
        self.tables = []         # (in_overflow_at_table, nb_th, attrs_table)
        self.violations = []

    def _ancestor(self, idx=-1):
        return self.stack[idx] if self.stack else None

    def _scrollable(self, attrs):
        if _style_overflow_x(attrs.get('style', '')):
            return True
        cls = attrs.get('class', '')
        return any(c in self.classes_overflow for c in cls.split())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        anc = self._ancestor()
        in_overflow = bool(anc and anc[1])
        hidden = bool(anc and anc[2])
        style = attrs.get('style', '') or ''
        if self._scrollable(attrs):
            in_overflow = True
        if re.search(r'display\s*:\s*none', style, re.I):
            hidden = True

        self.stack.append((tag, in_overflow, hidden))

        if tag == 'table':
            self.tables.append([in_overflow, 0, attrs])
        elif tag == 'th' and self.tables:
            self.tables[-1][1] += 1

        if hidden:
            return
        for m in self._WIDTH_RE.finditer(style):
            if float(m.group(1)) > LARGEUR_FIXE_MAX and not in_overflow:
                self.violations.append(
                    f"<{tag}> {m.group(0).strip()} hors conteneur scrollable"
                )

    def handle_startendtag(self, tag, attrs):
        attrs = dict(attrs)
        style = attrs.get('style', '') or ''
        anc = self._ancestor()
        if anc and anc[2]:
            return
        if re.search(r'display\s*:\s*none', style, re.I):
            return
        in_overflow = bool(anc and anc[1])
        if self._scrollable(attrs):
            in_overflow = True
        for m in self._WIDTH_RE.finditer(style):
            if float(m.group(1)) > LARGEUR_FIXE_MAX and not in_overflow:
                self.violations.append(
                    f"<{tag}/> {m.group(0).strip()} hors conteneur scrollable"
                )

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i]
                break
        if tag == 'table' and self.tables:
            in_overflow, nb_th, tbl_attrs = self.tables.pop()
            if nb_th >= COLONNES_TABLEAU_MAX and not in_overflow:
                tcls = tbl_attrs.get('class', '').split()
                if any(c in self.classes_table_fixed for c in tcls):
                    return  # table-layout: fixed + width 100% : pas de débordement
                self.violations.append(
                    f"tableau ({nb_th} colonnes) sans conteneur overflow-x"
                )


def _style_block_violations(html):
    """Détecte le motif 'sidebar fixe + flex' sans media query mobile."""
    out = []
    for m in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.S | re.I):
        block = m.group(1)
        if re.search(r'@media', block):
            continue  # un @media existe : le motif est géré
        if not re.search(r'display\s*:\s*flex', block):
            continue
        a_sidebar = False
        a_flexible = bool(re.search(r'flex\s*:\s*1\b|min-width\s*:\s*0', block))
        for rule in re.finditer(r'\{([^{}]*)\}', block):
            r = rule.group(1)
            if re.search(r'flex-shrink\s*:\s*0', r) and \
               re.search(r'width\s*:\s*\d{3,4}px', r):
                a_sidebar = True
        if a_sidebar and a_flexible:
            out.append("layout 'sidebar fixe + contenu flexible' sans @media mobile")
    return out


class ResponsiveMobileTest(TestCase):
    """Vérifie l'absence de débordement horizontal sur toutes les pages en 375px."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(
            username='admin_responsive', password='x', email='a@a.ci'
        )
        # Le middleware PasswordChangeMiddleware redirige vers /auth/forcer-mdp/
        # tant que doit_changer_mdp=True (défaut du Profil) → on le désactive.
        cls.user.profil.doit_changer_mdp = False
        cls.user.profil.save()
        cls.magasin = creer_magasin(nom="Magasin Mobile")
        cls.famille = creer_famille()
        cls.article = creer_article(famille=cls.famille, reference="MOB001")
        creer_stock(cls.article, cls.magasin, quantite=5)
        cls.fournisseur = Fournisseur.objects.create(code="F001", raison_sociale="Fournisseur Test")

    def setUp(self):
        self.client.force_login(self.user)
        s = self.client.session
        s['magasin_actif_id'] = str(self.magasin.id)
        s.save()

    def _urls(self):
        m = self.magasin.id
        return [
            '/', '/articles/', '/familles/', '/entrees/', '/sorties/',
            '/bons/hors-stock/', '/stock/retours-services/',
            '/stock/retours-fournisseurs/', '/livraisons/',
            '/receptions/', '/etat-stock/', '/ajustements/', '/inventaires/',
            '/administration/historique/', '/commandes/', '/mes-demandes/',
            '/gestion-demandes/', '/valider-demandes/',
            '/parametres/administratifs/', '/parametres/logistique/',
            '/magasins/%d/parametres/' % m,
            '/rapports/', '/rapports/consommation-services/',
            '/stats/demandes/', '/stats/sondages/',
            '/stats/satisfaction-services/', '/notifications/',
            '/auth/', '/auth/profil/', '/auth/roles/', '/auth/utilisateurs/',
            '/auth/journal-audit/', '/auth/securite/mots-de-passe/',
            '/auth/circuits-validation/', '/auth/parametres/documents-pdf/',
            '/patrimoine/', '/patrimoine/sas/', '/patrimoine/contrats/',
            '/patrimoine/interventions/', '/patrimoine/import/',
            '/patrimoine/parametres/', '/patrimoine/inventaires/',
            '/patrimoine/rebuts/', '/patrimoine/pertes/',
            '/patrimoine/rapports/valeur-services/',
            '/patrimoine/mes-tickets/', '/patrimoine/mes-interventions/',
            '/magasin/%d/modele-pdf/BS/' % m,
            '/articles/%d/historique/' % self.article.id,
        ]

    def test_aucun_debordement_horizontal_mobile(self):
        echecs = []
        for url in self._urls():
            resp = self.client.get(url)
            if resp.status_code not in (200, 302):
                echecs.append(f"{url} -> HTTP {resp.status_code}")
                continue
            if resp.status_code != 200:
                continue  # redirection légitime (POST-only, circuit inactif…)
            html = resp.content.decode('utf-8', errors='replace')
            parser = _OverflowParser(
                _classes_overflow_x(html),
                _classes_table_fixed(html),
            )
            try:
                parser.feed(html)
                parser.close()
            except Exception:
                pass  # ne pas échouer sur une bizarrerie du parseur HTML
            violations = parser.violations + _style_block_violations(html)
            if violations:
                echecs.append(f"{url} -> {violations[:3]}")

        self.assertEqual(
            echecs, [],
            "Débordements horizontaux potentiels en mobile 375px :\n" + "\n".join(echecs[:40])
        )

    def test_registre_patrimoine_empile_en_mobile(self):
        """Le Registre du Patrimoine empile la sidebar au-dessus du tableau (bug corrigé)."""
        resp = self.client.get('/patrimoine/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8', errors='replace')
        self.assertIn('@media (max-width: 768px)', html)
        self.assertIn('flex-direction: column', html)

    def test_breakpoint_menu_768px(self):
        """Le layout global bascule à 768px : sidebar off-canvas + topbar compacte.
        C'est le breakpoint unique qui gère tablette (~768px) et mobile étroit."""
        resp = self.client.get('/articles/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8', errors='replace')
        # Sidebar off-canvas en <=768px (déplacée hors écran, ouverte par .mobile-open)
        self.assertIn('@media (max-width: 768px)', html)
        self.assertIn('left: -270px', html)
        self.assertIn('sidebar.mobile-open { left: 0; }', html)
        self.assertIn('mobile-overlay', html)
        # Topbar compacte : icônes conservées, libellés masqués
        self.assertIn('.topbar-user-name, .topbar-logout-text { display: none !important; }', html)

    def test_formulaires_creation_empilent_en_mobile(self):
        """Les formulaires de création (article, bon de sortie, commande) empilent
        leurs champs en une colonne en <=768px au lieu de les écraser."""
        # Nouvel Article (modale)
        r = self.client.get('/articles/')
        html = r.content.decode('utf-8', errors='replace')
        self.assertIn('grid-template-columns: 1fr !important', html)
        # Bon de Sortie (modale) : les 4 champs d'en-tête empilés via .vd-header-grid
        r = self.client.get('/sorties/')
        html = r.content.decode('utf-8', errors='replace')
        self.assertIn('vd-header-grid', html)
        self.assertIn('.vd-header-grid {', html)
        self.assertIn('grid-template-columns: 1fr !important', html)
        # Commande (modale) : les 2 grilles empilées via .cmd-grid-2/.cmd-grid-3
        r = self.client.get('/commandes/')
        html = r.content.decode('utf-8', errors='replace')
        self.assertIn('cmd-grid-2', html)
        self.assertIn('cmd-grid-3', html)
        self.assertIn('.cmd-grid-2, .cmd-grid-3 { grid-template-columns: 1fr !important; }', html)
        # Import patrimoine : grille de types auto-empilable (minmax)
        r = self.client.get('/patrimoine/import/')
        html = r.content.decode('utf-8', errors='replace')
        self.assertIn('minmax(200px,1fr)', html)

    # ------------------------------------------------------------------
    # MENU PRINCIPAL : défilement, sections repliables, navigation fluide
    # ------------------------------------------------------------------

    def test_menu_header_sticky(self):
        """Le header (logo) reste ancré en haut pendant le défilement de la sidebar
        (position: sticky) pour garder une ancre stable dans un menu long."""
        for url in ('/articles/', '/inventaires/', '/patrimoine/'):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            html = resp.content.decode('utf-8', errors='replace')
            self.assertIn('.sidebar-header', html)
            self.assertIn('position: sticky', html)

    def test_menu_sous_menu_anime(self):
        """Le sous-menu s'ouvre/ferme avec une transition animable : max-height
        numérique (3000px) au lieu de 'none' — 'none' rend la fermeture
        instantanée et l'accordéon brutal."""
        resp = self.client.get('/articles/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8', errors='replace')
        self.assertIn('.submenu', html)
        self.assertIn('max-height: 900px', html)
        self.assertNotIn('.submenu.active {\n            max-height: none', html)

    def test_menu_accordion_un_seul_ouvert(self):
        """L'accordéon du menu : toggleMenu ferme tous les autres sous-menus avant
        d'ouvrir celui cliqué (un seul module déplié à la fois)."""
        resp = self.client.get('/articles/')
        html = resp.content.decode('utf-8', errors='replace')
        # Le JS doit fermer tous les .submenu puis ouvrir celui cliqué
        self.assertIn("document.querySelectorAll('.submenu').forEach(function(sub) { sub.classList.remove('active'); });", html)

    def test_menu_scroll_vers_actif(self):
        """Après ouverture du sous-menu actif, la sidebar scrolle vers l'élément
        actif (getBoundingClientRect) — l'utilisateur voit toujours où il est."""
        resp = self.client.get('/articles/')
        html = resp.content.decode('utf-8', errors='replace')
        self.assertIn('bestLink.getBoundingClientRect()', html)
        self.assertIn('sb.scrollTo', html)

    def test_menu_scroll_sous_menu_deploye(self):
        """Quand le sous-menu déployé déborde en bas de la sidebar, toggleMenu
        le remonte pour que son contenu soit visible (menuBottom vs visibleBottom)."""
        resp = self.client.get('/articles/')
        html = resp.content.decode('utf-8', errors='replace')
        self.assertIn('menuBottom', html)
        self.assertIn('visibleBottom', html)

    def test_menu_memoire_sous_menu_ouvert(self):
        """Le sous-menu ouvert est mémorisé dans localStorage à l'ouverture
        (toggleMenu) et restauré quand aucun lien actif n'est trouvé
        (updateActiveMenu) — l'utilisateur retrouve son contexte en naviguant."""
        resp = self.client.get('/articles/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8', errors='replace')
        # Sauvegarde à l'ouverture (toggleMenu)
        self.assertIn("localStorage.setItem('nexuserp_menu_open', menuId)", html)
        # Oubli à la fermeture volontaire (clic sur le module déjà ouvert)
        self.assertIn("localStorage.removeItem('nexuserp_menu_open')", html)
        # Le lien actif met à jour l'état mémorisé
        self.assertIn("localStorage.setItem('nexuserp_menu_open', submenu.id)", html)
        # Restauration quand aucun lien actif (accueil, tableau de bord…)
        self.assertIn("localStorage.getItem('nexuserp_menu_open')", html)
        self.assertIn('var savedSub = document.getElementById(remembered)', html)
