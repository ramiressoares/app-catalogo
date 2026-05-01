(function () {
    var alerts = document.querySelectorAll('[data-auto-dismiss]');
    var loading = document.getElementById('appLoading');
    var forms = document.querySelectorAll('form');
    var modal = document.getElementById('fishImageModal');
    var modalImage = document.getElementById('fishModalImage');
    var closeButton = document.getElementById('fishModalClose');
    var imageButtons = document.querySelectorAll('.fish-image-button');

    alerts.forEach(function (alertElement) {
        var timeout = Number(alertElement.getAttribute('data-auto-dismiss')) || 3000;

        window.setTimeout(function () {
            alertElement.classList.remove('show');
            alertElement.classList.add('hide');
            window.setTimeout(function () {
                alertElement.remove();
            }, 250);
        }, timeout);
    });

    forms.forEach(function (form) {
        form.addEventListener('submit', function () {
            if (loading) {
                loading.classList.add('is-visible');
                loading.setAttribute('aria-hidden', 'false');
            }
        });
    });

    if (modal && modalImage && closeButton && imageButtons.length) {
        function openModal(src, name) {
            modalImage.src = src;
            modalImage.alt = 'Imagem ampliada de ' + name;
            modal.classList.add('is-open');
            modal.setAttribute('aria-hidden', 'false');
            document.body.classList.add('modal-open');
        }

        function closeModal() {
            modal.classList.remove('is-open');
            modal.setAttribute('aria-hidden', 'true');
            modalImage.src = '';
            document.body.classList.remove('modal-open');
        }

        imageButtons.forEach(function (button) {
            button.addEventListener('click', function () {
                var src = button.getAttribute('data-fish-image');
                var name = button.getAttribute('data-fish-name') || 'peixe';

                if (src) {
                    openModal(src, name);
                }
            });
        });

        closeButton.addEventListener('click', closeModal);

        modal.addEventListener('click', function (event) {
            if (event.target === modal) {
                closeModal();
            }
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && modal.classList.contains('is-open')) {
                closeModal();
            }
        });
    }
})();