// Interface de modais de confirmação/aviso e envio de formulários com PUT/DELETE
(function () {
    'use strict';

    // ---------- Modal ----------
    const modal = document.getElementById('se-modal');
    const titleEl = document.getElementById('se-modal-title');
    const textEl = document.getElementById('se-modal-text');
    const iconEl = document.getElementById('se-modal-icon');
    const confirmBtn = document.getElementById('se-modal-confirm');
    const cancelBtn = document.getElementById('se-modal-cancel');
    let resolver = null;
    let lastFocused = null;

    // Fecha o modal e devolve o resultado (true = confirmou, false = cancelou)
    function closeModal(result) {
        if (!modal || modal.hidden) return;
        modal.hidden = true;
        document.body.classList.remove('se-modal-open');
        if (lastFocused && typeof lastFocused.focus === 'function') lastFocused.focus();
        const done = resolver;
        resolver = null;
        if (done) done(result);
    }

    // Abre o modal com título, mensagem e botões; retorna uma Promise<boolean>
    function openModal(options) {
        return new Promise(function (resolve) {
            if (resolver) closeModal(false);
            resolver = resolve;
            lastFocused = document.activeElement;
            titleEl.textContent = options.title;
            textEl.textContent = options.message;
            confirmBtn.textContent = options.confirmText;
            cancelBtn.textContent = options.cancelText || 'Cancelar';
            cancelBtn.hidden = !options.showCancel;
            confirmBtn.className = 'se-groups-button ' + (options.danger ? 'se-modal-danger' : 'se-groups-button-primary');
            modal.dataset.tone = options.danger ? 'danger' : 'info';
            iconEl.innerHTML = '<i class="fa-solid ' + (options.danger ? 'fa-triangle-exclamation' : (options.showCancel ? 'fa-circle-question' : 'fa-circle-info')) + '" aria-hidden="true"></i>';
            modal.hidden = false;
            document.body.classList.add('se-modal-open');
            // Em ações destrutivas o foco inicial fica em "Cancelar" para evitar confirmação acidental
            (options.showCancel && options.danger ? cancelBtn : confirmBtn).focus();
        });
    }

    // API pública usada por outras páginas (ex.: SEModal.alert na tela de despesas)
    window.SEModal = {
        confirm: function (options) {
            if (!modal) return Promise.resolve(window.confirm(options.message));
            return openModal({
                title: options.title || 'Confirmar ação',
                message: options.message,
                confirmText: options.confirmText || 'Confirmar',
                cancelText: options.cancelText || 'Cancelar',
                danger: Boolean(options.danger),
                showCancel: true,
            });
        },
        alert: function (message, title) {
            if (!modal) { window.alert(message); return Promise.resolve(true); }
            return openModal({ title: title || 'Aviso', message: message, confirmText: 'Entendi', danger: false, showCancel: false });
        },
    };

    if (modal) {
        confirmBtn.addEventListener('click', function () { closeModal(true); });
        cancelBtn.addEventListener('click', function () { closeModal(false); });
        modal.addEventListener('click', function (event) {
            if (event.target.hasAttribute('data-se-modal-close')) closeModal(false);
        });
        // Escape cancela e Tab fica preso dentro do modal
        document.addEventListener('keydown', function (event) {
            if (modal.hidden) return;
            if (event.key === 'Escape') { event.preventDefault(); closeModal(false); return; }
            if (event.key !== 'Tab') return;
            const buttons = [cancelBtn, confirmBtn].filter(function (btn) { return !btn.hidden; });
            const first = buttons[0];
            const last = buttons[buttons.length - 1];
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        });
    }

    // ---------- PUT / DELETE via fetch ----------

    // Lê um cookie pelo nome (usado para obter o token CSRF quando o form não o contém)
    function readCookie(name) {
        const match = document.cookie.split('; ').find(function (row) { return row.indexOf(name + '=') === 0; });
        return match ? decodeURIComponent(match.split('=').slice(1).join('=')) : '';
    }

    // Trata a resposta do servidor: navega para o destino em JSON ou troca a tela pelo HTML recebido
    async function handleResponse(response) {
        // Redirecionamento automático (ex.: sessão expirada levando ao login)
        if (response.redirected) { window.location.assign(response.url); return; }
        const type = response.headers.get('Content-Type') || '';
        if (type.indexOf('application/json') !== -1) {
            const data = await response.json();
            if (data.redirect_url) { window.location.assign(data.redirect_url); return; }
        }
        if (!response.ok) {
            await window.SEModal.alert('Não foi possível concluir a ação (erro ' + response.status + '). Atualize a página e tente novamente.', 'Algo deu errado');
            return;
        }
        // Página renderizada com erros de validação: substitui a tela atual mantendo a mesma URL
        if (type.indexOf('text/html') !== -1) {
            const html = await response.text();
            document.open();
            document.write(html);
            document.close();
            return;
        }
        window.location.reload();
    }

    // Envia o formulário com o método HTTP real (PUT ou DELETE) e o token CSRF
    async function sendWithMethod(form, submitter, method) {
        const url = form.getAttribute('action') || window.location.href;
        const fields = new FormData(form);
        // O botão que disparou o envio também contribui com name/value (ex.: action=promote)
        if (submitter && submitter.name) fields.append(submitter.name, submitter.value);
        const tokenInput = form.querySelector('input[name="csrfmiddlewaretoken"]');
        const token = tokenInput ? tokenInput.value : readCookie('csrftoken');

        form.dataset.seBusy = '1';
        form.querySelectorAll('button[type="submit"], button:not([type])').forEach(function (btn) { btn.disabled = true; });
        try {
            const response = await fetch(url, {
                method: method,
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': token,
                    'X-Requested-With': 'XMLHttpRequest',
                    'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                    'Accept': 'application/json, text/html',
                },
                body: new URLSearchParams(fields).toString(),
            });
            await handleResponse(response);
        } catch (error) {
            await window.SEModal.alert('Não foi possível conectar ao servidor. Verifique sua conexão e tente novamente.', 'Sem conexão');
        } finally {
            delete form.dataset.seBusy;
            form.querySelectorAll('button[type="submit"], button:not([type])').forEach(function (btn) { btn.disabled = false; });
        }
    }

    // Formulários já confirmados no modal que seguem o envio nativo (POST/GET)
    const confirmedForms = new WeakSet();

    // Intercepta todo envio: aplica data-confirm (modal) e data-method (PUT/DELETE)
    document.addEventListener('submit', function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        const submitter = event.submitter || null;
        // O botão pode sobrescrever método e mensagem do formulário (vários botões no mesmo form)
        const method = String((submitter && submitter.dataset.method) || form.dataset.method || form.method || 'post').toUpperCase();
        const source = (submitter && submitter.dataset.confirm) ? submitter : form;
        const message = source.dataset.confirm;
        const usesVerb = method === 'PUT' || method === 'DELETE';

        if (!usesVerb && !message) return;
        if (!usesVerb && confirmedForms.has(form)) { confirmedForms.delete(form); return; }

        event.preventDefault();
        if (form.dataset.seBusy === '1') return;

        const run = function () {
            if (usesVerb) {
                sendWithMethod(form, submitter, method);
            } else {
                confirmedForms.add(form);
                form.requestSubmit(submitter || undefined);
            }
        };

        if (!message) { run(); return; }
        window.SEModal.confirm({
            title: source.dataset.confirmTitle || 'Confirmar ação',
            message: message,
            confirmText: source.dataset.confirmOk || 'Confirmar',
            danger: source.dataset.confirmDanger === 'true',
        }).then(function (accepted) { if (accepted) run(); });
    });
})();
