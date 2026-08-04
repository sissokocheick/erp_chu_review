/**
 * NexusERP — Design System UX
 * Fichier : static/js/nx-ux.js
 *
 * Dépendances : SweetAlert2 (déjà chargé dans base_ui.html)
 *
 * Usage :
 *   NxUX.toast('success', 'Enregistré avec succès');
 *   NxUX.toast('error', 'Une erreur est survenue');
 *   NxUX.confirm({ title: '...', text: '...', onConfirm: () => form.submit() });
 *   NxUX.loading(btn);  NxUX.stopLoading(btn);
 */

window.NxUX = (function () {
  'use strict';

  function toast(type, message, timer) {
    var map = {
      success: { icon: 'success' },
      error:   { icon: 'error' },
      warning: { icon: 'warning' },
      info:    { icon: 'info' }
    };
    var cfg = map[type] || map.info;
    var isDark = document.body.classList.contains('dark-mode');

    Swal.fire({
      toast: true,
      position: 'top-end',
      icon: cfg.icon,
      title: message,
      showConfirmButton: false,
      timer: timer || 3500,
      timerProgressBar: true,
      background: isDark ? '#1e293b' : '#fff',
      color: isDark ? '#f1f5f9' : '#333'
    });
  }

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
      focusCancel: true
    }).then(function (result) {
      if (result.isConfirmed && typeof options.onConfirm === 'function') {
        options.onConfirm();
      }
      return result;
    });
  }

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

  function loading(btn, text) {
    if (!btn) return;
    btn.disabled = true;
    btn.dataset.nxOriginalHtml = btn.innerHTML;
    btn.innerHTML =
      '<span style="display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:nxSpin .7s linear infinite;vertical-align:middle;margin-right:6px;"></span>' +
      (text || 'Chargement…');
  }

  function stopLoading(btn) {
    if (!btn) return;
    btn.disabled = false;
    if (btn.dataset.nxOriginalHtml) {
      btn.innerHTML = btn.dataset.nxOriginalHtml;
      delete btn.dataset.nxOriginalHtml;
    }
  }

  (function injectSpinnerCSS() {
    if (document.getElementById('nx-ux-style')) return;
    var style = document.createElement('style');
    style.id = 'nx-ux-style';
    style.textContent = '@keyframes nxSpin{to{transform:rotate(360deg)}}';
    document.head.appendChild(style);
  })();

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
    submitWithConfirm: submitWithConfirm
  };
})();
