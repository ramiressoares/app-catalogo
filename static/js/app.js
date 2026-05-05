(function () {
    var alerts = document.querySelectorAll('[data-auto-dismiss]');
    var loading = document.getElementById('appLoading');
    var forms = document.querySelectorAll('form');
    var modal = document.getElementById('fishImageModal');
    var modalImage = document.getElementById('fishModalImage');
    var closeButton = document.getElementById('fishModalClose');
    var imageButtons = document.querySelectorAll('.fish-image-button');
    var uploadInput = document.getElementById('imagem');
    var uploadLabel = document.querySelector('[data-upload-label]');

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

    if (uploadInput && uploadLabel) {
        uploadInput.addEventListener('change', function () {
            var fileName = uploadInput.files && uploadInput.files[0] ? uploadInput.files[0].name : 'Selecione uma imagem';
            uploadLabel.textContent = fileName;
        });
    }

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

    // Curtidas
    document.querySelectorAll('.like-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var peixeId = btn.getAttribute('data-peixe-id');
            var countEl = document.querySelector('.like-count[data-peixe-id="' + peixeId + '"]');
            var labelEl = countEl ? countEl.nextElementSibling : null;

            fetch('/peixes/' + peixeId + '/curtir', {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin'
            })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data.curtido) {
                    btn.classList.add('like-btn--active');
                    btn.setAttribute('aria-pressed', 'true');
                    btn.querySelector('i').className = 'bi bi-heart-fill';
                } else {
                    btn.classList.remove('like-btn--active');
                    btn.setAttribute('aria-pressed', 'false');
                    btn.querySelector('i').className = 'bi bi-heart';
                }
                if (countEl) {
                    countEl.textContent = data.total;
                }
                if (labelEl) {
                    labelEl.textContent = data.total === 1 ? 'curtida' : 'curtidas';
                }
            })
            .catch(function () {});
        });
    });
})();