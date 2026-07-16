window.showAppToast = function(message, options) {
    if (!message) return;
    const config = options || {};
    const variant = config.variant || 'primary';
    const title = config.title || window.AppConfig.translations.clinicUpdate;
    const autohide = config.autohide !== false;
    const delay = Number(config.delay || 5000);
    let container = document.getElementById('notificationContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notificationContainer';
        container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = 'toast border-' + variant;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    const toastHeader = document.createElement('div');
    toastHeader.className = 'toast-header bg-' + variant + ' text-white';
    const icon = document.createElement('i');
    icon.className = 'bi bi-bell-fill me-2';
    const titleElement = document.createElement('strong');
    titleElement.className = 'me-auto';
    titleElement.textContent = title;
    const nowLabel = document.createElement('small');
    nowLabel.className = 'text-white-50';
    nowLabel.textContent = AppConfig.translations.justNow;
    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'btn-close btn-close-white';
    closeButton.setAttribute('data-bs-dismiss', 'toast');
    closeButton.setAttribute('aria-label', AppConfig.translations.close);
    toastHeader.appendChild(icon);
    toastHeader.appendChild(titleElement);
    toastHeader.appendChild(nowLabel);
    toastHeader.appendChild(closeButton);
    const toastBody = document.createElement('div');
    toastBody.className = 'toast-body bg-light';
    toastBody.textContent = String(message);
    toast.appendChild(toastHeader);
    toast.appendChild(toastBody);
    container.appendChild(toast);
    if (window.bootstrap && window.bootstrap.Toast) {
        const instance = window.bootstrap.Toast.getOrCreateInstance(toast, {
            autohide: autohide,
            delay: delay
        });
        toast.addEventListener('hidden.bs.toast', function() {
            toast.remove();
        });
        instance.show();
        return;
    }
    toast.classList.add('show');
    if (autohide) {
        window.setTimeout(function() {
            toast.remove();
        }, delay);
    }
};

document.addEventListener('DOMContentLoaded', function() {
    var App = window.AppConfig;
    if (!App || !App.isAuthenticated) return;

    var sidebar = document.getElementById('adminSidebar');
    var sidebarToggle = document.getElementById('adminSidebarToggle');
    var sidebarBackdrop = document.getElementById('adminSidebarBackdrop');
    var offcanvas = document.getElementById('messagesOffcanvas');
    var notificationsOffcanvas = document.getElementById('notificationsOffcanvas');
    var isAdmin = App.isAdmin;
    var conversationSelect = document.getElementById('conversationSelect');
    var conversationSearch = document.getElementById('conversationSearch');
    var conversationTypeFilter = document.getElementById('conversationTypeFilter');
    var conversationStatusFilter = document.getElementById('conversationStatusFilter');
    var recipientInput = document.getElementById('messageRecipientId');
    var notificationAudience = document.getElementById('notificationAudience');
    var selectedPatientsWrap = document.getElementById('selectedPatientsWrap');
    var filterNotificationAll = document.getElementById('filterNotificationAll');
    var filterNotificationCandidates = document.getElementById('filterNotificationCandidates');
    var selectAllNotificationPatients = document.getElementById('selectAllNotificationPatients');
    var clearAllNotificationPatients = document.getElementById('clearAllNotificationPatients');
    var refreshNotificationsBtn = document.getElementById('refreshNotificationsBtn');
    var markAllNotificationsReadBtn = document.getElementById('markAllNotificationsReadBtn');
    var notificationHistoryList = document.getElementById('notificationHistoryList');
    var notificationRecipientsList = document.getElementById('notificationRecipientsList');
    var pageCsrfToken = document.getElementById('csrf_token') ? document.getElementById('csrf_token').value : '';
    var selectedConversation = null;
    var allConversations = [];
    var activeNotificationRecipientFilter = 'all';

    function isDesktopViewport() {
        return window.innerWidth >= 1024;
    }

    function setSidebarState(openOnMobile) {
        if (!sidebar) return;
        if (isDesktopViewport()) {
            sidebar.classList.remove('is-open');
            sidebar.setAttribute('aria-hidden', 'false');
            if (sidebarBackdrop) {
                sidebarBackdrop.classList.add('hidden');
            }
            document.body.classList.remove('overflow-hidden');
            if (sidebarToggle) {
                sidebarToggle.setAttribute('aria-expanded', 'false');
            }
            return;
        }
        var shouldOpen = !!openOnMobile;
        sidebar.classList.toggle('is-open', shouldOpen);
        sidebar.setAttribute('aria-hidden', shouldOpen ? 'false' : 'true');
        if (sidebarBackdrop) {
            sidebarBackdrop.classList.toggle('hidden', !shouldOpen);
        }
        document.body.classList.toggle('overflow-hidden', shouldOpen);
        if (sidebarToggle) {
            sidebarToggle.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
        }
    }

    function syncSidebarStateForViewport() {
        if (!sidebar) return;
        var isOpen = sidebarToggle && sidebarToggle.getAttribute('aria-expanded') === 'true';
        setSidebarState(isOpen);
    }

    function toggleAdminSidebar(forceOpen) {
        if (!sidebar || isDesktopViewport()) return;
        var currentlyOpen = sidebar.classList.contains('is-open');
        var shouldOpen = typeof forceOpen === 'boolean' ? forceOpen : !currentlyOpen;
        setSidebarState(shouldOpen);
    }

    syncSidebarStateForViewport();

    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', function () {
            toggleAdminSidebar();
        });
    }

    if (sidebarBackdrop) {
        sidebarBackdrop.addEventListener('click', function () {
            toggleAdminSidebar(false);
        });
    }

    if (sidebar) {
        sidebar.querySelectorAll('a').forEach(function(link) {
            link.addEventListener('click', function () {
                if (!isDesktopViewport()) {
                    toggleAdminSidebar(false);
                }
            });
        });
    }

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            toggleAdminSidebar(false);
        }
    });

    window.addEventListener('resize', syncSidebarStateForViewport);

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function escapeAttribute(value) {
        return escapeHtml(value).replace(/`/g, '&#96;');
    }

    function linkifyText(value) {
        var text = String(value || '');
        var tokenPattern = /(https?:\/\/[^\s<]+|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})/gi;
        var html = '';
        var lastIndex = 0;
        text.replace(tokenPattern, function(match, _token, offset) {
            html += escapeHtml(text.slice(lastIndex, offset));
            if (/^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$/i.test(match)) {
                html += '<a href="mailto:' + escapeAttribute(match) + '" class="text-decoration-none">' + escapeHtml(match) + '</a>';
            } else {
                html += '<a href="' + escapeAttribute(match) + '" target="_blank" rel="noopener noreferrer" class="text-decoration-none">' + escapeHtml(match) + '</a>';
            }
            lastIndex = offset + match.length;
            return match;
        });
        html += escapeHtml(text.slice(lastIndex));
        return html.replace(/\n/g, '<br>');
    }

    function applyNotificationRecipientFilter(filterName) {
        activeNotificationRecipientFilter = filterName || 'all';
        document.querySelectorAll('.notification-recipient-item').forEach(function(node) {
            var statusValue = (node.dataset.status || '').toLowerCase();
            var shouldShow = activeNotificationRecipientFilter === 'all' || statusValue === 'candidate';
            node.classList.toggle('d-none', !shouldShow);
        });
        if (filterNotificationAll) {
            filterNotificationAll.classList.toggle('is-selected', activeNotificationRecipientFilter === 'all');
        }
        if (filterNotificationCandidates) {
            filterNotificationCandidates.classList.toggle('is-selected', activeNotificationRecipientFilter === 'candidate');
        }
    }

    function loadNotificationRecipients() {
        if (!notificationRecipientsList || !isAdmin) return;
        notificationRecipientsList.innerHTML = '<div class="text-muted small">' + App.translations.loading + '</div>';
        fetch('/api/notification_recipients')
            .then(function(response) { return response.json(); })
            .then(function(items) {
                if (!items || items.length === 0) {
                    notificationRecipientsList.innerHTML = '<div class="text-muted small">' + App.translations.noConversations + '</div>';
                    return;
                }
                notificationRecipientsList.innerHTML = items.map(function(item) {
                    var typeLabel = escapeHtml(String(item.patient_type || 'private').replace(/-/g, ' '));
                    var statusLabel = escapeHtml(String(item.status || 'ongoing').replace(/-/g, ' '));
                    var patientName = escapeHtml(item.patient_name || '');
                    var disabledAttr = item.has_login ? '' : 'disabled';
                    var mutedClass = item.has_login ? '' : ' opacity-50';
                    var noLogin = item.has_login ? '' : '<span class="d-block text-muted">' + App.translations.noLogin + '</span>';
                    return [
                        '<label class="notification-recipient-item d-flex align-items-start gap-2 py-1' + mutedClass + '" data-status="' + escapeHtml(item.status || '') + '" data-patient-type="' + escapeHtml(item.patient_type || '') + '">',
                            '<input type="checkbox" name="patient_ids" value="' + item.patient_id + '" class="form-check-input mt-1 notification-patient-check" ' + disabledAttr + '>',
                            '<span class="small">',
                                '<span class="fw-semibold">' + patientName + '</span>',
                                '<span class="badge bg-light text-dark border ms-1 text-capitalize">' + typeLabel + '</span>',
                                '<span class="badge bg-warning-subtle text-dark border ms-1 text-capitalize">' + statusLabel + '</span>',
                                noLogin,
                            '</span>',
                        '</label>'
                    ].join('');
                }).join('');
                applyNotificationRecipientFilter(activeNotificationRecipientFilter);
            })
            .catch(function() {
                notificationRecipientsList.innerHTML = '<div class="text-danger small">' + App.translations.error + '</div>';
            });
    }

    function updateNotificationBadges(unreadCount) {
        document.querySelectorAll('.notification-badge').forEach(function(node) {
            if (unreadCount > 0) {
                node.textContent = unreadCount > 99 ? '99+' : String(unreadCount);
            } else {
                node.remove();
            }
        });
        if (markAllNotificationsReadBtn) {
            markAllNotificationsReadBtn.disabled = unreadCount === 0;
        }
    }

    function submitNotificationRead(notificationId, markAll) {
        var body = new URLSearchParams();
        var markBtn = markAll ? document.getElementById('markAllNotificationsReadBtn') : null;
        if (markAll) {
            body.set('all', '1');
        } else if (notificationId) {
            body.append('notification_id', String(notificationId));
        }
        if (markBtn) { markBtn.disabled = true; }
        fetch('/api/notifications/mark_read', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': pageCsrfToken
            },
            body: body.toString()
        })
            .then(function(response) { return response.json(); })
            .then(function(data) {
                if (data.status === 'success') {
                    loadNotificationCenter();
                } else {
                    window.showAppToast(data.message || App.translations.error, {
                        variant: 'danger',
                        title: App.translations.error
                    });
                }
            })
            .catch(function() {
                window.showAppToast(App.translations.error, {
                    variant: 'danger',
                    title: App.translations.error
                });
            })
            .finally(function() {
                if (markBtn) { markBtn.disabled = false; }
            });
    }

    window.markNotificationRead = function(notificationId) {
        submitNotificationRead(notificationId, false);
    };

    function loadNotificationCenter() {
        if (!notificationHistoryList) return;
        notificationHistoryList.innerHTML = '<div class="text-muted small">' + App.translations.loading + '</div>';
        fetch('/api/notifications?all=1&mark_read=0')
            .then(function(response) { return response.json(); })
            .then(function(items) {
                var unreadCount = Array.isArray(items)
                    ? items.filter(function(item) { return Number(item.is_read || 0) === 0; }).length
                    : 0;
                updateNotificationBadges(unreadCount);
                if (!items || items.length === 0) {
                    notificationHistoryList.innerHTML = '<div class="text-muted small">' + App.translations.noNotifications + '</div>';
                    return;
                }
                notificationHistoryList.innerHTML = items.map(function(item) {
                    var category = item.category || 'system';
                    var categoryColors = {
                        'billing': 'bg-success',
                        'appointment': 'bg-primary',
                        'file_upload': 'bg-info text-dark',
                        'contact_inquiry': 'bg-warning text-dark',
                        'admin_broadcast': 'bg-secondary',
                        'system': 'bg-light text-dark',
};

// Dark mode toggle
(function() {
    var toggle = document.getElementById('themeToggle');
    var icon = document.getElementById('themeToggleIcon');
    var label = document.getElementById('themeToggleLabel');
    if (!toggle || !icon || !label) return;

    function applyDark(enabled) {
        document.documentElement.classList.toggle('dark', enabled);
        icon.className = enabled ? 'bi bi-sun-fill' : 'bi bi-moon-stars-fill';
        var lang = document.documentElement.dir === 'rtl' ? 'he' : 'en';
        label.textContent = enabled ? (lang === 'he' ? 'מצב בהיר' : 'Light Mode') : (lang === 'he' ? 'מצב כהה' : 'Dark Mode');
        try { localStorage.setItem('clinic_dark_mode', enabled ? '1' : '0'); } catch(e) {}
    }

    toggle.addEventListener('click', function() {
        var current = document.documentElement.classList.contains('dark');
        applyDark(!current);
    });

    var saved = null;
    try { saved = localStorage.getItem('clinic_dark_mode'); } catch(e) {}
    if (saved === '1') applyDark(true);
})();
                    var badgeClass = categoryColors[category] || 'bg-light text-dark';
                    var categoryLabel = {
                        'billing': App.translations.billing || 'Billing',
                        'appointment': App.translations.appointment || 'Appointment',
                        'file_upload': App.translations.fileUpload || 'File',
                        'contact_inquiry': App.translations.inquiry || 'Inquiry',
                        'admin_broadcast': App.translations.broadcast || 'Broadcast',
                        'system': App.translations.system || 'System',
                    }[category] || category;
                    var title = escapeHtml(item.title || App.translations.clinicUpdate);
                    var message = linkifyText(item.message || '');
                    var createdAt = escapeHtml(item.created_at || '');
                    var notificationId = Number(item.id || 0);
                    var isUnread = Number(item.is_read || 0) === 0;
                    var actionHtml = isUnread
                        ? '<button type="button" class="btn btn-outline-success btn-sm rounded-pill" onclick="markNotificationRead(' + notificationId + ')">' + App.translations.markAsSeen + '</button>'
                        : '<span class="badge bg-success-subtle text-success border">' + App.translations.seen + '</span>';
                    return [
                        '<div class="notification-history-item border rounded-3 p-2 ' + (isUnread ? 'border-primary-subtle bg-light-subtle' : '') + '">',
                            '<div class="d-flex justify-content-between align-items-start gap-2 mb-1">',
                                '<div class="fw-semibold text-dark">' + title + '</div>',
                                '<span class="badge ' + badgeClass + ' border rounded-pill text-uppercase small">' + categoryLabel + '</span>',
                            '</div>',
                            '<div class="text-muted mb-2" style="white-space:pre-wrap;">' + message + '</div>',
                            '<div class="d-flex justify-content-between align-items-center gap-2">',
                                '<div class="small text-secondary">' + createdAt + '</div>',
                                actionHtml,
                            '</div>',
                        '</div>'
                    ].join('');
                }).join('');
            })
            .catch(function() {
                notificationHistoryList.innerHTML = '<div class="text-danger small">' + App.translations.error + '</div>';
            });
    }

    function loadMessages() {
        var query = '';
        if (isAdmin) {
            var searchValue = conversationSearch ? conversationSearch.value.trim() : '';
            var typeValue = conversationTypeFilter ? conversationTypeFilter.value : 'all';
            var statusValue = conversationStatusFilter ? conversationStatusFilter.value : 'all';
            var params = new URLSearchParams();
            if (selectedConversation) params.set('conversation_with', selectedConversation);
            if (searchValue) params.set('q', searchValue);
            if (typeValue && typeValue !== 'all') params.set('patient_type', typeValue);
            if (statusValue && statusValue !== 'all') params.set('status', statusValue);
            query = params.toString() ? ('?' + params.toString()) : '';
        } else if (selectedConversation) {
            query = '?conversation_with=' + encodeURIComponent(selectedConversation);
        }
        fetch(App.endpoints.getMessages + query)
            .then(function(response) { return response.json(); })
            .then(function(payload) {
                var container = document.getElementById('messagesContainer');
                container.innerHTML = '';
                var messages = payload;
                if (isAdmin) {
                    var conversations = payload.conversations || [];
                    allConversations = conversations;
                    if (conversationSelect) {
                        conversationSelect.innerHTML = '';
                        if (allConversations.length === 0) {
                            conversationSelect.innerHTML = '<option value="">' + App.translations.noConversations + '</option>';
                        } else {
                            allConversations.forEach(function(conv) {
                                var option = document.createElement('option');
                                option.value = conv.user_id ? String(conv.user_id) : '';
                                option.disabled = !conv.can_message;
                                var unread = conv.unread_count ? ' (' + conv.unread_count + ' ' + App.translations.unread + ')' : '';
                                var locked = conv.can_message ? '' : ' (' + App.translations.noLogin + ')';
                                option.textContent = conv.patient_name + unread + locked;
                                conversationSelect.appendChild(option);
                            });
                        }
                    }
                    if (selectedConversation && !allConversations.some(function(c) { return c.user_id && String(c.user_id) === String(selectedConversation); })) {
                        selectedConversation = null;
                    }
                    var activeConversation = payload.active_conversation ? String(payload.active_conversation) : null;
                    if (!selectedConversation && activeConversation) {
                        selectedConversation = activeConversation;
                    }
                    if (!selectedConversation) {
                        var firstAvailable = allConversations.find(function(c) { return c.can_message && c.user_id; });
                        selectedConversation = firstAvailable ? String(firstAvailable.user_id) : null;
                    }
                    if (conversationSelect && selectedConversation) {
                        conversationSelect.value = selectedConversation;
                    }
                    if (recipientInput) {
                        recipientInput.value = selectedConversation || '';
                    }
                    messages = payload.messages || [];
                }
                if (messages.length === 0) {
                    container.innerHTML = '<div class="text-center py-4 text-muted small">' + App.translations.noMessages + '</div>';
                    return;
                }
                messages.forEach(function(msg) {
                    var isMine = msg.sender_id === App.userId;
                    var alignClass = isMine ? 'text-end' : 'text-start';
                    var bgClass = isMine ? 'bg-primary text-white' : 'bg-light border';
                    var senderName = isMine ? App.translations.you : (msg.sender_name || App.translations.systemAdmin);
                    container.innerHTML += [
                        '<div class="' + alignClass + ' mb-3">',
                            '<div class="smallest text-muted mb-1">' + senderName + '</div>',
                            '<span class="d-inline-block p-2 rounded-3 ' + bgClass + '" style="max-width: 85%; word-break: break-word;">' + msg.content + '</span>',
                            '<small class="text-muted d-block smallest mt-1">' + msg.timestamp + '</small>',
                        '</div>'
                    ].join('');
                });
                container.scrollTop = container.scrollHeight;
            });
    }

    function loadContactInquiries() {
        var list = document.getElementById('contactInquiriesList');
        if (!list) return;
        fetch('/api/contact_inquiries?limit=5')
            .then(function(r) { return r.json(); })
            .then(function(items) {
                if (!items || items.length === 0) {
                    list.innerHTML = '<div class="text-muted small">' + App.translations.noNotifications + '</div>';
                    return;
                }
                list.innerHTML = items.map(function(item) {
                    return '<div class="border rounded p-2 ' + (Number(item.is_read) ? '' : 'bg-warning-subtle') + '">' +
                        '<div class="fw-semibold small">' + escapeHtml(item.name || '') + '</div>' +
                        '<div class="small">' + escapeHtml((item.message || '').substring(0, 80)) + '</div>' +
                        '<div class="d-flex justify-content-between align-items-center">' +
                            '<span class="smallest text-muted">' + escapeHtml(item.created_at || '') + '</span>' +
                            (item.email ? '<span class="smallest text-muted">' + escapeHtml(item.email) + '</span>' : '') +
                        '</div>' +
                    '</div>';
                }).join('');
            })
            .catch(function() { list.innerHTML = '<div class="text-danger small">Error</div>'; });
    }

    if (offcanvas) {
        offcanvas.addEventListener('show.bs.offcanvas', function () {
            loadMessages();
            loadContactInquiries();
        });
        if (conversationSelect) {
            conversationSelect.addEventListener('change', function () {
                selectedConversation = conversationSelect.value || null;
                if (recipientInput) {
                    recipientInput.value = selectedConversation || '';
                }
                loadMessages();
            });
        }
        [conversationSearch, conversationTypeFilter, conversationStatusFilter].forEach(function(node) {
            if (!node) return;
            node.addEventListener('input', function () {
                selectedConversation = null;
                loadMessages();
            });
            node.addEventListener('change', function () {
                selectedConversation = null;
                loadMessages();
            });
        });
        document.getElementById('sendMessageForm').addEventListener('submit', function(e) {
            e.preventDefault();
            var content = document.getElementById('messageContent').value;
            var csrfToken = document.getElementById('csrf_token').value;
            var sendBtn = this.querySelector('button[type="submit"]');
            if (content.trim() !== '') {
                if (isAdmin && !selectedConversation) return;
                sendBtn.disabled = true;
                sendBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
                var formBody = 'content=' + encodeURIComponent(content)
                    + (isAdmin && selectedConversation ? '&recipient_id=' + encodeURIComponent(selectedConversation) : '');
                fetch(App.endpoints.sendMessage, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-CSRFToken': csrfToken
                    },
                    body: formBody
                })
                .then(function(response) { return response.json(); })
                .then(function(data) {
                    if (data.status === 'success') {
                        document.getElementById('messageContent').value = '';
                        loadMessages();
                    }
                })
                .finally(function() {
                    sendBtn.disabled = false;
                    sendBtn.innerHTML = '<i class="bi bi-send-fill"></i>';
                });
            }
        });
    }

    function toggleNotificationRecipientsVisibility() {
        if (!notificationAudience || !selectedPatientsWrap) return;
        selectedPatientsWrap.classList.toggle('d-none', notificationAudience.value !== 'selected');
    }

    if (notificationAudience) {
        notificationAudience.addEventListener('change', toggleNotificationRecipientsVisibility);
        toggleNotificationRecipientsVisibility();
    }

    if (filterNotificationAll) {
        filterNotificationAll.addEventListener('click', function () {
            applyNotificationRecipientFilter('all');
        });
    }

    if (filterNotificationCandidates) {
        filterNotificationCandidates.addEventListener('click', function () {
            applyNotificationRecipientFilter('candidate');
        });
    }

    if (selectAllNotificationPatients) {
        selectAllNotificationPatients.addEventListener('click', function () {
            document.querySelectorAll('.notification-recipient-item:not(.d-none) .notification-patient-check:not([disabled])').forEach(function(node) {
                node.checked = true;
            });
        });
    }

    if (clearAllNotificationPatients) {
        clearAllNotificationPatients.addEventListener('click', function () {
            document.querySelectorAll('.notification-patient-check').forEach(function(node) {
                node.checked = false;
            });
        });
    }

    if (refreshNotificationsBtn) {
        refreshNotificationsBtn.addEventListener('click', loadNotificationCenter);
    }

    if (markAllNotificationsReadBtn) {
        markAllNotificationsReadBtn.addEventListener('click', function () {
            submitNotificationRead(null, true);
        });
    }

    if (notificationsOffcanvas) {
        notificationsOffcanvas.addEventListener('show.bs.offcanvas', function () {
            loadNotificationCenter();
            loadNotificationRecipients();
        });
    }

    /* Notification polling */
    function checkNotifications() {
        fetch('/api/notifications')
            .then(function(response) { return response.json(); })
            .then(function(data) {
                if (data.length > 0) {
                    document.querySelectorAll('.notification-badge').forEach(function(node) { node.remove(); });
                    var container = document.getElementById('notificationContainer');
                    data.forEach(function(notification) {
                        var title = notification.title || App.translations.newActivity;
                        var toastHTML = [
                            '<div class="toast show border-primary" role="alert" aria-live="assertive" aria-atomic="true">',
                                '<div class="toast-header bg-primary text-white">',
                                    '<i class="bi bi-bell-fill me-2"></i>',
                                    '<strong class="me-auto">' + title + '</strong>',
                                    '<small class="text-white-50">' + App.translations.justNow + '</small>',
                                    '<button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast" aria-label="' + App.translations.close + '"></button>',
                                '</div>',
                                '<div class="toast-body bg-light">',
                                    notification.message,
                                '</div>',
                            '</div>'
                        ].join('');
                        container.insertAdjacentHTML('beforeend', toastHTML);
                        var newToast = container.lastElementChild;
                        setTimeout(function() {
                            newToast.classList.remove('show');
                            setTimeout(function() { newToast.remove(); }, 500);
                        }, 10000);
                    });
                }
            })
            .catch(function(error) { console.error('Error fetching notifications:', error); });
    }
    setInterval(checkNotifications, 10000);
    checkNotifications();
});

/* Clipboard blocker + autocomplete off */
document.addEventListener('DOMContentLoaded', function() {
    var App = window.AppConfig;
    if (!App) return;
    var endpoint = (document.body.dataset.endpoint || '').trim();
    if (endpoint === 'login') return;
    var userRole = document.body.dataset.userRole || 'guest';
    if (!App.isAuthenticated || userRole === 'patient') {
        var blockClipboard = function(event) {
            var eventTarget = event.target;
            if (eventTarget && typeof eventTarget.closest === 'function' && eventTarget.closest('[data-allow-clipboard="true"]')) return;
            event.preventDefault();
        };
        document.addEventListener('copy', blockClipboard, true);
        document.addEventListener('cut', blockClipboard, true);
        document.addEventListener('paste', blockClipboard, true);
    } else if (userRole === 'admin') {
        console.log('[Clinic] Admin clipboard access enabled (role: admin)');
        document.addEventListener('contextmenu', function(e) {
            e.stopImmediatePropagation();
        }, true);
    }
    document.querySelectorAll('form').forEach(function(form) {
        form.setAttribute('autocomplete', 'off');
    });
    document.querySelectorAll('input, textarea').forEach(function(field) {
        var fieldType = (field.getAttribute('type') || '').toLowerCase();
        if (fieldType === 'hidden' || fieldType === 'checkbox' || fieldType === 'radio' || fieldType === 'submit' || fieldType === 'button') return;
        field.setAttribute('autocomplete', 'off');
        field.setAttribute('autocorrect', 'off');
        field.setAttribute('autocapitalize', 'none');
        field.setAttribute('spellcheck', 'false');
    });
});

/* ── Bootstrap client-side form validation ────────────────────── */
(function() {
    'use strict';
    var forms = document.querySelectorAll('.needs-validation');
    Array.prototype.slice.call(forms).forEach(function(form) {
        form.addEventListener('submit', function(event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            }
            form.classList.add('was-validated');
        }, false);
    });
})();

/* ── Reusable confirmation modal ──────────────────────────────── */
document.addEventListener('click', function(e) {
    var trigger = e.target.closest('[data-confirm-modal]');
    if (!trigger) return;
    e.preventDefault();
    var message = trigger.getAttribute('data-confirm-message') || 'Are you sure?';
    var action = trigger.getAttribute('data-confirm-action') || trigger.getAttribute('href') || '';
    var method = trigger.getAttribute('data-confirm-method') || 'POST';
    var hasReason = trigger.hasAttribute('data-confirm-reason');
    var btnColor = trigger.getAttribute('data-confirm-btn') || 'danger';
    var confirmModal = document.getElementById('confirmModal');
    if (!confirmModal) return;
    document.getElementById('confirmModalMessage').textContent = message;
    var confirmBtn = document.getElementById('confirmModalBtn');
    confirmBtn.className = 'btn btn-' + btnColor;
    var reasonWrap = document.getElementById('confirmModalReasonWrap');
    if (hasReason) {
        reasonWrap.classList.remove('d-none');
    } else {
        reasonWrap.classList.add('d-none');
    }
    confirmBtn.onclick = function() {
        if (hasReason) {
            var reason = document.getElementById('confirmModalReason');
            if (!reason.value.trim()) { reason.focus(); return; }
        }
        if (trigger.tagName === 'A') {
            window.location.href = action;
        } else if (trigger.tagName === 'FORM') {
            if (hasReason) {
                var reasonVal = document.getElementById('confirmModalReason').value.trim();
                var reasonInput = document.createElement('input');
                reasonInput.type = 'hidden';
                reasonInput.name = 'deletion_reason';
                reasonInput.value = reasonVal;
                trigger.appendChild(reasonInput);
            }
            trigger.submit();
        } else {
            var form = document.createElement('form');
            form.method = method;
            form.action = action;
            var csrf = document.createElement('input');
            csrf.type = 'hidden';
            csrf.name = 'csrf_token';
            csrf.value = (window.AppConfig && AppConfig.csrfToken) || '';
            form.appendChild(csrf);
            if (hasReason) {
                var reasonVal = document.getElementById('confirmModalReason').value.trim();
                var reasonInput = document.createElement('input');
                reasonInput.type = 'hidden';
                reasonInput.name = 'deletion_reason';
                reasonInput.value = reasonVal;
                form.appendChild(reasonInput);
            }
            document.body.appendChild(form);
            form.submit();
        }
        var modal = bootstrap.Modal.getInstance(confirmModal);
        if (modal) modal.hide();
    };
    var modal = new bootstrap.Modal(confirmModal);
    modal.show();
    confirmModal.addEventListener('keydown', function trap(e) {
        if (e.key !== 'Tab') return;
        var focusable = confirmModal.querySelectorAll('button, input, textarea, select, [tabindex]:not([tabindex="-1"])');
        if (!focusable.length) return;
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
});

/* ── Dark mode toggle ─────────────────────────────────────────── */
(function() {
    var STORAGE_KEY = 'clinic-theme';
    var htmlEl = document.documentElement;
    var savedTheme = (function() {
        try { return localStorage.getItem(STORAGE_KEY); } catch(e) { return null; }
    })();
    var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    var theme = savedTheme || (prefersDark ? 'dark' : 'light');
    htmlEl.setAttribute('data-bs-theme', theme);
    function updateToggleUI() {
        var btn = document.getElementById('themeToggle');
        var icon = document.getElementById('themeToggleIcon');
        var label = document.getElementById('themeToggleLabel');
        if (!icon || !label) return;
        if (htmlEl.getAttribute('data-bs-theme') === 'dark') {
            icon.className = 'bi bi-sun-fill';
            label.textContent = (window.AppConfig && AppConfig.translations) ? AppConfig.translations.lightMode : 'Light Mode';
        } else {
            icon.className = 'bi bi-moon-stars-fill';
            label.textContent = (window.AppConfig && AppConfig.translations) ? AppConfig.translations.darkMode : 'Dark Mode';
        }
        if (btn && btn.classList) btn.classList.remove('hidden');
    }
    document.addEventListener('DOMContentLoaded', function() {
        var toggleBtn = document.getElementById('themeToggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', function() {
                var current = htmlEl.getAttribute('data-bs-theme');
                var next = current === 'dark' ? 'light' : 'dark';
                htmlEl.setAttribute('data-bs-theme', next);
                try { localStorage.setItem(STORAGE_KEY, next); } catch(e) {}
                updateToggleUI();
            });
        }
        updateToggleUI();
    });
})();
