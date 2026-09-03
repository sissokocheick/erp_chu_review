// ================================================================
//  NexusERP — Modales de confirmation SweetAlert2
//  Utilisation : appelé depuis les onclick des boutons d'action
// ================================================================

/**
 * Confirme l'annulation d'une demande (véhicule ou salle)
 * @param {string} url - URL de redirection après confirmation
 * @param {string} type - 'vehicule' ou 'salle'
 */
function confirmerAnnulation(url, type) {
    const icon = type === 'vehicule' ? '🚗' : '🚪';
    const label = type === 'vehicule' ? 'véhicule' : 'salle';
    Swal.fire({
        title: 'Annuler la demande ?',
        html: `<div style="text-align:left;">
            <p style="margin:0 0 8px;">${icon} Vous êtes sur le point d'annuler votre demande de <strong>${label}</strong>.</p>
            <p style="margin:0;font-size:12px;color:#94a3b8;">Cette action est irréversible.</p>
        </div>`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#dc3545',
        cancelButtonColor: '#6c757d',
        confirmButtonText: '<i class="fas fa-times"></i> Oui, annuler',
        cancelButtonText: '<i class="fas fa-arrow-left"></i> Non, garder',
        reverseButtons: true,
        focusCancel: true
    }).then((result) => {
        if (result.isConfirmed) {
            // Soumission en POST (les actions destructrices refusent le GET)
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = url;

            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                              document.cookie.match(/csrftoken=([^;]+)/)?.[1];
            if (csrfToken) {
                const csrfInput = document.createElement('input');
                csrfInput.type = 'hidden';
                csrfInput.name = 'csrfmiddlewaretoken';
                csrfInput.value = csrfToken;
                form.appendChild(csrfInput);
            }

            document.body.appendChild(form);
            form.submit();
        }
    });
    return false;
}

/**
 * Confirme la soumission d'une demande (véhicule ou salle)
 * @param {HTMLFormElement} form - Le formulaire à soumettre
 * @param {string} type - 'vehicule' ou 'salle'
 */
function confirmerSoumission(form, type) {
    const icon = type === 'vehicule' ? '🚗' : '🚪';
    const label = type === 'vehicule' ? 'véhicule' : 'salle';
    const objet = form.querySelector('[name="objet"]')?.value || '';
    const submitBtn = form.querySelector('[type="submit"]');
    
    Swal.fire({
        title: `Envoyer la demande de ${label} ?`,
        html: `<div style="text-align:left;">
            <div style="background:#f8f9fa;border-radius:8px;padding:12px;margin-bottom:8px;">
                <div style="font-size:12px;color:#6c757d;margin-bottom:4px;">Objet</div>
                <div style="font-weight:700;">${objet || '<em>Non renseigné</em>'}</div>
            </div>
            <p style="margin:0;font-size:12px;color:#94a3b8;">${icon} La demande sera envoyée au responsable pour validation.</p>
        </div>`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: type === 'vehicule' ? '#7c3aed' : '#0891b2',
        cancelButtonColor: '#6c757d',
        confirmButtonText: '<i class="fas fa-paper-plane"></i> Envoyer',
        cancelButtonText: '<i class="fas fa-arrow-left"></i> Modifier',
        reverseButtons: true
    }).then((result) => {
        if (result.isConfirmed) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Envoi...';
            form.submit();
        }
    });
    return false;
}

/**
 * Confirme le rendu d'un véhicule
 * @param {HTMLFormElement} form - Le formulaire de retour
 */
function confirmerRetour(form) {
    const kmRetour = form.querySelector('[name="km_retour"]')?.value;
    if (!kmRetour || parseInt(kmRetour) < 1) {
        Swal.fire({
            title: 'KM manquant',
            text: 'Veuillez saisir le kilométrage au retour.',
            icon: 'info',
            confirmButtonColor: '#17a2b8'
        });
        return false;
    }
    
    Swal.fire({
        title: 'Rendre le véhicule ?',
        html: `<div style="text-align:left;">
            <div style="background:#f0fdf4;border-radius:8px;padding:12px;margin-bottom:8px;border:1px solid #bbf7d0;">
                <div style="font-size:12px;color:#166534;margin-bottom:4px;">Kilométrage au retour</div>
                <div style="font-weight:700;color:#166534;font-size:18px;">${kmRetour} km</div>
            </div>
            <p style="margin:0;font-size:12px;color:#94a3b8;">🚗 Le véhicule sera marqué comme rendu et disponible.</p>
        </div>`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#17a2b8',
        cancelButtonColor: '#6c757d',
        confirmButtonText: '<i class="fas fa-check"></i> Confirmer le retour',
        cancelButtonText: '<i class="fas fa-arrow-left"></i> Modifier',
        reverseButtons: true
    }).then((result) => {
        if (result.isConfirmed) {
            const btn = form.querySelector('[type="submit"]');
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Traitement...';
            form.submit();
        }
    });
    return false;
}

/**
 * Confirme la validation et l'affectation d'un véhicule
 * @param {HTMLFormElement} form - Le formulaire de validation
 * @param {string} type - 'vehicule' ou 'salle'
 */
function confirmerValidation(form, type) {
    const icon = type === 'vehicule' ? '🚗' : '🏢';
    const selectEl = form.querySelector('[name="vehicule"], [name="salle"]');
    const selectedOption = selectEl?.options[selectEl.selectedIndex];
    const selectedText = selectedOption?.text || '';
    
    if (!selectEl?.value) {
        Swal.fire({
            title: `${type === 'vehicule' ? 'Véhicule' : 'Salle'} non sélectionné`,
            text: `Veuillez choisir un ${type === 'vehicule' ? 'véhicule' : 'salle'} disponible.`,
            icon: 'info',
            confirmButtonColor: '#17a2b8'
        });
        return false;
    }
    
    Swal.fire({
        title: `Valider et ${type === 'vehicule' ? 'affecter' : 'attribuer'} ?`,
        html: `<div style="text-align:left;">
            <div style="background:#f0fdf4;border-radius:8px;padding:12px;margin-bottom:8px;border:1px solid #bbf7d0;">
                <div style="font-size:12px;color:#166534;margin-bottom:4px;">${type === 'vehicule' ? 'Véhicule' : 'Salle'} sélectionné(e)</div>
                <div style="font-weight:700;color:#166534;">${icon} ${selectedText}</div>
            </div>
            <p style="margin:0;font-size:12px;color:#94a3b8;">La demande sera validée et ${type === 'vehicule' ? 'le véhicule sera affecté' : 'la salle sera attribuée'} au demandeur.</p>
        </div>`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#28a745',
        cancelButtonColor: '#6c757d',
        confirmButtonText: '<i class="fas fa-check"></i> Valider',
        cancelButtonText: '<i class="fas fa-arrow-left"></i> Modifier',
        reverseButtons: true
    }).then((result) => {
        if (result.isConfirmed) {
            const btn = form.querySelector('[type="submit"][value="valider"]');
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Validation...';
            }
            form.submit();
        }
    });
    return false;
}

/**
 * Confirme le refus d'une demande
 * @param {string} url - URL de redirection après confirmation
 * @param {string} type - 'vehicule' ou 'salle'
 */
function confirmerRefus(url, type) {
    const icon = type === 'vehicule' ? '🚗' : '🚪';
    Swal.fire({
        title: 'Refuser cette demande ?',
        html: `<div style="text-align:left;">
            <p style="margin:0 0 8px;">${icon} Le demandeur sera notifié du refus.</p>
        </div>`,
        input: 'textarea',
        inputPlaceholder: 'Motif du refus (obligatoire)...',
        inputValidator: (value) => {
            if (!value || value.trim().length < 3) {
                return 'Le motif du refus est obligatoire';
            }
        },
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#dc3545',
        cancelButtonColor: '#6c757d',
        confirmButtonText: '<i class="fas fa-times"></i> Refuser',
        cancelButtonText: '<i class="fas fa-arrow-left"></i> Annuler',
        reverseButtons: true,
        focusCancel: true
    }).then((result) => {
        if (result.isConfirmed) {
            // Créer un formulaire temporaire pour envoyer le motif
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = url;
            
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
                              document.cookie.match(/csrftoken=([^;]+)/)?.[1];
            if (csrfToken) {
                const csrfInput = document.createElement('input');
                csrfInput.type = 'hidden';
                csrfInput.name = 'csrfmiddlewaretoken';
                csrfInput.value = csrfToken;
                form.appendChild(csrfInput);
            }
            
            const actionInput = document.createElement('input');
            actionInput.type = 'hidden';
            actionInput.name = 'action';
            actionInput.value = 'refuser';
            form.appendChild(actionInput);
            
            const motifInput = document.createElement('input');
            motifInput.type = 'hidden';
            motifInput.name = 'motif_refus';
            motifInput.value = result.value;
            form.appendChild(motifInput);
            
            document.body.appendChild(form);
            form.submit();
        }
    });
    return false;
}

/**
 * Modale SweetAlert2 réutilisable pour toute action nécessitant une confirmation.
 * Utilisation: onclick="confirmerSweetAlert('Titre', 'Description', 'question', 'Confirmer', '#007bff', callback)"
 */
function confirmerSweetAlert(title, text, icon, confirmText, confirmColor, onConfirm) {
    Swal.fire({
        title: title,
        text: text,
        icon: icon || 'question',
        showCancelButton: true,
        confirmButtonColor: confirmColor || '#0d47a1',
        cancelButtonColor: '#6c757d',
        confirmButtonText: '<i class="fas fa-check"></i>&nbsp; ' + (confirmText || 'Confirmer'),
        cancelButtonText: 'Annuler',
        focusCancel: true,
        reverseButtons: true
    }).then(function(result) {
        if (result.isConfirmed && typeof onConfirm === 'function') {
            onConfirm();
        }
    });
}
