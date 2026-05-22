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
            if (form.matches('.comment-form')) {
                return;
            }

            if (loading) {
                loading.classList.add('is-visible');
                loading.setAttribute('aria-hidden', 'false');
            }
        });
    });

    if (uploadInput && uploadLabel) {
        uploadInput.addEventListener('change', function () {
            var fileName = uploadInput.files && uploadInput.files[0] ? uploadInput.files[0].name : 'Selecione a imagem do registro';
            uploadLabel.textContent = fileName;
        });
    }

    document.querySelectorAll('.fish-image').forEach(function (image) {
        if (image.complete) {
            image.classList.remove('fish-image--loading');
            image.classList.add('fish-image--loaded');
            return;
        }

        image.addEventListener('load', function () {
            image.classList.remove('fish-image--loading');
            image.classList.add('fish-image--loaded');
        });

        image.addEventListener('error', function () {
            image.classList.remove('fish-image--loading');
            image.classList.add('fish-image--loaded');
        });
    });

    if (modal && modalImage && closeButton && imageButtons.length) {
        function openModal(src, name) {
            modalImage.src = src;
            modalImage.alt = 'Imagem ampliada do registro de ' + name;
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
            var labelEl = document.querySelector('[data-like-label="' + peixeId + '"]');

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
                    labelEl.textContent = data.total === 1 ? 'apoio' : 'apoios';
                }
            })
            .catch(function () {});
        });
    });

    // Comentarios (toggle, curtida e envio assincrono)
    document.querySelectorAll('[data-comment-toggle]').forEach(function (toggle) {
        toggle.addEventListener('click', function () {
            var peixeId = toggle.getAttribute('data-comment-toggle');
            var panel = document.getElementById('comments-' + peixeId);

            if (!panel) {
                return;
            }

            var willOpen = !panel.classList.contains('is-open');
            panel.classList.toggle('is-open', willOpen);
            panel.setAttribute('aria-hidden', willOpen ? 'false' : 'true');
            toggle.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
        });
    });

    function createCommentElement(comment, peixeId) {
        var article = document.createElement('article');
        article.className = 'comment-item' + (comment.parent_id ? ' comment-item--reply' : '');
        article.setAttribute('data-comment-id', String(comment.id));

        article.innerHTML =
            '<div class="comment-item__head">' +
                '<span class="comment-avatar"></span>' +
                '<strong></strong>' +
                '<span></span>' +
            '</div>' +
            '<p></p>' +
            '<div class="comment-item__actions">' +
                '<button type="button" class="comment-like-btn" data-comment-like="' + comment.id + '" aria-pressed="false">' +
                    '<i class="bi bi-heart"></i>' +
                    '<span data-comment-like-count="' + comment.id + '">0</span>' +
                '</button>' +
                '<button type="button" class="comment-reply-btn" data-reply-toggle="' + comment.id + '" aria-expanded="false" aria-controls="reply-' + comment.id + '">' +
                    '<i class="bi bi-reply"></i><span>Responder</span>' +
                '</button>' +
            '</div>' +
            '<form method="post" action="/peixes/' + peixeId + '/comentar" class="comment-reply-form" id="reply-' + comment.id + '" data-reply-form="' + comment.id + '" data-comment-form="' + peixeId + '" aria-hidden="true">' +
                '<input type="hidden" name="parent_id" value="' + comment.id + '">' +
                '<label for="reply_input_' + comment.id + '" class="visually-hidden">Resposta</label>' +
                '<input type="text" id="reply_input_' + comment.id + '" name="comentario" class="form-control" maxlength="300" placeholder="Escreva uma resposta objetiva e respeitosa..." required>' +
                '<button type="submit" class="app-button app-button--sm"><i class="bi bi-send"></i><span>Publicar</span></button>' +
            '</form>' +
            '<div class="comment-children" data-comment-children="' + comment.id + '"></div>';

        article.querySelector('.comment-avatar').textContent = comment.avatar;
        article.querySelector('.comment-item__head strong').textContent = comment.usuario_nome;
        article.querySelector('.comment-item__head span:last-child').textContent = comment.data;
        article.querySelector('p').textContent = comment.texto;
        article.querySelector('[data-comment-like-count="' + comment.id + '"]').textContent = comment.curtidas || 0;

        return article;
    }

    document.addEventListener('click', function (event) {
        var likeButton = event.target.closest('[data-comment-like]');
        if (likeButton) {
            var comentarioId = likeButton.getAttribute('data-comment-like');
            var icon = likeButton.querySelector('i');
            var countEl = document.querySelector('[data-comment-like-count="' + comentarioId + '"]');

            fetch('/comentarios/' + comentarioId + '/curtir', {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin'
            })
            .then(function (response) { return response.json(); })
            .then(function (data) {
                if (!data || !data.ok) {
                    return;
                }

                likeButton.classList.toggle('is-active', data.curtido);
                likeButton.setAttribute('aria-pressed', data.curtido ? 'true' : 'false');
                if (icon) {
                    icon.className = data.curtido ? 'bi bi-heart-fill' : 'bi bi-heart';
                }
                if (countEl) {
                    countEl.textContent = data.total;
                }
            })
            .catch(function () {});
            return;
        }

        var replyToggle = event.target.closest('[data-reply-toggle]');
        if (replyToggle) {
            var commentId = replyToggle.getAttribute('data-reply-toggle');
            var replyForm = document.getElementById('reply-' + commentId);
            if (!replyForm) {
                return;
            }

            var isOpen = !replyForm.classList.contains('is-open');
            replyForm.classList.toggle('is-open', isOpen);
            replyForm.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
            replyToggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
            if (isOpen) {
                var replyInput = replyForm.querySelector('input[name="comentario"]');
                if (replyInput) {
                    replyInput.focus();
                }
            }
        }
    });

    document.addEventListener('submit', function (event) {
        var form = event.target;
        if (!form.matches('[data-comment-form]')) {
            return;
        }

        event.preventDefault();

        var peixeId = form.getAttribute('data-comment-form');
        var parentIdInput = form.querySelector('input[name="parent_id"]');
        var parentId = parentIdInput ? parentIdInput.value : '';
        var input = form.querySelector('input[name="comentario"]');
        var list = document.querySelector('[data-comment-list="' + peixeId + '"]');
        var countEl = document.querySelector('[data-comment-count="' + peixeId + '"]');
        var labelEl = document.querySelector('[data-comment-label="' + peixeId + '"]');
        var emptyEl = document.querySelector('[data-comment-empty="' + peixeId + '"]');

        if (!input || !input.value.trim() || !list) {
            return;
        }

        var submitButton = form.querySelector('button[type="submit"]');
        var originalButtonText = submitButton ? submitButton.innerHTML : '';

        if (submitButton) {
            submitButton.disabled = true;
            submitButton.innerHTML = '<i class="bi bi-hourglass-split"></i><span>Publicando...</span>';
        }

        var payload = 'comentario=' + encodeURIComponent(input.value.trim());
        if (parentId) {
            payload += '&parent_id=' + encodeURIComponent(parentId);
        }

        fetch(form.action, {
            method: 'POST',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'
            },
            credentials: 'same-origin',
            body: payload
        })
        .then(function (response) { return response.json(); })
        .then(function (data) {
            if (!data || !data.ok || !data.comentario) {
                return;
            }

            if (emptyEl) {
                emptyEl.remove();
            }

            var commentEl = createCommentElement(data.comentario, peixeId);

            if (data.comentario.parent_id) {
                var children = document.querySelector('[data-comment-children="' + data.comentario.parent_id + '"]');
                if (children) {
                    children.insertBefore(commentEl, children.firstChild);
                } else {
                    list.insertBefore(commentEl, list.firstChild);
                }
            } else {
                list.insertBefore(commentEl, list.firstChild);
            }

            input.value = '';

            if (countEl) {
                countEl.textContent = data.total;
            }

            if (labelEl) {
                labelEl.textContent = data.total === 1 ? 'comentário' : 'comentários';
            }

            if (parentId) {
                form.classList.remove('is-open');
                form.setAttribute('aria-hidden', 'true');
                var toggle = document.querySelector('[data-reply-toggle="' + parentId + '"]');
                if (toggle) {
                    toggle.setAttribute('aria-expanded', 'false');
                }
            }
        })
        .catch(function () {
            form.submit();
        })
        .finally(function () {
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.innerHTML = originalButtonText;
            }
        });
    });
})();