# core/pdf_chromium.py — CORRIGÉ (v2)
"""
Service de generation PDF avec Playwright + Chromium.
CORRECTIONS P0 (v2):
  • asyncio.Semaphore sans paramètre loop (déprécié Python 3.8+, supprimé 3.10+)
  • Pool de navigateurs via asyncio.Queue au lieu de list.pop(0)
  • Browser corrompu remplacé, jamais remis dans le pool
  • _ensure_loop thread-safe avec lock
  • Timeout sur _init (asyncio.wait_for)
  • _init_lock créé lazy dans _init() (pas dans __init__)
  • SSRF bloqué via context.route() (interdit tout sauf data:)
  • Tracking des browsers in-flight pour _close propre
"""

import asyncio
import atexit
import logging
import threading
from typing import Optional, Set

logger = logging.getLogger(__name__)

PDF_FORMAT = 'A4'
PDF_MARGINS = {
    'top': '10mm',
    'right': '10mm',
    'bottom': '10mm',
    'left': '10mm',
}
PDF_PRINT_OPTIONS = {
    'format': PDF_FORMAT,
    'margin': PDF_MARGINS,
    'print_background': True,
    'prefer_css_page_size': True,
}

MAX_BROWSER_POOL = 3
INIT_TIMEOUT_SECONDS = 30


class ChromiumPDFGenerator:
    """Generateur de PDF via Playwright + Chromium (pool thread-safe avec Queue)."""

    def __init__(self, pool_size: int = MAX_BROWSER_POOL):
        self._playwright = None
        self._pool_size = pool_size
        self._initialized = False
        self._init_lock = None          # ✅ CORRECTION P0 (v2): créé lazy dans _init()
        self._loop_lock = threading.Lock()
        self._loop = None
        self._thread = None
        self._semaphore = None
        self._browser_queue = None
        # ✅ CORRECTION P0 (v2): Tracker les browsers en cours d'utilisation
        self._browsers_in_flight: Set = set()
        self._in_flight_lock = threading.Lock()

    def _ensure_loop(self):
        """Crée un thread dédié avec sa propre event loop persistante (thread-safe)."""
        with self._loop_lock:
            if self._loop is not None:
                return

            self._loop = asyncio.new_event_loop()
            self._semaphore = asyncio.Semaphore(self._pool_size)
            self._browser_queue = asyncio.Queue()
            self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
            self._thread.start()
            logger.info("[ChromiumPDF] Thread dédié démarré")

    async def _init(self):
        """
        Initialise Playwright et le pool de navigateurs (lazy, thread-safe).
        ✅ CORRECTION P0 (v2): _init_lock créé ici (lazy) pour être lié à la bonne boucle.
        """
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()

        async with self._init_lock:
            if self._initialized:
                return
            try:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()
                for i in range(self._pool_size):
                    browser = await self._playwright.chromium.launch(
                        headless=True,
                        args=[
                            '--no-sandbox',
                            '--disable-gpu',
                            '--disable-dev-shm-usage',
                            '--disable-web-security',
                        ]
                    )
                    await self._browser_queue.put(browser)
                self._initialized = True
                logger.info(f"[ChromiumPDF] Pool de {self._pool_size} navigateurs initialise")
            except ImportError:
                raise ImportError(
                    "Playwright n'est pas installe. "
                    "Executez: pip install playwright && playwright install chromium"
                )

    async def _close(self):
        """
        Ferme le pool de navigateurs et Playwright.
        ✅ CORRECTION P0 (v2): Attendre que tous les browsers in-flight soient rendus.
        """
        # Attendre que les browsers en cours d'utilisation soient rendus
        for _ in range(60):  # 60 x 0.5s = 30s max d'attente
            with self._in_flight_lock:
                if len(self._browsers_in_flight) == 0:
                    break
            await asyncio.sleep(0.5)
        else:
            logger.warning(
                f"[ChromiumPDF] {len(self._browsers_in_flight)} browsers encore "
                f"en vol après timeout — fermeture forcée"
            )

        # Vider la queue et fermer tous les navigateurs
        browsers_to_close = []
        while not self._browser_queue.empty():
            try:
                browser = self._browser_queue.get_nowait()
                browsers_to_close.append(browser)
            except asyncio.QueueEmpty:
                break

        for browser in browsers_to_close:
            try:
                await browser.close()
            except Exception as e:
                logger.warning(f"[ChromiumPDF] Erreur fermeture navigateur: {e}")

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._initialized = False
        logger.info("[ChromiumPDF] Pool ferme")

    async def html_to_pdf_async(self, html_string: str) -> bytes:
        """
        Convertit une chaine HTML en PDF (async).
        ✅ CORRECTION P0 (v2): SSRF bloqué via context.route().
        """
        # ✅ CORRECTION P0 (v2): Timeout sur _init
        try:
            await asyncio.wait_for(self._init(), timeout=INIT_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.critical(f"[ChromiumPDF] _init timeout après {INIT_TIMEOUT_SECONDS}s")
            raise RuntimeError(f"Initialisation Chromium timeout ({INIT_TIMEOUT_SECONDS}s)")

        async with self._semaphore:
            browser = None
            browser_corrupted = False
            try:
                browser = await self._browser_queue.get()
                # ✅ CORRECTION P0 (v2): Tracker le browser in-flight
                with self._in_flight_lock:
                    self._browsers_in_flight.add(id(browser))

                context = await browser.new_context()

                # ✅ CORRECTION P0 (v2): Bloquer TOUTES les requêtes réseau sauf data:
                # pour empêcher SSRF interne
                async def block_route(route, request):
                    url = request.url
                    if url.startswith('data:'):
                        await route.continue_()
                    else:
                        logger.warning(f"[ChromiumPDF] Requête réseau bloquée (SSRF): {url}")
                        await route.abort()

                await context.route("**/*", block_route)

                page = await context.new_page()
                try:
                    await page.set_content(html_string, wait_until='domcontentloaded')
                    await page.wait_for_timeout(500)
                    pdf_bytes = await page.pdf(**PDF_PRINT_OPTIONS, timeout=30000)
                    logger.debug(f"[ChromiumPDF] PDF genere: {len(pdf_bytes)} octets")
                    return pdf_bytes
                finally:
                    await page.close()
                    await context.close()
            except Exception as e:
                logger.error(f"[ChromiumPDF] Erreur génération PDF: {e}")
                browser_corrupted = True
                if browser:
                    try:
                        await browser.close()
                    except:
                        pass
                    try:
                        new_browser = await self._playwright.chromium.launch(
                            headless=True,
                            args=[
                                '--no-sandbox',
                                '--disable-gpu',
                                '--disable-dev-shm-usage',
                                '--disable-web-security',
                            ]
                        )
                        await self._browser_queue.put(new_browser)
                        logger.info("[ChromiumPDF] Navigateur corrompu remplace")
                    except Exception as e2:
                        logger.critical(f"[ChromiumPDF] Impossible de recréer navigateur: {e2}")
                        self._initialized = False
                raise
            finally:
                if browser:
                    # ✅ CORRECTION P0 (v2): Retirer du tracking in-flight
                    with self._in_flight_lock:
                        self._browsers_in_flight.discard(id(browser))
                    # Remettre dans le pool UNIQUEMENT si pas corrompu
                    if not browser_corrupted:
                        await self._browser_queue.put(browser)

    def html_to_pdf(self, html_string: str) -> bytes:
        """Convertit une chaine HTML en PDF (sync, thread-safe)."""
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            self.html_to_pdf_async(html_string), self._loop
        )
        return future.result(timeout=60)

    def close(self):
        """Ferme explicitement le pool de navigateurs."""
        with self._loop_lock:
            if self._initialized and self._loop:
                future = asyncio.run_coroutine_threadsafe(self._close(), self._loop)
                try:
                    future.result(timeout=10)
                except Exception as e:
                    logger.warning(f"[ChromiumPDF] Erreur fermeture: {e}")
            if self._loop:
                self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread:
                self._thread.join(timeout=5)

    def __del__(self):
        """Nettoyage a la destruction."""
        try:
            self.close()
        except Exception:
            pass


_chromium_generator = None
_generator_lock = threading.Lock()


def get_chromium_generator() -> ChromiumPDFGenerator:
    """Retourne l'instance singleton du generateur (thread-safe)."""
    global _chromium_generator
    with _generator_lock:
        if _chromium_generator is None:
            _chromium_generator = ChromiumPDFGenerator()
    return _chromium_generator


def _cleanup_chromium():
    """Ferme proprement Chromium a l'arret de l'application."""
    global _chromium_generator
    if _chromium_generator:
        try:
            _chromium_generator.close()
        except Exception:
            pass
        _chromium_generator = None

atexit.register(_cleanup_chromium)


def html_to_pdf(html_string: str) -> bytes:
    """Fonction de convenance pour generer un PDF depuis du HTML."""
    gen = get_chromium_generator()
    return gen.html_to_pdf(html_string)


def render_template_to_pdf(template_name: str, context: dict, request=None) -> bytes:
    """Rend un template Django et genere un PDF."""
    from django.template.loader import render_to_string
    html_string = render_to_string(template_name, context, request=request)
    return html_to_pdf(html_string)
