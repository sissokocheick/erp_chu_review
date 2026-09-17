
/* ═════ DONNÉES ARTICLES ═════ */
const ALL_ARTICLES = [
    {% for a in articles %}
    {id: {{ a.id }}, designation: "{{ a.designation|escapejs }}", reference: "{{ a.reference|default:""|escapejs }}"}{% if not forloop.last %},{% endif %}
    {% endfor %}
];

/* ═════ PRÉ-REMPLISSAGE (retour fournisseur en 1 clic) ═════ */
const PREFILL = {% if prefill_retour %}{
  fournisseur_id: {{ prefill_retour.fournisseur_id }},
  lignes: [
    {% for l in prefill_retour.lignes %}
    {article_id: {{ l.article_id }}, designation: "{{ l.designation|escapejs }}", reference: "{{ l.reference|escapejs }}", quantite: {{ l.quantite }}, numero_lot: "{{ l.numero_lot|escapejs }}", date_peremption: "{{ l.date_peremption }}"}{% if not forloop.last %},{% endif %}
    {% endfor %}
  ]
}{% else %}null{% endif %};

/* ═════ MODAL PDF ═════ */
window.imprimerModal = function(url, titre) {
        if (window.nxOpenPdfModal) { nxOpenPdfModal(url, titre); return; }
        window.open(url, '_blank');
    };

document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('modal-pdf').addEventListener('click', function(e) {
        if (e.target === this) this.classList.remove('open');
    });
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') document.getElementById('modal-pdf').classList.remove('open');
    });
});

function toggleDetail(bonId) {
    var detail = document.getElementById('detail-' + bonId);
    var chev   = document.getElementById('chev-' + bonId);
    var isOpen = detail && detail.classList.contains('open');

    document.querySelectorAll('.detail-row.open').forEach(function(r){ r.classList.remove('open'); });
    document.querySelectorAll('.chev').forEach(function(c){
        c.classList.replace('fa-chevron-down','fa-chevron-right'); c.style.color='var(--text-light)';
    });

    if (!isOpen && detail) {
        detail.classList.add('open');
        if (chev) { chev.classList.replace('fa-chevron-right','fa-chevron-down'); chev.style.color='#e74c3c'; }
    }
}

function clearDateRange() {
    var dr = document.getElementById('date_range');
    var form = document.getElementById('form-q');
    if (dr) dr.value = '';
    if (form) form.submit();
}

document.addEventListener('DOMContentLoaded', function() {
    var timer;
    var input = document.getElementById('input-q');
    var tbody = document.getElementById('zone-tbody');
    var form  = document.getElementById('form-q');

    if (input) {
        input.addEventListener('input', function() {
            clearTimeout(timer);
            if (tbody) tbody.style.opacity = '.4';
            timer = setTimeout(function() {
                var params = new URLSearchParams(new FormData(form)).toString();
                fetch(window.location.pathname + '?' + params, {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                })
                .then(function(r){ return r.text(); })
                .then(function(html) {
                    if (tbody) { tbody.innerHTML = html; tbody.style.opacity = '1'; }
                })
                .catch(function() {
                    if (tbody) tbody.style.opacity = '1';
                });
            }, 400);
        });
    }

    if ($.fn.daterangepicker) {
        var $dr = $('#date_range');
        var existing = $dr.val();
        var drConfig = {
            autoUpdateInput: false,
            autoApply: true,
            locale: {
                format: 'DD/MM/YYYY',
                cancelLabel: 'Effacer',
                applyLabel: 'Appliquer',
                daysOfWeek: ['Di', 'Lu', 'Ma', 'Me', 'Je', 'Ve', 'Sa'],
                monthNames: ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Aoû', 'Sep', 'Oct', 'Nov', 'Déc']
            }
        };

        if (existing) {
            var parts = existing.split(' - ');
            if (parts.length === 2) {
                drConfig.startDate = moment(parts[0], 'DD/MM/YYYY');
                drConfig.endDate   = moment(parts[1], 'DD/MM/YYYY');
            }
        }

        $dr.daterangepicker(drConfig);

        $dr.on('apply.daterangepicker', function(ev, picker) {
            $(this).val(picker.startDate.format('DD/MM/YYYY') + ' - ' + picker.endDate.format('DD/MM/YYYY'));
            if (form) form.submit();
        });

        $dr.on('cancel.daterangepicker', function(ev, picker) {
            $(this).val('');
            if (form) form.submit();
        });
    }

    if (typeof $ !== 'undefined') {
        $('.select2-fournisseur').select2({ width: '100%', dropdownParent: $('#modal-retour') });
    }
});

function ouvrirModal() {
    document.getElementById('modal-retour').classList.add('open');
    setTimeout(function(){ document.getElementById('input-search-article').focus(); }, 100);
}
function fermerModal() {
    document.getElementById('modal-retour').classList.remove('open');
}
document.addEventListener('keydown', function(e){
    if (e.key === 'Escape') fermerModal();
});

/* ═══════════════════════════════════════════════
   RECHERCHE & AJOUT D'ARTICLES
   ═══════════════════════════════════════════════ */
(function() {
    var searchInput = document.getElementById('input-search-article');
    var resultsBox  = document.getElementById('search-results');
    var zoneLignes  = document.getElementById('zone-lignes');
    var msgVide     = document.getElementById('msg-vide');
    var badgeNb     = document.getElementById('badge-nb');
    var ligneIndex  = 0;

    function updateCompteur() {
        var nb = zoneLignes.querySelectorAll('.ligne-item').length;
        badgeNb.textContent = nb;
        msgVide.style.display = nb === 0 ? 'block' : 'none';
    }

    function ajouterLigneArticle(article, extra) {
        extra = extra || {};
        var qte = extra.quantite || 1;
        var lot = extra.numero_lot || '';
        var peremp = extra.date_peremption || '';

        var existant = zoneLignes.querySelector('[data-article-id="' + article.id + '"]');
        if (existant) {
            Swal.fire({ icon: 'info', title: 'Déjà présent', text: 'Cet article est déjà dans la liste.', confirmButtonColor: '#e74c3c', timer: 2000 });
            searchInput.value = '';
            resultsBox.classList.remove('open');
            searchInput.focus();
            return;
        }

        ligneIndex++;
        var div = document.createElement('div');
        div.className = 'ligne-item';
        div.setAttribute('data-article-id', article.id);
        div.id = 'ligne-' + ligneIndex;

        div.innerHTML = `
            <div class="ligne-grid">
                <div class="fg" style="margin:0;">
                    <label>Article</label>
                    <input type="hidden" name="articles[]" value="${article.id}">
                    <div style="padding:9px 12px; background:var(--bg-stripe); border:1px solid var(--border-color); border-radius:7px; font-size:13px; font-weight:600; color:var(--text-dark);">
                        ${article.designation}
                        <span style="color:var(--text-light); font-size:11px; font-weight:400;">(${article.reference || '—'})</span>
                    </div>
                </div>
                <div class="fg" style="margin:0;">
                    <label>Quantité *</label>
                    <input type="number" name="quantites[]" min="1" required value="${qte}"
                           style="width:100%; padding:8px; border:2px solid #e74c3c; border-radius:6px; text-align:center; font-weight:bold; color:#e74c3c; font-size:14px; outline:none; box-sizing:border-box;">
                </div>
                <div class="fg" style="margin:0;">
                    <label>N° Lot</label>
                    <input type="text" name="lots[]" placeholder="Optionnel" value="${lot}"
                           style="width:100%; padding:8px; border:1px solid var(--border-color); border-radius:6px; font-size:13px; outline:none; background:var(--bg-input); color:var(--text-dark); box-sizing:border-box;">
                </div>
                <div class="fg" style="margin:0;">
                    <label>Péremption</label>
                    <input type="date" name="peremptions[]" value="${peremp}"
                           style="width:100%; padding:8px; border:1px solid var(--border-color); border-radius:6px; font-size:13px; outline:none; background:var(--bg-input); color:var(--text-dark); box-sizing:border-box;">
                </div>
                <button type="button" class="btn-rm" onclick="this.closest('.ligne-item').remove(); updateCompteur();" title="Retirer la ligne" aria-label="Retirer la ligne"><i class="fas fa-trash"></i></button>
            </div>
        `;
        zoneLignes.appendChild(div);
        updateCompteur();
        searchInput.value = '';
        resultsBox.classList.remove('open');
        searchInput.focus();
    }

    if (searchInput) {
        searchInput.addEventListener('input', function() {
            var term = this.value.trim().toLowerCase();
            if (!term) { resultsBox.classList.remove('open'); resultsBox.innerHTML = ''; return; }

            var matches = ALL_ARTICLES.filter(function(a) {
                return (a.designation || '').toLowerCase().indexOf(term) !== -1
                    || (a.reference || '').toLowerCase().indexOf(term) !== -1;
            }).slice(0, 8);

            if (!matches.length) {
                resultsBox.innerHTML = '<div class="res-empty">Aucun article trouvé</div>';
            } else {
                resultsBox.innerHTML = matches.map(function(a) {
                    return '<div class="res-item" onclick="ajouterLigneArticle(' + JSON.stringify(a).replace(/"/g, '&quot;') + ')">' +
                        '<span>' + a.designation + '<span class="ref">' + (a.reference || '') + '</span></span>' +
                        '<i class="fas fa-plus add-icon"></i></div>';
                }).join('');
            }
            resultsBox.classList.add('open');
        });

        document.addEventListener('click', function(e) {
            if (!searchInput.contains(e.target) && !resultsBox.contains(e.target)) {
                resultsBox.classList.remove('open');
            }
        });
    }

    function appliquerPrefill() {
        if (!PREFILL) return;
        var sel = document.getElementById('sel-fournisseur');
        if (sel && PREFILL.fournisseur_id) {
            sel.value = String(PREFILL.fournisseur_id);
            if (window.jQuery && jQuery.fn.select2) { jQuery(sel).trigger('change'); }
        }
        (PREFILL.lignes || []).forEach(function(l) {
            ajouterLigneArticle(
                {id: l.article_id, designation: l.designation, reference: l.reference},
                {quantite: l.quantite, numero_lot: l.numero_lot, date_peremption: l.date_peremption}
            );
        });
        var modal = document.getElementById('modal-retour');
        if (modal) modal.classList.add('open');
    }
    if (PREFILL) document.addEventListener('DOMContentLoaded', appliquerPrefill);

    window.updateCompteur = updateCompteur;
    window.ajouterLigneArticle = ajouterLigneArticle;
    window.appliquerPrefill = appliquerPrefill;
})();

function confirmerAnnulationRetourFournisseur(bonId, numeroBon) {
    Swal.fire({
        title: 'Annuler le retour ' + numeroBon,
        html: `<div style="text-align:left; margin-top:10px;">
            <label style="font-weight:bold;">Motif :</label>
            <select id="swal-motif-select-rf" class="form-control" style="width:100%;margin-top:10px;">
                <option value="">-- Sélectionner --</option>
                {% for m in motifs_annulation %}
                <option value="{{ m.id }}">{{ m.libelle }}</option>
                {% endfor %}
            </select>
        </div>`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#dc3545',
        confirmButtonText: 'Confirmer l\'annulation',
        cancelButtonText: 'Retour',
        didOpen: () => {
            if (typeof $ !== 'undefined') {
                $('#swal-motif-select-rf').select2({
                    dropdownParent: $('.swal2-container'),
                    placeholder: 'Tapez pour chercher...'
                });
            }
        },
        preConfirm: () => {
            const motifId = document.getElementById('swal-motif-select-rf').value;
            if (!motifId) {
                Swal.showValidationMessage('Veuillez sélectionner un motif');
            }
            return motifId;
        }
    }).then((result) => {
        if (result.isConfirmed) {
            let form = document.getElementById('form-annuler-rf-' + bonId);
            let inputMotif = document.createElement('input');
            inputMotif.type = 'hidden';
            inputMotif.name = 'motif_id';
            inputMotif.value = result.value;
            form.appendChild(inputMotif);
            Swal.fire({
                title: 'Annulation en cours...',
                allowOutsideClick: false,
                didOpen: () => { Swal.showLoading(); }
            });
            form.submit();
        }
    });
}
