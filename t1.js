
    


    

    
    if (typeof jQuery !== 'undefined') {
        $('.select2').select2({ dropdownParent: $('#modal-transfert') });
    }
    document.addEventListener('DOMContentLoaded', function() {
        const urlImpression = "{% url 'imprimer_bon_multi_lignes' request.GET.print_bon %}";
        imprimerModal(urlImpression, "Bon de Transfert — {{ request.GET.print_bon }}");
    });
