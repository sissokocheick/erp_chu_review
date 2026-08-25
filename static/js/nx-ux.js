/**
 * NexusERP — Design System UX (Version 2.0 - Standardisée)
 * Fichier : static/js/nx-ux.js
 *
 * Dépendances : SweetAlert2, Select2 (optionnel)
 *
 * Usage standardisé dans tous les modules :
 *   NxUX.toast('success', 'Enregistré avec succès');
 *   NxUX.confirm({ title: '...', onConfirm: () => {...} });
 *   NxUX.loading(btn); NxUX.stopLoading(btn);
 *   NxUX.formatField(input); // Applique le masque (téléphone, email, etc.)
 *   NxUX.handleError(error, 'Action échouée');
 */

window.NxUX = (function () {
  'use strict';

  /**
   * Affiche une notification toast non bloquante
   * @param {string} type - 'success', 'error', 'warning', 'info'
   * @param {string} message - Texte à afficher
   * @param {number} timer - Durée en ms (défaut 3500)
   */
  function toast(type, message, timer) {
    var map = {
      success: { icon: 'success' },
      error:   { icon: 'error' },
      warning: { icon: 'warning' },
      info:    { icon: 'info' }
    };
    var cfg = map[type] || map.info;
    var isDark = document.body && document.body.classList.contains('dark-mode');

    Swal.fire({
      toast: true,
      position: 'top-end',
      icon: cfg.icon,
      title: message,
      showConfirmButton: false,
      timer: timer || 3500,
      timerProgressBar: true,
      background: isDark ? '#1e293b' : '#fff',
      color: isDark ? '#f1f5f9' : '#333',
      didOpen: function (toast) {
        toast.addEventListener('mouseenter', Swal.stopTimer);
        toast.addEventListener('mouseleave', Swal.resumeTimer);
      }
    });
  }

  /**
   * Affiche une modale de confirmation
   * @param {Object} options - { title, text, icon, confirmText, cancelText, onConfirm, onCancel }
   * @returns {Promise}
   */
  function confirm(options) {
    options = options || {};
    return Swal.fire({
      title: options.title || 'Confirmer',
      text: options.text || '',
      icon: options.icon || 'question',
      showCancelButton: true,
      confirmButtonColor: options.confirmColor || '#1c5b96',
      cancelButtonColor: options.cancelColor || '#6c757d',
      confirmButtonText: options.confirmText || 'Oui',
      cancelButtonText: options.cancelText || 'Annuler',
      reverseButtons: true,
      focusCancel: true,
      backdrop: 'rgba(0,0,0,0.5)'
    }).then(function (result) {
      if (result.isConfirmed && typeof options.onConfirm === 'function') {
        options.onConfirm();
      } else if (result.isDismissed && typeof options.onCancel === 'function') {
        options.onCancel();
      }
      return result;
    });
  }

  /**
   * Raccourci pour confirmation de suppression
   */
  function confirmDelete(message, onConfirm) {
    return confirm({
      title: 'Confirmer la suppression',
      text: message || 'Cette action est irréversible.',
      icon: 'warning',
      confirmText: '<i class="fas fa-trash-alt"></i> Supprimer',
      confirmColor: '#dc3545',
      onConfirm: onConfirm
    });
  }

  /**
   * Active l'état de chargement sur un bouton
   * @param {HTMLElement} btn - Le bouton HTML
   * @param {string} text - Texte optionnel (défaut: "Chargement...")
   */
  function loading(btn, text) {
    if (!btn) return;
    btn.disabled = true;
    btn.dataset.nxOriginalHtml = btn.innerHTML;
    btn.classList.add('nx-loading');
    
    var spinner = '<span class="nx-spinner"></span>';
    var label = text || 'Chargement…';
    
    btn.innerHTML = spinner + label;
  }

  /**
   * Désactive l'état de chargement sur un bouton
   * @param {HTMLElement} btn - Le bouton HTML
   */
  function stopLoading(btn) {
    if (!btn) return;
    btn.disabled = false;
    btn.classList.remove('nx-loading');
    if (btn.dataset.nxOriginalHtml) {
      btn.innerHTML = btn.dataset.nxOriginalHtml;
      delete btn.dataset.nxOriginalHtml;
    }
  }

  /**
   * Affiche/masque un état de chargement sur un conteneur de tableau
   * (overlay spinner centré) pendant une recherche AJAX.
   * @param {HTMLElement} container - Le conteneur du tableau (table-card…)
   * @param {boolean} on - true = afficher, false = masquer
   */
  function setTableLoading(container, on) {
    if (!container) return;
    var overlay = container.querySelector('.nx-table-loading');
    if (on) {
      if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'nx-table-loading';
        overlay.innerHTML = '<span class="nx-spinner"></span><span class="nx-table-loading-label">Chargement…</span>';
        container.appendChild(overlay);
      }
      overlay.style.display = 'flex';
    } else if (overlay) {
      overlay.style.display = 'none';
    }
  }

  /**
   * Applique un formatage spécifique à un champ input
   * Détecte automatiquement le type via data-nx-format ou le pattern
   * @param {HTMLElement} input - L'élément input
   */
  function formatField(input) {
    if (!input) return;
    
    var formatType = input.dataset.nxFormat;
    var value = input.value || '';

    if (!formatType) {
      if (input.type === 'tel' || input.placeholder.includes('Tél')) formatType = 'phone';
      else if (input.type === 'email') formatType = 'email';
      else if (input.dataset.nxMask) formatType = 'mask';
    }

    if (formatType === 'phone') {
      // Format telephone CI : 01 02 03 04 05 (10 chiffres, groupes de 2)
      value = value.replace(/\D/g, '').substring(0, 10);
      if (value.length > 2) {
        value = value.match(/.{1,2}/g).join(' ');
      }
      input.value = value;
    } 
    else if (formatType === 'email') {
      input.value = value.toLowerCase().trim();
    }
    else if (formatType === 'uppercase') {
      input.value = value.toUpperCase();
    }
    else if (formatType === 'capitalize') {
      input.value = value.replace(/\b\w/g, l => l.toUpperCase());
    }
  }

  /**
   * Initialise tous les champs avec data-nx-format dans un conteneur
   * @param {HTMLElement|string} container - Sélecteur ou élément DOM
   */
  function initFormatting(container) {
    var root = typeof container === 'string' ? document.querySelector(container) : container;
    if (!root) root = document;
    
    var inputs = root.querySelectorAll('[data-nx-format], input[type="tel"], input[type="email"]');
    inputs.forEach(function(input) {
      formatField(input);
      input.addEventListener('blur', function() { formatField(input); });
      input.addEventListener('input', function() { 
        // Formatage en temps réel pour le téléphone uniquement pour éviter d'être intrusif
        if (input.dataset.nxFormat === 'phone' || input.type === 'tel') {
          formatField(input);
        }
      });
    });
  }

  /**
   * Gestionnaire d'erreur standardisé pour les requêtes Fetch/AJAX
   * @param {Error|Response} error - L'erreur ou la réponse
   * @param {string} defaultMessage - Message par défaut si l'erreur est muette
   */
  function handleError(error, defaultMessage) {
    console.error('NxUX Error:', error);
    
    var msg = defaultMessage || 'Une erreur inattendue est survenue.';
    
    if (error && error.message) {
      msg = error.message;
    } else if (error && error.statusText) {
      msg = 'Erreur serveur : ' + error.statusText;
    } else if (typeof error === 'string') {
      msg = error;
    }

    toast('error', msg);
  }

  /**
   * Sélectionne une option dans un Select2 et ouvre le dropdown
   * Utile pour les workflows guidés
   * @param {string} selector - Sélecteur jQuery/JS du select
   * @param {string} value - Valeur à sélectionner
   */
  function selectAndOpen(selector, value) {
    try {
      var $select = $(selector);
      if ($select.length && $.fn.select2) {
        $select.val(value).trigger('change');
        $select.select2('open');
      }
    } catch (e) {
      console.warn('Select2 not available or selector invalid', e);
    }
  }

  /**
   * Injecte le CSS nécessaire pour les spinners et états de chargement
   */
  (function injectSpinnerCSS() {
    if (document.getElementById('nx-ux-style')) return;
    var style = document.createElement('style');
    style.id = 'nx-ux-style';
    style.textContent = `
      @keyframes nxSpin { to { transform: rotate(360deg); } }
      .nx-spinner {
        display: inline-block;
        width: 14px;
        height: 14px;
        border: 2px solid rgba(255,255,255,0.3);
        border-top-color: #fff;
        border-radius: 50%;
        animation: nxSpin 0.7s linear infinite;
        vertical-align: middle;
        margin-right: 6px;
      }
      .nx-loading {
        opacity: 0.8;
        cursor: not-allowed;
        position: relative;
        pointer-events: none;
      }
      .nx-loading::after {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0,0,0,0.1);
        border-radius: inherit;
      }
      .nx-table-loading {
        position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        background: rgba(248,250,252,0.72);
        backdrop-filter: blur(1px);
        z-index: 20;
        border-radius: inherit;
        font-size: 13px;
        font-weight: 600;
        color: var(--text-medium, #475569);
        pointer-events: none;
      }
      body.dark-mode .nx-table-loading {
        background: rgba(15,23,42,0.72);
      }
      .nx-table-loading .nx-spinner {
        width: 18px;
        height: 18px;
        border-color: rgba(17,122,139,0.3);
        border-top-color: #117a8b;
      }
    `;
    document.head.appendChild(style);
  })();

  /**
   * Soumet un formulaire avec confirmation préalable
   * @param {HTMLFormElement} form - Le formulaire
   * @param {Object} options - Options de confirmation et de chargement
   */
  function submitWithConfirm(form, options) {
    options = options || {};
    confirm({
      title: options.title || 'Confirmer ?',
      text: options.text || '',
      icon: options.icon || 'question',
      confirmText: options.confirmText || 'Oui, enregistrer',
      confirmColor: options.confirmColor || '#1c5b96',
      onConfirm: function () {
        var btn = options.btn || form.querySelector('[type=submit], .btn-save, .nx-btn-primary');
        if (btn) loading(btn, options.loadingText || 'Enregistrement…');
        form.submit();
      }
    });
  }

  return {
    toast: toast,
    confirm: confirm,
    confirmDelete: confirmDelete,
    loading: loading,
    stopLoading: stopLoading,
    setTableLoading: setTableLoading,
    formatField: formatField,
    initFormatting: initFormatting,
    handleError: handleError,
    selectAndOpen: selectAndOpen,
    submitWithConfirm: submitWithConfirm
  };
})();
