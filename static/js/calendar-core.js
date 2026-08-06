document.addEventListener('DOMContentLoaded', function() {
    window.Cal = window.Cal || {};
    var Cal = window.Cal;
    var I18N = window.I18N;

    var contextNode = document.getElementById('calendarContext');
    Cal.isAdmin = contextNode && contextNode.dataset.isAdmin === '1';
    Cal.canSelfSchedule = contextNode && contextNode.dataset.canSelfSchedule === '1';
    Cal.csrfToken = document.getElementById('csrf_token') ? document.getElementById('csrf_token').value : null;
    var selectedSlotText = document.getElementById('selectedSlotText');
    var bookingDate = document.getElementById('bookingDate');
    var bookingTime = document.getElementById('bookingTime');
    var bookingEndTime = document.getElementById('bookingEndTime');
    var bookingPatient = document.getElementById('bookingPatient');
    var bookingEndTimeInput = document.getElementById('bookingEndTimeInput');
    var meetingTypeSelect = document.getElementById('meetingTypeSelect');
    var meetingTitleInput = document.getElementById('meetingTitleInput');
    var bookingStatusHint = document.getElementById('bookingStatusHint');
    var bookingTypeSelect = document.getElementById('bookingTypeSelect');
    var createVacancyBtn = document.getElementById('createVacancyBtn');
    var specialMetaWrap = document.getElementById('specialMetaWrap');
    var specialPatternSelect = document.getElementById('specialPatternSelect');
    var specialRepeatUntilWrap = document.getElementById('specialRepeatUntilWrap');
    var specialRepeatUntilInput = document.getElementById('specialRepeatUntilInput');
    var specialTitleWrap = document.getElementById('specialTitleWrap');
    var specialTitleInput = document.getElementById('specialTitleInput');
    var bookSlotSubmitBtn = document.getElementById('bookSlotSubmitBtn');
    var meetingLinkInput = document.getElementById('meetingLinkInput');
    var meetingPlatformHidden = document.getElementById('meetingPlatformHidden');
    var otherNameWrap = document.getElementById('otherNameWrap');
    var otherNameInput = document.getElementById('otherNameInput');
    var filterButtons = document.querySelectorAll('.filter-chip');
    var availableSlotsContainer = document.getElementById('availableSlots');
    var availableCount = document.getElementById('availableCount');
    var availableWeekSelect = document.getElementById('availableWeekSelect');
    var followUpAlerts = document.getElementById('followUpAlerts');
    var ongoingThisWeek = document.getElementById('ongoingThisWeek');
    var calendarWeekLabel = document.getElementById('calendarWeekLabel');
    var calendarPrevWeek = document.getElementById('calendarPrevWeek');
    var calendarTodayWeek = document.getElementById('calendarTodayWeek');
    var calendarNextWeek = document.getElementById('calendarNextWeek');
    var fridaySpecials = document.getElementById('fridaySpecials');
    var saturdaySpecials = document.getElementById('saturdaySpecials');
    var bookingTabTrigger = document.getElementById('booking-tab');
    var bookingManagementMode = document.getElementById('bookingManagementMode');
    var bookingManagementBody = document.getElementById('bookingManagementBody');
    var createPublicBookingLinkBtn = document.getElementById('createPublicBookingLinkBtn');
    var publicBookingLinkInput = document.getElementById('publicBookingLinkInput');
    var copyPublicBookingLinkBtn = document.getElementById('copyPublicBookingLinkBtn');
    var sendPublicBookingMailBtn = document.getElementById('sendPublicBookingMailBtn');
    var blockRecurrencePattern = document.getElementById('blockRecurrencePattern');
    var blockRepeatUntilWrap = document.getElementById('blockRepeatUntilWrap');
    var blockRepeatUntilInput = document.getElementById('blockRepeatUntilInput');
    var bookingPane = document.getElementById('booking-pane');

    var modalRoot = document.getElementById('calendarActionModal');
    var modalTitle = document.getElementById('calendarActionModalTitle');
    var modalBody = document.getElementById('calendarActionModalBody');
    var modalConfirmBtn = document.getElementById('calendarModalConfirmBtn');
    var modalCancelBtn = document.getElementById('calendarModalCancelBtn');
    var actionModal = modalRoot ? new bootstrap.Modal(modalRoot) : null;

    Cal.modalRoot = modalRoot;
    Cal.modalTitle = modalTitle;
    Cal.modalBody = modalBody;
    Cal.modalConfirmBtn = modalConfirmBtn;
    Cal.modalCancelBtn = modalCancelBtn;
    Cal.actionModal = actionModal;

    Cal.bookingDate = bookingDate;
    Cal.bookingTime = bookingTime;
    Cal.bookingEndTime = bookingEndTime;
    Cal.bookingEndTimeInput = bookingEndTimeInput;
    Cal.bookingDateInput = document.getElementById('bookingDateInput');
    Cal.bookingTimeInput = document.getElementById('bookingTimeInput');
    Cal.bookingPatient = bookingPatient;
    Cal.bookingTypeSelect = bookingTypeSelect;
    Cal.bookingStatusHint = bookingStatusHint;
    Cal.meetingTypeSelect = meetingTypeSelect;
    Cal.meetingTitleInput = meetingTitleInput;
    Cal.meetingLinkInput = meetingLinkInput;
    Cal.meetingPlatformHidden = meetingPlatformHidden;
    Cal.specialMetaWrap = specialMetaWrap;
    Cal.specialPatternSelect = specialPatternSelect;
    Cal.specialRepeatUntilWrap = specialRepeatUntilWrap;
    Cal.specialRepeatUntilInput = specialRepeatUntilInput;
    Cal.specialTitleWrap = specialTitleWrap;
    Cal.specialTitleInput = specialTitleInput;
    Cal.bookSlotSubmitBtn = bookSlotSubmitBtn;
    Cal.createVacancyBtn = createVacancyBtn;
    Cal.otherNameWrap = otherNameWrap;
    Cal.otherNameInput = otherNameInput;
    Cal.selectedSlotText = selectedSlotText;
    Cal.filterButtons = filterButtons;
    Cal.availableSlotsContainer = availableSlotsContainer;
    Cal.availableCount = availableCount;
    Cal.availableWeekSelect = availableWeekSelect;
    Cal.followUpAlerts = followUpAlerts;
    Cal.ongoingThisWeek = ongoingThisWeek;
    Cal.calendarWeekLabel = calendarWeekLabel;
    Cal.calendarPrevWeek = calendarPrevWeek;
    Cal.calendarTodayWeek = calendarTodayWeek;
    Cal.calendarNextWeek = calendarNextWeek;
    Cal.fridaySpecials = fridaySpecials;
    Cal.saturdaySpecials = saturdaySpecials;
    Cal.bookingTabTrigger = bookingTabTrigger;
    Cal.bookingManagementMode = bookingManagementMode;
    Cal.bookingManagementBody = bookingManagementBody;
    Cal.createPublicBookingLinkBtn = createPublicBookingLinkBtn;
    Cal.publicBookingLinkInput = publicBookingLinkInput;
    Cal.copyPublicBookingLinkBtn = copyPublicBookingLinkBtn;
    Cal.sendPublicBookingMailBtn = sendPublicBookingMailBtn;
    Cal.blockRecurrencePattern = blockRecurrencePattern;
    Cal.blockRepeatUntilWrap = blockRepeatUntilWrap;
    Cal.blockRepeatUntilInput = blockRepeatUntilInput;
    Cal.bookingPane = bookingPane;

    Cal.nowWeekAnchor = null;
    Cal.currentWeekStart = null;
    Cal.activeFilter = 'all';
    Cal.activeManagementMode = 'upcoming';
    Cal.followUpExpanded = false;

    if (modalRoot) {
        modalRoot.addEventListener('hidden.bs.modal', function() {
            document.querySelectorAll('.modal-backdrop').forEach(function(el) { el.remove(); });
            document.body.classList.remove('modal-open');
            document.body.style.overflow = '';
            document.body.style.paddingRight = '';
        });
    }

    Cal.initBookingSectionToggles = function() {
        if (!bookingPane) return;
        var sectionCards = bookingPane.querySelectorAll(':scope > .card');
        sectionCards.forEach(function(card) {
            var header = card.querySelector(':scope > .card-header');
            var body = card.querySelector(':scope > .card-body');
            var title = header ? header.querySelector('h6') : null;
            if (!header || !body || !title) return;

            body.classList.add('d-none');
            title.style.cursor = 'pointer';
            title.setAttribute('role', 'button');
            title.setAttribute('tabindex', '0');
            title.setAttribute('aria-expanded', 'false');

            var icon = title.querySelector('.booking-toggle-icon');
            if (!icon) {
                icon = document.createElement('i');
                icon.className = 'bi bi-chevron-down ms-2 booking-toggle-icon';
                title.appendChild(icon);
            }

            var toggle = function() {
                var isHidden = body.classList.contains('d-none');
                body.classList.toggle('d-none', !isHidden);
                title.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
                icon.className = isHidden
                    ? 'bi bi-chevron-up ms-2 booking-toggle-icon'
                    : 'bi bi-chevron-down ms-2 booking-toggle-icon';
            };

            title.addEventListener('click', toggle);
            title.addEventListener('keydown', function(event) {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    toggle();
                }
            });
        });
    };

    Cal.initBookingSectionToggles();

    Cal.pad2 = function(v) {
        return String(v).padStart(2, '0');
    };

    Cal.getWeekStartString = function(dateObj) {
        var d = new Date(dateObj);
        var day = d.getDay();
        d.setDate(d.getDate() - day);
        d.setHours(0, 0, 0, 0);
        return d.getFullYear() + '-' + Cal.pad2(d.getMonth() + 1) + '-' + Cal.pad2(d.getDate());
    };

    Cal.parseIsoDate = function(iso) {
        var parts = String(iso).split('-').map(Number);
        return new Date(parts[0], (parts[1] || 1) - 1, parts[2] || 1);
    };

    Cal.formatWeekLabel = function(isoStart) {
        var start = Cal.parseIsoDate(isoStart);
        var end = new Date(start);
        end.setDate(end.getDate() + 4);
        var fmt = new Intl.DateTimeFormat(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
        return fmt.format(start) + ' - ' + fmt.format(end);
    };

    Cal.shiftWeek = function(isoStart, weeksDelta) {
        var d = Cal.parseIsoDate(isoStart);
        d.setDate(d.getDate() + (weeksDelta * 7));
        return Cal.getWeekStartString(d);
    };

    Cal.syncWeekFromAnchor = function() {
        Cal.currentWeekStart = Cal.nowWeekAnchor;
        if (Cal.calendarWeekLabel) {
            Cal.calendarWeekLabel.textContent = Cal.formatWeekLabel(Cal.currentWeekStart);
        }
        if (Cal.availableWeekSelect) {
            Cal.availableWeekSelect.value = Cal.nowWeekAnchor;
        }
    };

    Cal.refreshWeekOptions = function() {
        if (!Cal.availableWeekSelect) return;
        var options = [];
        for (var i = -2; i <= 8; i += 1) {
            var weekStart = Cal.shiftWeek(Cal.nowWeekAnchor, i);
            var labelPrefix = i === 0 ? I18N.currentWeek : (i > 0 ? '+' + i + ' ' + I18N.weekLabelPlus : Math.abs(i) + ' ' + I18N.weekLabelMinus);
            options.push('<option value="' + weekStart + '">' + labelPrefix + ' · ' + Cal.formatWeekLabel(weekStart) + '</option>');
        }
        Cal.availableWeekSelect.innerHTML = options.join('');
        Cal.availableWeekSelect.value = Cal.nowWeekAnchor;
    };

    Cal.goToWeek = function(isoStart) {
        Cal.nowWeekAnchor = isoStart;
        Cal.syncWeekFromAnchor();
        Cal.refreshWeekOptions();
        Cal.calendar.gotoDate(Cal.parseIsoDate(isoStart));
        Cal.loadSnapshot();
    };

    Cal._modalQueue = Promise.resolve();

    Cal.showActionModal = function(config) {
        var _show = function() {
            if (!Cal.actionModal) {
                return Promise.resolve(true);
            }

            return new Promise(function(resolve) {
                Cal.modalTitle.textContent = config.title || I18N.notice;
                Cal.modalBody.innerHTML = config.message || '';
                Cal.modalConfirmBtn.textContent = config.confirmText || I18N.ok;
                Cal.modalConfirmBtn.className = 'btn ' + (config.confirmClass || 'btn-primary');

                if (config.showCancel) {
                    Cal.modalCancelBtn.classList.remove('d-none');
                    Cal.modalCancelBtn.textContent = config.cancelText || I18N.cancel;
                } else {
                    Cal.modalCancelBtn.classList.add('d-none');
                }

                Cal.modalConfirmBtn.onclick = null;

                var resolved = false;
                var result = false;
                var confirmHandler = function() {
                    if (resolved) return;
                    resolved = true;
                    result = true;
                    Cal.actionModal.hide();
                };
                var hiddenHandler = function() {
                    Cal.modalConfirmBtn.removeEventListener('click', confirmHandler);
                    Cal.modalRoot.removeEventListener('hidden.bs.modal', hiddenHandler);
                    if (!resolved) {
                        resolved = true;
                        result = false;
                    }
                    resolve(result);
                };

                Cal.modalConfirmBtn.addEventListener('click', confirmHandler);
                Cal.modalRoot.addEventListener('hidden.bs.modal', hiddenHandler);
                Cal.actionModal.show();
            });
        };
        return Cal._modalQueue = Cal._modalQueue.then(_show, _show);
    };

    Cal.escapeHtml = function(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    };

    Cal.showScopeModal = function(config) {
        var _show = function() {
            if (!Cal.actionModal) return Promise.resolve(null);
            return new Promise(function(resolve) {
                Cal.modalTitle.textContent = config.title || I18N.notice;
                var optionsHtml = (config.options || []).map(function(opt, i) {
                    return '<div class="form-check mb-2">' +
                        '<input class="form-check-input" type="radio" name="calScopeChoice" id="calScope_' + i + '" value="' + Cal.escapeHtml(opt.value) + '" ' + (i === 0 ? 'checked' : '') + '>' +
                        '<label class="form-check-label" for="calScope_' + i + '">' + Cal.escapeHtml(opt.label) + '</label>' +
                    '</div>';
                }).join('');
                Cal.modalBody.innerHTML = (config.message ? '<p class="small text-muted mb-3">' + Cal.escapeHtml(config.message) + '</p>' : '') + optionsHtml;
                Cal.modalConfirmBtn.textContent = config.confirmText || I18N.ok;
                Cal.modalConfirmBtn.className = 'btn ' + (config.confirmClass || 'btn-primary');
                Cal.modalCancelBtn.classList.remove('d-none');
                Cal.modalCancelBtn.textContent = config.cancelText || I18N.cancel;
                Cal.modalConfirmBtn.onclick = null;
                Cal.actionModal.show();
                var resolved = false;
                var confirmHandler = function() {
                    if (resolved) return;
                    resolved = true;
                    var sel = Cal.modalBody.querySelector('input[name="calScopeChoice"]:checked');
                    Cal.actionModal.hide();
                    resolve(sel ? sel.value : null);
                };
                var hiddenHandler = function() {
                    Cal.modalConfirmBtn.removeEventListener('click', confirmHandler);
                    Cal.modalRoot.removeEventListener('hidden.bs.modal', hiddenHandler);
                    if (!resolved) { resolved = true; resolve(null); }
                };
                Cal.modalConfirmBtn.addEventListener('click', confirmHandler);
                Cal.modalRoot.addEventListener('hidden.bs.modal', hiddenHandler);
            });
        };
        return Cal._modalQueue = Cal._modalQueue.then(_show, _show);
    };
});
