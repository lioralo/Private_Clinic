document.addEventListener('DOMContentLoaded', function() {
    var Cal = window.Cal;
    var I18N = window.I18N;
    var csrfToken = Cal.csrfToken;
    var isAdmin = Cal.isAdmin;

    var APPOINTMENT_CONFIG = {
        kind: 'appointment',
        title: function(p) { return p.is_recurring ? I18N.editRecurringTitle : I18N.editMeetingTitle; },
        errorTitle: I18N.editFailed,
        errorMessage: I18N.missingAppointmentId,
        deleteEndpoint: function(p) { return '/api/calendar/appointment/' + p.source_id + '/delete'; },
        updateEndpoint: function(p) { return '/api/calendar/appointment/' + p.source_id + '/update'; },
        deleteBtnText: I18N.deleteMeeting,
        confirmText: I18N.saveLabel || I18N.ok,
        extraBodyHtml: function(p) {
            var recurringInfo = p.is_recurring
                ? '<div class="alert alert-info py-1 px-2 small mb-2">' + I18N.recurringMeeting + '</div>'
                : '';
            var patientLinkHtml = (isAdmin && p.patient_id)
                ? '<div class="mb-2"><a class="btn btn-sm btn-outline-secondary" href="/patient/' + p.patient_id + '?tab=appointments" target="_blank" rel="noopener noreferrer">' + I18N.openPatientProfile + '</a></div>'
                : '';
            return patientLinkHtml + recurringInfo;
        },
        fields: [
            { id: 'editMeetingDate', label: I18N.date, type: 'date', dataKey: 'date', postKey: 'date' },
            { id: 'editMeetingTime', label: I18N.startTime, type: 'time', dataKey: 'time', postKey: 'time' },
            { id: 'editMeetingEndTime', label: I18N.endTime, type: 'time', dataKey: 'end_time', postKey: 'end_time' },
            { id: 'editMeetingTitle', label: I18N.meetingTitle, type: 'text', dataKey: 'meeting_title', postKey: 'meeting_title' },
            { id: 'editSaveToGoogleBtn', elementType: 'html', html: '<button type="button" class="btn btn-sm btn-outline-secondary mb-2" id="editSaveToGoogleBtn"><i class="bi bi-calendar-plus me-1"></i>' + I18N.addToGoogleCalendar + '</button>' },
            { id: 'editMeetingType', label: I18N.meetingType, elementType: 'select', dataKey: 'meeting_type', postKey: 'meeting_type',
              options: [{ value: 'in-person', label: I18N.inPerson }, { value: 'zoom', label: I18N.zoomLabel }, { value: 'google-meet', label: 'Google Meet' }] },
            { id: 'editMeetingLink', label: I18N.meetingLink, type: 'url', dataKey: 'meeting_link', postKey: 'meeting_link' }
        ],
        postShow: function(p) {
            var typeSelect = document.getElementById('editMeetingType');
            if (typeSelect) typeSelect.value = p.meeting_type || 'in-person';
            var gcalBtn = document.getElementById('editSaveToGoogleBtn');
            if (gcalBtn) {
                gcalBtn.onclick = function() {
                    Cal.openGoogleCalendarEvent(
                        document.getElementById('editMeetingDate').value,
                        document.getElementById('editMeetingTime').value,
                        document.getElementById('editMeetingEndTime').value,
                        document.getElementById('editMeetingTitle').value,
                        document.getElementById('editMeetingLink').value
                    );
                };
            }
        },
        extraPostParams: function(p, formData) {
            var selectedType = formData.meeting_type;
            return {
                save_to_google: '0',
                meeting_platform: (['zoom', 'google-meet'].indexOf(selectedType) !== -1 ? selectedType : ''),
                scope: 'all',
                occurrence_date: p.occurrence_date || p.date || ''
            };
        },
        onSave: function(p, formData) {
            if (!p.is_recurring) return;
            return Cal.showScopeModal({
                title: I18N.editRecurringTitle,
                message: I18N.editRecurringApplyScope,
                options: [
                    { value: 'one', label: I18N.editOneOccurrence },
                    { value: 'upcoming', label: I18N.editThisAndUpcoming },
                    { value: 'all', label: I18N.editAllOccurrences }
                ],
                confirmText: I18N.saveLabel || 'Save',
                confirmClass: 'btn-primary'
            }).then(function(scope) {
                if (!scope) return false;
                formData.scope = scope;
                formData.occurrence_date = p.occurrence_date || p.date || '';
            });
        },
        onDelete: function(p, defaultFn) {
            if (!p.is_recurring) return;
            var occDate = p.occurrence_date || p.date || '';
            Cal.modalRoot.addEventListener('hidden.bs.modal', function onHidden() {
                Cal.modalRoot.removeEventListener('hidden.bs.modal', onHidden);
                Cal.showScopeModal({
                    title: I18N.deleteRecurringTitle,
                    message: I18N.deleteRecurringQuestion,
                    options: [
                        { value: 'one', label: I18N.deleteOneOccurrence },
                        { value: 'upcoming', label: I18N.deleteThisAndUpcoming },
                        { value: 'all', label: I18N.deleteAllOccurrences }
                    ],
                    confirmText: I18N.deleteLabel,
                    confirmClass: 'btn-danger'
                }).then(function(scope) {
                    if (!scope) return;
                    var body = new URLSearchParams({ scope: scope });
                    if (scope === 'one' || scope === 'upcoming') body.set('occurrence_date', occDate);
                    defaultFn(body);
                });
            });
            Cal.actionModal.hide();
            return true;
        }
    };

    var GROUP_CONFIG = {
        kind: 'group',
        title: 'Edit Group Session',
        errorTitle: 'Edit Failed',
        errorMessage: 'Missing group session id.',
        deleteEndpoint: function(p) { return '/api/groups/sessions/' + p.source_id + '/delete'; },
        updateEndpoint: function(p) { return '/api/groups/sessions/' + p.source_id + '/update'; },
        deleteBtnText: 'Delete Group Session',
        confirmText: 'Save',
        fields: [
            { id: 'editGroupDate', label: 'Date', type: 'date', dataKey: 'date', postKey: 'session_date' },
            { id: 'editGroupStart', label: 'Start Time', type: 'time', dataKey: 'time', postKey: 'session_time' },
            { id: 'editGroupEnd', label: 'End Time', type: 'time', dataKey: 'end_time', postKey: 'end_time' },
            { id: 'editGroupTitle', label: 'Title', type: 'text', dataKey: 'meeting_title', postKey: 'title', altDataKey: 'title' },
            { id: 'editGroupFacilitator', label: 'Facilitator', type: 'text', dataKey: 'facilitator', postKey: 'facilitator' },
            { id: 'editGroupMeetingType', label: 'Meeting Type', elementType: 'select', dataKey: 'meeting_type', postKey: 'meeting_type',
              options: [{ value: 'in-person', label: 'In-person' }, { value: 'zoom', label: 'Zoom' }, { value: 'google-meet', label: 'Google Meet' }] },
            { id: 'editGroupMeetingLink', label: 'Meeting Link', type: 'url', dataKey: 'meeting_link', postKey: 'meeting_link' }
        ],
        postShow: function(p) {
            var typeSelect = document.getElementById('editGroupMeetingType');
            if (typeSelect) typeSelect.value = p.meeting_type || 'in-person';
        }
    };

    var BLOCK_CONFIG = {
        kind: 'block',
        title: 'Edit Block',
        errorTitle: 'Edit Failed',
        errorMessage: 'Missing block id.',
        deleteEndpoint: function(p) { return '/api/calendar/block/' + p.source_id + '/delete'; },
        updateEndpoint: function(p) { return '/api/calendar/block/' + p.source_id + '/update'; },
        deleteBtnText: 'Delete',
        confirmText: 'Save',
        fields: [
            { id: 'editBlockDate', label: 'Date', type: 'date', dataKey: 'date', postKey: 'blocked_date' },
            { id: 'editBlockTime', label: 'Start Time', type: 'time', dataKey: 'time', postKey: 'blocked_time' },
            { id: 'editBlockEndTime', label: 'End Time', type: 'time', dataKey: 'end_time', postKey: 'end_time' },
            { id: 'editBlockType', label: 'Type', elementType: 'select', dataKey: 'block_type', postKey: 'block_type',
              options: [{ value: 'blocked', label: 'Blocked' }] },
            { id: 'editBlockTitle', label: 'Title', type: 'text', dataKey: 'title', postKey: 'title' },
            { id: 'editBlockPrivate', label: 'Hide title from patients', elementType: 'checkbox', dataKey: 'is_private', postKey: 'is_private' }
        ],
        postShow: function(p) {
            var typeSelect = document.getElementById('editBlockType');
            if (typeSelect) typeSelect.value = 'blocked';
        }
    };

    function openSlotEditor(payload, config) {
        if (!payload || !payload.source_id) {
            Cal.showActionModal({ title: typeof config.errorTitle === 'function' ? config.errorTitle(payload) : config.errorTitle, message: typeof config.errorMessage === 'function' ? config.errorMessage(payload) : config.errorMessage });
            return;
        }

        Cal.modalTitle.textContent = typeof config.title === 'function' ? config.title(payload) : config.title;

        var html = config.extraBodyHtml ? config.extraBodyHtml(payload) : '';
        config.fields.forEach(function(f) {
            if (f.elementType === 'html') {
                html += f.html;
                return;
            }
            if (f.elementType === 'checkbox') {
                var checked = payload[f.dataKey] ? ' checked' : '';
                html += '<div class="form-check mt-2">';
                html += '<input class="form-check-input" type="checkbox" id="' + f.id + '"' + checked + '>';
                html += '<label class="form-check-label small" for="' + f.id + '">' + (typeof f.label === 'function' ? f.label(payload) : f.label) + '</label>';
                html += '</div>';
                return;
            }
            html += '<div class="mb-2"><label class="form-label small">' + (typeof f.label === 'function' ? f.label(payload) : f.label) + '</label>';
            if (f.elementType === 'select') {
                html += '<select class="form-select form-select-sm" id="' + f.id + '">';
                f.options.forEach(function(opt) {
                    html += '<option value="' + opt.value + '">' + opt.label + '</option>';
                });
                html += '</select>';
            } else {
                var value = f.altDataKey ? (payload[f.dataKey] || payload[f.altDataKey] || '') : (payload[f.dataKey] || '');
                html += '<input type="' + (f.type || 'text') + '" class="form-control form-control-sm" id="' + f.id + '" value="' + Cal.escapeHtml(String(value)) + '">';
            }
            html += '</div>';
        });

        var confirmText = typeof config.confirmText === 'function' ? config.confirmText(payload) : config.confirmText;
        html += '<button type="button" class="btn btn-sm btn-outline-danger mt-2" id="editorDeleteBtn">' + (typeof config.deleteBtnText === 'function' ? config.deleteBtnText(payload) : config.deleteBtnText) + '</button>';

        Cal.modalBody.innerHTML = html;

        Cal.modalConfirmBtn.textContent = confirmText;
        Cal.modalConfirmBtn.className = 'btn btn-primary';
        Cal.modalCancelBtn.classList.remove('d-none');
        Cal.actionModal.show();

        if (config.postShow) config.postShow(payload);

        function collectFormData() {
            var data = {};
            config.fields.forEach(function(f) {
                if (!f.postKey || f.elementType === 'html') return;
                var el = document.getElementById(f.id);
                if (!el) return;
                if (f.elementType === 'checkbox') {
                    data[f.postKey] = el.checked ? '1' : '0';
                } else {
                    data[f.postKey] = el.value || '';
                }
            });
            if (config.extraPostParams) {
                var extra = config.extraPostParams(payload, data);
                for (var k in extra) {
                    if (extra.hasOwnProperty(k)) data[k] = extra[k];
                }
            }
            return data;
        }

        var deleteBtn = document.getElementById('editorDeleteBtn');
        if (deleteBtn) {
            deleteBtn.onclick = function() {
                function doDelete(bodyParams) {
                    fetch(config.deleteEndpoint(payload), {
                        method: 'POST',
                        headers: bodyParams ? { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/x-www-form-urlencoded' } : { 'X-CSRFToken': csrfToken },
                        body: bodyParams
                    }).then(function(r) { return r.json(); }).then(function(data) {
                        if (data.status === 'success') {
                            if (!config._deleteHandled) Cal.actionModal.hide();
                            Cal.loadSnapshot();
                            Cal.loadBookingManagement();
                            if (data.message) Cal.showActionModal({ title: 'Deleted with Warning', message: data.message });
                        } else {
                            Cal.showActionModal({ title: 'Delete Failed', message: data.message || 'Could not delete.' });
                        }
                    }).catch(function() {
                        Cal.showActionModal({ title: 'Delete Failed', message: 'Could not delete.' });
                    });
                }

                if (config.onDelete) {
                    var handled = config.onDelete(payload, doDelete);
                    if (handled) return;
                }
                doDelete();
            };
        }

        Cal.modalConfirmBtn.onclick = function() {
            var formData = collectFormData();

            function doSave(finalData) {
                fetch(config.updateEndpoint(payload), {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: new URLSearchParams(finalData)
                }).then(function(r) { return r.json(); }).then(function(data) {
                    if (data.status === 'success') {
                        Cal.actionModal.hide();
                        Cal.loadSnapshot();
                        Cal.loadBookingManagement();
                        if (data.message) Cal.showActionModal({ title: 'Saved with Warning', message: data.message });
                    } else {
                        Cal.showActionModal({ title: I18N.saveFailed, message: data.message || I18N.couldNotSaveMeetingChanges });
                    }
                }).catch(function() {
                    Cal.showActionModal({ title: I18N.saveFailed, message: I18N.couldNotSaveMeetingChanges });
                });
            }

            if (config.onSave) {
                var result = config.onSave(payload, formData);
                if (result === false) return;
                if (result && typeof result.then === 'function') {
                    result.then(function() {
                        doSave(formData);
                    }).catch(function() {
                        Cal.showActionModal({ title: I18N.saveFailed, message: I18N.couldNotSaveMeetingChanges });
                    });
                    return;
                }
            }
            doSave(formData);
        };
    }

    Cal.openAppointmentEditor = function(payload) {
        openSlotEditor(payload, APPOINTMENT_CONFIG);
    };

    Cal.openGroupSessionEditor = function(payload) {
        openSlotEditor(payload, GROUP_CONFIG);
    };

    Cal.openBlockEditor = function(payload) {
        openSlotEditor(payload, BLOCK_CONFIG);
    };

    Cal.openBookingEditor = function(payload) {
        if (!payload) {
            return;
        }
        if (payload.kind === 'appointment') {
            Cal.openAppointmentEditor(payload);
            return;
        }
        if (payload.kind === 'group_session') {
            Cal.openGroupSessionEditor(payload);
            return;
        }
        if (payload.kind === 'block') {
            Cal.openBlockEditor(payload);
        }
    };

    Cal.deleteBookingItem = function(payload) {
        if (!payload || !payload.source_id) {
            return;
        }

        var endpointByKind = {
            appointment: '/api/calendar/appointment/' + payload.source_id + '/delete',
            group_session: '/api/groups/sessions/' + payload.source_id + '/delete',
            block: '/api/calendar/block/' + payload.source_id + '/delete'
        };
        var endpoint = endpointByKind[payload.kind];
        if (!endpoint) {
            return;
        }

        if (payload.kind === 'appointment' && payload.is_recurring) {
            var occDate = payload.occurrence_date || payload.date || '';
            Cal.showScopeModal({
                title: I18N.deleteRecurringTitle,
                message: I18N.deleteRecurringQuestion,
                options: [
                    { value: 'one', label: I18N.deleteOneOccurrence },
                    { value: 'upcoming', label: I18N.deleteThisAndUpcoming },
                    { value: 'all', label: I18N.deleteAllOccurrences }
                ],
                confirmText: I18N.deleteLabel,
                confirmClass: 'btn-danger'
            }).then(function(scope) {
                if (!scope) return;
                var formBody = new URLSearchParams({ scope: scope });
                if (scope === 'one' || scope === 'upcoming') formBody.set('occurrence_date', occDate);
                fetch(endpoint, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: formBody
                }).then(function(r) { return r.json(); }).then(function(data) {
                    if (data.status === 'success') {
                        Cal.loadSnapshot();
                        Cal.loadBookingManagement();
                    } else {
                        Cal.showActionModal({ title: I18N.deleteFailed, message: data.message || I18N.couldNotDeleteMeeting });
                    }
                }).catch(function() {
                    Cal.showActionModal({ title: I18N.deleteFailed, message: I18N.couldNotDeleteMeeting });
                });
            });
            return;
        }

        Cal.showActionModal({
            title: 'Delete Booking',
            message: 'Delete this item?',
            confirmText: 'Delete',
            confirmClass: 'btn-danger',
            showCancel: true
        }).then(function(confirmed) {
            if (!confirmed) {
                return;
            }
            fetch(endpoint, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken }
            }).then(function(r) { return r.json(); }).then(function(data) {
                if (data.status === 'success') {
                    Cal.loadSnapshot();
                    Cal.loadBookingManagement();
                } else {
                    Cal.showActionModal({ title: 'Delete Failed', message: data.message || 'Could not delete item.' });
                }
            }).catch(function() {
                Cal.showActionModal({ title: 'Delete Failed', message: 'Could not delete item.' });
            });
        });
    };

    Cal.toGoogleDateTime = function(dateValue, timeValue) {
        var cleanDate = String(dateValue || '').replace(/-/g, '');
        var cleanTime = String(timeValue || '').replace(':', '');
        return cleanDate + 'T' + cleanTime + '00';
    };

    Cal.openGoogleCalendarEvent = function(dateValue, startTimeValue, endTimeValue, titleValue, meetingLinkValue) {
        if (!dateValue || !startTimeValue || !endTimeValue) {
            return;
        }
        var text = encodeURIComponent((titleValue || '').trim() || '### private meeting');
        var details = encodeURIComponent((meetingLinkValue || '').trim() || 'Therapy meeting');
        var dates = Cal.toGoogleDateTime(dateValue, startTimeValue) + '/' + Cal.toGoogleDateTime(dateValue, endTimeValue);
        var url = 'https://calendar.google.com/calendar/render?action=TEMPLATE&text=' + text + '&details=' + details + '&dates=' + dates;
        window.open(url, '_blank', 'noopener,noreferrer');
    };
});
