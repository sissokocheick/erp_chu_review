
    const CSRF_TOKEN = '{{ csrf_token }}';

    window.imprimerModal = function(url, titre) {
        if (window.nxOpenPdfModal) { nxOpenPdfModal(url, titre); return; }
        var modal = document.getElementById('modal-pdf');
        var loader = document.getElementById('pdf-loader');
        var iframe = document.getElementById('pdf-iframe');
        if (modal) {
            modal.classList.add('open');
            loader.style.display = 'flex';
            iframe.style.display = 'none';
            iframe.onload = function() {
                loader.style.display = 'none';
                iframe.style.display = 'block';
            };
            iframe.src = url;
        } else {
            window.open(url, '_blank');
        }
    };

    
    function toggleDetail(rowId, iconId) {
        var row = document.getElementById(rowId);
        var icon = document.getElementById(iconId);
        if (row.style.display === "none" || row.style.display === "") {
            document.querySelectorAll('tr[id^="detail-"]').forEach(function(r) { r.style.display = 'none'; });
            document.querySelectorAll('i[id^="icon-"]').forEach(function(i) { i.style.transform = 'rotate(0deg)'; });
            row.style.display = "table-row";
            if(icon) icon.style.transform = "rotate(90deg)";
        } else {
            row.style.display = "none";
            if(icon) icon.style.transform = "rotate(0deg)";
        }
    }

    function filtrerProduits() {
        let input = document.getElementById('vd-search-input').value.toLowerCase();
        let dropdown = document.getElementById('vd-dropdown');
        let items = document.querySelectorAll('.dropdown-item');
        let hasVisible = false;

        let magasinSourceId = document.querySelector('input[name="magasin_source"][type="hidden"]') ? document.querySelector('input[name="magasin_source"][type="hidden"]').value : document.querySelector('select[name="magasin_source"]').value;

        if (input.length > 0) {
            dropdown.style.display = 'block';
            items.forEach(function(item) {
                let ref = item.getAttribute('data-ref').toLowerCase();
                let nom = item.getAttribute('data-nom').toLowerCase();
                
                // Mettre à jour le stock affiché pour le magasin source sélectionné
                let stocks = JSON.parse(item.getAttribute('data-stocks') || '{}');
                let qte = stocks[magasinSourceId] || 0;
                
                let spanStock = item.querySelector('.badge-stock');
                spanStock.innerText = qte + " en stock";
                if(qte > 0) { spanStock.style.color = '#28a745'; spanStock.style.fontWeight = 'bold'; }
                else { spanStock.style.color = '#dc3545'; spanStock.style.fontWeight = 'normal'; }

                if (ref.includes(input) || nom.includes(input)) {
                    item.style.display = '';
                    hasVisible = true;
                } else {
                    item.style.display = 'none';
                }
            });
        } else {
            dropdown.style.display = 'none';
        }
    }

    let compteurLignes = 0;

    function ajouterArticleDirect(element) {
        let id = element.getAttribute('data-id');
        let ref = element.getAttribute('data-ref');
        let nom = element.getAttribute('data-nom');
        
        let magasinSourceId = document.querySelector('input[name="magasin_source"][type="hidden"]') ? document.querySelector('input[name="magasin_source"][type="hidden"]').value : document.querySelector('select[name="magasin_source"]').value;
        let stocks = JSON.parse(element.getAttribute('data-stocks') || '{}');
        let qteDispo = stocks[magasinSourceId] || 0;
        
        if (qteDispo <= 0) {
            Swal.fire({icon: 'error', title: 'Stock insuffisant', text: 'Cet article n\'est pas en stock dans le magasin source.'});
            document.getElementById('vd-dropdown').style.display = 'none';
            return;
        }

        // Vérifier si l'article est déjà dans le tableau
        let trExistant = document.querySelector('tr[data-article-id="' + id + '"]');
        if (trExistant) {
            let inputQte = trExistant.querySelector('input[name="quantites[]"]');
            inputQte.value = parseInt(inputQte.value) + 1;
        } else {
            document.getElementById('vd-ligne-vide')?.remove();
            compteurLignes++;

            let tbody = document.getElementById('vd-lignes-tbody');
            let tr = document.createElement('tr');
            tr.setAttribute('data-article-id', id);
            tr.innerHTML = 
                '<td class="col-num" style="text-align: center; font-weight: bold; color: var(--text-medium);">' + compteurLignes + '</td>' +
                '<td style="font-family: monospace; font-size: 13px;">' + (ref !== '-' ? ref : '') + '</td>' +
                '<td style="font-weight: 500; font-size: 14px; color: var(--text-dark);">' + nom + '</td>' +
                '<td style="text-align: center;">' +
                '<input type="number" name="quantites[]" value="1" min="1" max="' + qteDispo + '" class="input-ligne-qte" style="width: 80px; padding:6px; border:1px solid #ccc; border-radius:4px; text-align:center;" title="Max: ' + qteDispo + '">' +
                '<input type="hidden" name="articles[]" value="' + id + '">' +
                '<div style="font-size:11px; color:#6c757d; margin-top:4px;">Dispo: ' + qteDispo + '</div>' +
                '</td>' +
                '<td style="text-align: center;">' +
                '<button type="button" onclick="supprimerLigneVD(this)" style="color: #dc3545; border: none; background: var(--bg-hover); width: 32px; height: 32px; border-radius: 6px; cursor: pointer;"><i class="fas fa-trash-alt"></i></button>' +
                '</td>';
            tbody.appendChild(tr);
        }
        document.getElementById('vd-search-input').value = '';
        document.getElementById('vd-dropdown').style.display = 'none';
        document.getElementById('vd-search-input').focus();
    }

    function supprimerLigneVD(btn) {
        btn.closest('tr').remove();
        let lignes = document.querySelectorAll('#vd-lignes-tbody tr:not(#vd-ligne-vide)');
        compteurLignes = 0;
        lignes.forEach(ligne => { compteurLignes++; ligne.querySelector('.col-num').innerText = compteurLignes; });
        if (document.getElementById('vd-lignes-tbody').children.length === 0) {
            document.getElementById('vd-lignes-tbody').innerHTML = '<tr id="vd-ligne-vide"><td colspan="5" style="text-align: center; padding: 50px; color: var(--text-light);"><i class="fas fa-box" style="font-size: 40px; margin-bottom: 15px; display: block; opacity: 0.4;"></i>Aucun article ajouté. Cherchez ci-dessus.</td></tr>';
            compteurLignes = 0;
        }
    }

    function annulerTransfert(id, numero) {
        Swal.fire({
            title: 'Annuler le transfert ' + numero + ' ?',
            text: 'Le stock sera restitué au magasin source (le magasin destination sera débité).',
            icon: 'warning',
            input: 'text',
            inputPlaceholder: 'Motif de l\'annulation (optionnel)',
            showCancelButton: true,
            confirmButtonText: 'Oui, annuler',
            cancelButtonText: 'Non',
            confirmButtonColor: '#dc3545',
            inputValidator: () => undefined
        }).then((result) => {
            if (!result.isConfirmed) return;
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = "{% url 'liste_transferts' %}".replace('liste_transferts', 'transferts/' + id + '/annuler/');
            form.innerHTML = '<input type="hidden" name="csrfmiddlewaretoken" value="' + CSRF_TOKEN + '">' +
                '<input type="hidden" name="motif" value="' + (result.value || '') + '">';
            document.body.appendChild(form);
            form.submit();
        });
    }

    function receptionnerTransfert(id, numero) {
        Swal.fire({
            title: 'Réceptionner le transfert ' + numero + ' ?',
            text: 'Le stock sera crédité dans le magasin de destination.',
            icon: 'question',
            input: 'text',
            inputPlaceholder: 'Commentaire de réception (optionnel)',
            showCancelButton: true,
            confirmButtonText: 'Oui, réceptionner',
            cancelButtonText: 'Non',
            confirmButtonColor: '#28a745',
            inputValidator: () => undefined
        }).then((result) => {
            if (!result.isConfirmed) return;
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = "{% url 'receptionner_transfert' 0 %}".replace('/0/', '/' + id + '/');
            form.innerHTML = '<input type="hidden" name="csrfmiddlewaretoken" value="' + CSRF_TOKEN + '">' +
                '<input type="hidden" name="commentaire" value="' + (result.value || '') + '">';
            document.body.appendChild(form);
            form.submit();
        });
    }

    


    

    
    if (typeof jQuery !== 'undefined') {
        $('.select2').select2({ dropdownParent: $('#modal-transfert') });
    }
    document.addEventListener('DOMContentLoaded', function() {
        // Fermeture modales au clic extérieur
        const modalTransfert = document.getElementById('modal-transfert');
        if (modalTransfert) {
            modalTransfert.addEventListener('click', function(e) {
                if (e.target === this) this.style.display = 'none';
            });
        }
        const modalPdf = document.getElementById('modal-pdf');
        if (modalPdf) {
            modalPdf.addEventListener('click', function(e) {
                if (e.target === this) this.classList.remove('open');
            });
        }
    });
