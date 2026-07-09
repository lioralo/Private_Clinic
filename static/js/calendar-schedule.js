document.addEventListener('DOMContentLoaded', function() {
    var Cal = window.Cal;
    var I18N = window.I18N;
    var csrfToken = Cal.csrfToken;
    var isAdmin = Cal.isAdmin;

    Cal.renderBookingManagement = function(items) {
        if (!Cal.bookingManagementBody) {
            return;
        }
        if (!items || !items.length) {
            Cal.bookingManagementBody.innerHTML = '<tr><td colspan="6" class="text-muted small">No bookings found in this range.</td></tr>';
            return;
        }

        Cal.bookingManagementBody.innerHTML = items.map(function(item) {
            var details = [];
            if (item.meeting_type) {
                details.push(item.meeting_type);
            }
            if (item.status) {
                details.push(item.status);
            }
            if (item.is_recurring) {
                details.push('REC');
            }
            var escaped = encodeURIComponent(JSON.stringify({
                kind: item.kind,
                source_id: item.source_id || item.id,
                patient_id: item.patient_id,
                date: item.date,
                occurrence_date: item.date || '',
                time: item.time,
                end_time: item.end_time,
                meeting_type: item.meeting_type,
                meeting_link: item.meeting_link,
                meeting_title: item.title || item.meeting_title,
                title: item.title,
                facilitator: item.facilitator,
                is_recurring: item.is_recurring,
                is_private: item.is_private,
                block_type: item.block_type
            }));
            return '<tr>' +
                '<td>' + item.date + '</td>' +
                '<td>' + item.time + ' - ' + item.end_time + '</td>' +
                '<td>' + (item.type_label || item.kind) + '</td>' +
                '<td>' + (item.title || '') + '</td>' +
                '<td class="small text-muted">' + details.join(' · ') + '</td>' +
                '<td class="text-end">' +
                    '<button type="button" class="btn btn-sm btn-outline-primary me-1 manage-edit" data-item="' + escaped + '">Edit</button>' +
                    '<button type="button" class="btn btn-sm btn-outline-danger manage-delete" data-item="' + escaped + '">Delete</button>' +
                '</td>' +
            '</tr>';
        }).join('');

        Cal.bookingManagementBody.querySelectorAll('.manage-edit').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var payload = JSON.parse(decodeURIComponent(this.dataset.item || ''));
                Cal.openBookingEditor(payload);
            });
        });

        Cal.bookingManagementBody.querySelectorAll('.manage-delete').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var payload = JSON.parse(decodeURIComponent(this.dataset.item || ''));
                Cal.deleteBookingItem(payload);
            });
        });
    };

    Cal.loadBookingManagement = function() {
        if (!isAdmin || !Cal.bookingManagementBody) {
            return;
        }
        fetch('/api/calendar/bookings?mode=' + encodeURIComponent(Cal.activeManagementMode))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                Cal.renderBookingManagement(data.items || []);
            })
            .catch(function() {
                Cal.bookingManagementBody.innerHTML = '<tr><td colspan="6" class="text-danger small">Failed loading bookings.</td></tr>';
            });
    };

    var vacanciesContainer = document.getElementById('vacanciesContainer');
    var vacancyCount = document.getElementById('vacancyCount');

    Cal.doDeleteVacancy = function(id, kind) {
        if (!confirm('Remove this vacancy slot?')) return;
        fetch('/api/calendar/vacancy/' + id + '/delete', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ kind: kind || 'one-time' })
        }).then(function(r) { return r.json(); }).then(function(data) {
            if (data.status === 'success') {
                Cal.loadSnapshot();
                Cal.loadVacancies();
                Cal.loadVacancySlots();
            } else {
                alert(data.message || 'Delete failed.');
            }
        }).catch(function() {
            alert('Network error.');
        });
    };

    Cal.renderVacancies = function(items) {
        if (!vacanciesContainer) return;
        if (vacancyCount) vacancyCount.textContent = items.filter(function(i) { return i.status === 'available' || i.kind === 'weekly'; }).length;
        if (!items || !items.length) {
            vacanciesContainer.innerHTML = '<div class="small text-muted">No open vacancy slots.</div>';
            return;
        }
        vacanciesContainer.innerHTML = items.map(function(item) {
            var isWeekly = item.kind === 'weekly';
            var isOpen = item.status === 'available' || isWeekly;
            var statusBadge = '<span class="badge bg-secondary">Booked</span>';
            if (isWeekly) {
                statusBadge = '<span class="badge bg-success">Recurring Weekly</span>';
            } else if (isOpen) {
                statusBadge = '<span class="badge bg-success">Open</span>';
            } else if (item.booked_by_name) {
                statusBadge = '<span class="badge bg-secondary">Booked · ' + item.booked_by_name + '</span>';
            }
            var occupyBtn = (isOpen && item.kind !== 'weekly')
                ? '<button type="button" class="btn btn-sm btn-outline-primary vac-occupy" data-item="' + encodeURIComponent(JSON.stringify(item)) + '"><i class="bi bi-person-check"></i> Occupy</button>'
                : '';
            var deleteBtn = '<button type="button" class="btn btn-sm btn-outline-danger vac-del" data-id="' + item.id + '" data-kind="' + (item.kind || 'one-time') + '"><i class="bi bi-trash"></i></button>';
            return '<div class="border rounded-3 p-2 mb-2 d-flex justify-content-between align-items-center flex-wrap gap-2">' +
                '<div>' +
                    '<span class="small fw-semibold">' + item.date + ' ' + item.time + '–' + item.end_time + '</span>' +
                    '<span class="small text-muted ms-2">' + item.duration_minutes + ' min</span>' +
                    '<div class="mt-1">' + statusBadge + '</div>' +
                '</div>' +
                '<div class="d-flex gap-1">' +
                    occupyBtn + deleteBtn +
                '</div>' +
            '</div>';
        }).join('');

        vacanciesContainer.querySelectorAll('.vac-occupy').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var item = JSON.parse(decodeURIComponent(this.dataset.item || '{}'));
                var name = prompt('Enter name to occupy:\n' + item.time + ' - ' + item.end_time + ' (' + item.duration_minutes + ' min)');
                if (!name) return;
                fetch('/api/calendar/vacancy/' + item.id + '/occupy', {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: new URLSearchParams({ occupant_name: name })
                }).then(function(r) { return r.json(); }).then(function(data) {
                    if (data.status === 'success') {
                        Cal.loadSnapshot();
                        Cal.loadVacancies();
                        Cal.loadVacancySlots();
                        Cal.loadBookingManagement();
                    } else {
                        alert(data.message || 'Failed.');
                    }
                }).catch(function() { alert('Network error.'); });
            });
        });

        vacanciesContainer.querySelectorAll('.vac-del').forEach(function(btn) {
            btn.addEventListener('click', function() {
                Cal.doDeleteVacancy(this.dataset.id, this.dataset.kind);
            });
        });
    };

    Cal.loadVacancies = function() {
        if (!isAdmin || !vacanciesContainer) return;
        fetch('/api/calendar/vacancies')
            .then(function(r) { return r.json(); })
            .then(function(data) { Cal.renderVacancies(data.items || []); })
            .catch(function() {
                if (vacanciesContainer) vacanciesContainer.innerHTML = '<div class="small text-danger">Failed loading vacancies.</div>';
            });
    };

    function resetVacancyForm() {
        var form = document.getElementById('vacancyForm');
        if (form) form.reset();
        var editId = document.getElementById('vacancyEditId');
        if (editId) editId.value = '';
        var submitBtn = document.getElementById('vacancySubmitBtn');
        if (submitBtn) submitBtn.textContent = 'Add Vacant Slot';
        var cancelBtn = document.getElementById('vacancyCancelEditBtn');
        if (cancelBtn) cancelBtn.classList.add('d-none');
    }

    function fillVacancyFormForEdit(id, kind, dateVal, timeVal, endVal) {
        document.getElementById('vacancyEditId').value = id;
        document.getElementById('vacancySlotDate').value = dateVal;
        document.getElementById('vacancySlotTime').value = timeVal;
        document.getElementById('vacancySlotEnd').value = endVal;
        document.getElementById('vacancySlotPattern').value = kind;
        document.getElementById('vacancySubmitBtn').textContent = 'Update Vacant Slot';
        document.getElementById('vacancySubmitBtn').style.background = '#0d6efd';
        document.getElementById('vacancyCancelEditBtn').classList.remove('d-none');
        document.getElementById('vacancy-pane').scrollIntoView({ behavior: 'smooth' });
    }

    if (document.getElementById('vacancyCancelEditBtn')) {
        document.getElementById('vacancyCancelEditBtn').addEventListener('click', function() {
            resetVacancyForm();
            document.getElementById('vacancySubmitBtn').style.background = '#10b981';
        });
    }

    var vacancySlotsBody = document.getElementById('vacancySlotsBody');
    var vacancyForm = document.getElementById('vacancyForm');

    Cal.loadVacancySlots = function() {
        if (!isAdmin || !vacancySlotsBody) return;
        fetch('/api/calendar/vacancies')
            .then(function(r) { return r.json(); })
            .then(function(data) { Cal.renderVacancySlotsTable(data.items || []); })
            .catch(function() {
                if (vacancySlotsBody) vacancySlotsBody.innerHTML = '<tr><td colspan="6" class="text-danger small">Failed loading vacancies.</td></tr>';
            });
    };

    Cal.renderVacancySlotsTable = function(items) {
        if (!vacancySlotsBody) return;
        if (!items || !items.length) {
            vacancySlotsBody.innerHTML = '<tr><td colspan="6" class="text-muted small">No vacant slots defined.</td></tr>';
            return;
        }
        vacancySlotsBody.innerHTML = items.map(function(item) {
            var isWeekly = item.kind === 'weekly';
            var isOpen = item.status === 'available' || (isWeekly && item.status === 'available');
            var dateLabel = isWeekly ? item.date : (item.date || '');
            var timeLabel = item.time + (item.end_time ? '–' + item.end_time : '');
            var durationLabel = item.duration_minutes + ' min';
            var statusBadge = '<span class="badge bg-secondary border">Booked</span>';
            if (isOpen && isWeekly) {
                statusBadge = '<span class="badge bg-success border">Weekly Open</span>';
            } else if (isOpen) {
                statusBadge = '<span class="badge bg-success border">Open</span>';
            } else if (item.booked_by_name) {
                statusBadge = '<span class="badge bg-secondary border">Booked · ' + Cal.escapeHtml(item.booked_by_name) + '</span>';
            }
            var actions = '<div class="d-flex gap-1 justify-content-end">' +
                (isOpen
                    ? '<button type="button" class="btn btn-sm btn-outline-primary vacancy-edit" data-id="' + item.id + '" data-kind="' + (isWeekly ? 'weekly' : 'one-time') + '" data-date="' + Cal.escapeHtml(item.date) + '" data-time="' + item.time + '" data-end="' + (item.end_time || '') + '" data-duration="' + item.duration_minutes + '"><i class="bi bi-pencil"></i></button>'
                    : '') +
                '<button type="button" class="btn btn-sm btn-outline-danger vacancy-delete" data-id="' + item.id + '" data-kind="' + (isWeekly ? 'weekly' : 'one-time') + '"><i class="bi bi-trash"></i></button>' +
                '</div>';
            return '<tr><td class="small">' + Cal.escapeHtml(dateLabel) + '</td><td class="small">' + Cal.escapeHtml(timeLabel) + '</td><td class="small">' + durationLabel + '</td><td>' + statusBadge + '</td><td class="small">' + Cal.escapeHtml(item.booked_by_name || '') + '</td><td class="text-end">' + actions + '</td></tr>';
        }).join('');

        vacancySlotsBody.querySelectorAll('.vacancy-edit').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var id = this.dataset.id;
                var kind = this.dataset.kind;
                var dateVal = this.dataset.date;
                var timeVal = this.dataset.time;
                var endVal = this.dataset.end;
                fillVacancyFormForEdit(id, kind, dateVal, timeVal, endVal);
            });
        });

        vacancySlotsBody.querySelectorAll('.vacancy-delete').forEach(function(btn) {
            btn.addEventListener('click', function() {
                Cal.doDeleteVacancy(this.dataset.id, this.dataset.kind);
            });
        });
    };

    if (vacancyForm) {
        vacancyForm.addEventListener('submit', function(e) {
            e.preventDefault();
            var editId = document.getElementById('vacancyEditId').value;
            var formData = new FormData(vacancyForm);
            var url = editId ? '/api/calendar/vacancy/' + editId + '/update' : '/api/calendar/vacancy';
            fetch(url, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken },
                body: new URLSearchParams(formData)
            }).then(function(r) { return r.json(); }).then(function(data) {
                if (data.status === 'success') {
                    resetVacancyForm();
                    Cal.loadSnapshot();
                    Cal.loadVacancySlots();
                } else {
                    alert(data.message || 'Failed.');
                }
            }).catch(function() {
                alert('Network error.');
            });
        });
    }

    Cal.nowWeekAnchor = window.CALENDAR_CONFIG ? window.CALENDAR_CONFIG.initialWeekStart : null;
    if (!Cal.nowWeekAnchor || Cal.nowWeekAnchor === 'null') {
        Cal.nowWeekAnchor = Cal.getWeekStartString(new Date());
    }

    var calendarEl = document.getElementById('weeklyCalendar');

    Cal.calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'timeGridWeek',
        direction: document.documentElement.dir,
        height: 'auto',
        expandRows: true,
        contentHeight: 'auto',
        firstDay: 0,
        hiddenDays: [5, 6],
        slotMinTime: '08:00:00',
        slotMaxTime: '20:00:00',
        slotLabelFormat: { hour: '2-digit', minute: '2-digit', hour12: false },
        eventTimeFormat: { hour: '2-digit', minute: '2-digit', hour12: false },
        allDaySlot: false,
        nowIndicator: true,
        selectable: true,
        eventContent: function(arg) {
            var props = arg.event.extendedProps || {};
            var meta = props.meta || {};
            var platform = meta.meeting_platform || '';
            var mtype = meta.meeting_type || '';
            var recurringTag = meta.is_recurring ? '<span class="badge bg-light text-dark border me-1">REC</span>' : '';
            var displayLabel = (meta.type === 'appointment')
                ? (meta.patient_name || meta.meeting_title || '')
                : (meta.patient_name || arg.event.title || '');
            var safePrimaryLabel = Cal.escapeHtml(displayLabel);
            var icon = '';
            if (platform === 'zoom' || mtype === 'zoom') {
                icon = '<i class="bi bi-camera-video-fill me-1" title="Zoom meeting"></i>';
            } else if (platform === 'google-meet' || mtype === 'google-meet') {
                icon = '<i class="bi bi-camera-video me-1" title="Google Meet"></i>';
            }
            var timeText = arg.timeText ? '<div class="fc-event-time">' + arg.timeText + '</div>' : '';
            var titleText = '<div class="fc-event-title fc-event-title-primary" title="' + safePrimaryLabel + '">' + recurringTag + icon + '<span class="fc-event-patient-name">' + safePrimaryLabel + '</span></div>';
            return { html: '<div class="fc-event-main-frame">' + timeText + titleText + '</div>' };
        },
        selectMinDistance: 0,
        selectLongPressDelay: 0,
        selectOverlap: false,
        slotDuration: '00:30:00',
        selectMirror: true,
        dayHeaderFormat: { weekday: 'short', month: '2-digit', day: '2-digit' },
        headerToolbar: false,
        visibleRange: function() {
            var start = Cal.parseIsoDate(Cal.nowWeekAnchor);
            var endExclusive = new Date(start);
            endExclusive.setDate(endExclusive.getDate() + 5);
            return { start: start, end: endExclusive };
        },
        datesSet: function(info) {
            var start = new Date(info.start);
            var yyyy = start.getFullYear();
            var mm = String(start.getMonth() + 1).padStart(2, '0');
            var dd = String(start.getDate()).padStart(2, '0');
            Cal.currentWeekStart = yyyy + '-' + mm + '-' + dd;
            Cal.calendarWeekLabel.textContent = Cal.formatWeekLabel(Cal.currentWeekStart);
            Cal.loadSnapshot();
        },
        select: function(info) {
            var start = info.start;
            var end = info.end;
            var date = start.toISOString().slice(0, 10);
            var time = start.toTimeString().slice(0, 5);
            var durationMinutes = Math.max(30, Math.round((end - start) / 60000));
            Cal.setSelectedSlot(date, time, durationMinutes);
            if (Cal.bookingTabTrigger) {
                bootstrap.Tab.getOrCreateInstance(Cal.bookingTabTrigger).show();
            }
            Cal.calendar.unselect();
        },
        dateClick: function(info) {
            var clicked = info.date;
            Cal.setSelectedSlot(clicked.toISOString().slice(0, 10), clicked.toTimeString().slice(0, 5), 60);
            if (Cal.bookingTabTrigger) {
                bootstrap.Tab.getOrCreateInstance(Cal.bookingTabTrigger).show();
            }
        },
        eventClick: function(info) {
            var props = info.event.extendedProps || {};
            var meta = props.meta || {};

            if (meta.type === 'appointment') {
                if (!meta.can_edit && !meta.can_delete) {
                    Cal.showActionModal({ title: 'Not Allowed', message: 'You cannot edit this meeting.' });
                    return;
                }
                Cal.openAppointmentEditor({
                    kind: 'appointment',
                    source_id: props.appointment_id || meta.appointment_id,
                    patient_id: meta.patient_id,
                    date: info.event.start ? info.event.start.toISOString().slice(0, 10) : '',
                    occurrence_date: info.event.start ? info.event.start.toISOString().slice(0, 10) : '',
                    time: info.event.start ? info.event.start.toTimeString().slice(0, 5) : '',
                    end_time: info.event.end ? info.event.end.toTimeString().slice(0, 5) : '',
                    meeting_type: meta.meeting_type || 'in-person',
                    meeting_link: meta.meeting_link || '',
                    meeting_title: meta.meeting_title || '',
                    is_recurring: !!meta.is_recurring
                });
                return;
            }

            if (meta.type === 'group_session' && isAdmin) {
                var detailUrl = meta.detail_url || '';
                if (detailUrl) {
                    window.location.href = detailUrl;
                    return;
                }
                Cal.openGroupSessionEditor({
                    kind: 'group_session',
                    source_id: props.group_session_id || meta.group_session_id,
                    date: info.event.start ? info.event.start.toISOString().slice(0, 10) : (meta.session_date || ''),
                    time: info.event.start ? info.event.start.toTimeString().slice(0, 5) : (meta.session_time || ''),
                    end_time: info.event.end ? info.event.end.toTimeString().slice(0, 5) : '',
                    title: meta.title || '',
                    facilitator: meta.facilitator || '',
                    meeting_type: meta.meeting_type || 'in-person',
                    meeting_link: meta.meeting_link || ''
                });
                return;
            }

            if (meta.type === 'block' && isAdmin) {
                Cal.openBlockEditor({
                    kind: 'block',
                    source_id: props.block_id || meta.block_id,
                    date: info.event.start ? info.event.start.toISOString().slice(0, 10) : (meta.blocked_date || ''),
                    time: info.event.start ? info.event.start.toTimeString().slice(0, 5) : (meta.blocked_time || ''),
                    end_time: info.event.end ? info.event.end.toTimeString().slice(0, 5) : '',
                    title: meta.title || info.event.title || '',
                    block_type: meta.block_type || 'blocked',
                    is_private: !!meta.is_private
                });
            }

            if (meta.type === 'vacancy' && isAdmin) {
                var selectedDate = info.event.start ? info.event.start.toISOString().slice(0, 10) : '';
                var selectedTime = info.event.start ? info.event.start.toTimeString().slice(0, 5) : '';
                var duration = meta.duration_minutes || 60;
                Cal.setSelectedSlot(selectedDate, selectedTime, duration);
                if (Cal.bookingTypeSelect) {
                    Cal.bookingTypeSelect.value = 'appointment';
                    Cal.refreshSpecialControls();
                }
                if (Cal.bookingTabTrigger) {
                    bootstrap.Tab.getOrCreateInstance(Cal.bookingTabTrigger).show();
                }
                if (Cal.bookingPatient && isAdmin) {
                    Cal.bookingPatient.focus();
                }
            }
        }
    });

    var scheduleTabEl = document.getElementById('schedule-tab');
    if (scheduleTabEl) {
        scheduleTabEl.addEventListener('shown.bs.tab', function () {
            Cal.calendar.updateSize();
        });
    }

    var vacancyTabEl = document.getElementById('vacancy-tab');
    if (vacancyTabEl) {
        vacancyTabEl.addEventListener('shown.bs.tab', function () {
            Cal.loadVacancySlots();
        });
    }

    Cal.setSelectedSlot = function(date, time, durationMinutes) {
        Cal.bookingDate.value = date;
        Cal.bookingTime.value = time;
        if (Cal.bookingDateInput) Cal.bookingDateInput.value = date;
        if (Cal.bookingTimeInput) Cal.bookingTimeInput.value = time;
        var parts = time.split(':').map(Number);
        var endTotalMins = parts[0] * 60 + parts[1] + (durationMinutes || 60);
        var endH = Math.floor(endTotalMins / 60) % 24;
        var endM = endTotalMins % 60;
        var endTimeStr = String(endH).padStart(2, '0') + ':' + String(endM).padStart(2, '0');
        Cal.bookingEndTime.value = endTimeStr;
        if (Cal.bookingEndTimeInput) {
            Cal.bookingEndTimeInput.value = endTimeStr;
        }
        Cal.selectedSlotText.textContent = date + ' ' + time + ' → ' + endTimeStr;
    };

    if (Cal.bookingEndTimeInput) {
        Cal.bookingEndTimeInput.addEventListener('change', function() {
            Cal.bookingEndTime.value = Cal.bookingEndTimeInput.value;
            if (Cal.bookingDate.value && Cal.bookingTime.value && Cal.bookingEndTimeInput.value) {
                Cal.selectedSlotText.textContent = Cal.bookingDate.value + ' ' + Cal.bookingTime.value + ' → ' + Cal.bookingEndTimeInput.value;
            }
        });
    }

    if (Cal.bookingDateInput) {
        Cal.bookingDateInput.addEventListener('change', function() {
            Cal.bookingDate.value = this.value;
            if (Cal.bookingDate.value && Cal.bookingTime.value && Cal.bookingEndTimeInput.value) {
                Cal.selectedSlotText.textContent = Cal.bookingDate.value + ' ' + Cal.bookingTime.value + ' → ' + Cal.bookingEndTimeInput.value;
            }
        });
    }

    if (Cal.bookingTimeInput) {
        Cal.bookingTimeInput.addEventListener('change', function() {
            Cal.bookingTime.value = this.value;
            if (Cal.bookingDate.value && Cal.bookingTime.value && Cal.bookingEndTimeInput.value) {
                Cal.selectedSlotText.textContent = Cal.bookingDate.value + ' ' + Cal.bookingTime.value + ' → ' + Cal.bookingEndTimeInput.value;
            }
        });
    }

    var openGoogleMeetBtn = document.getElementById('openGoogleMeetBtn');
    var openZoomBtn = document.getElementById('openZoomBtn');
    if (openGoogleMeetBtn) {
        openGoogleMeetBtn.addEventListener('click', function() {
            window.open('https://meet.google.com/new', '_blank', 'noopener,noreferrer');
            if (Cal.meetingTypeSelect) Cal.meetingTypeSelect.value = 'google-meet';
            if (Cal.meetingPlatformHidden) Cal.meetingPlatformHidden.value = 'google-meet';
        });
    }
    if (openZoomBtn) {
        openZoomBtn.addEventListener('click', function() {
            window.open('https://zoom.us/start/videomeeting', '_blank', 'noopener,noreferrer');
            if (Cal.meetingTypeSelect) Cal.meetingTypeSelect.value = 'zoom';
            if (Cal.meetingPlatformHidden) Cal.meetingPlatformHidden.value = 'zoom';
        });
    }

    if (Cal.meetingTypeSelect && Cal.meetingLinkInput) {
        Cal.meetingTypeSelect.addEventListener('change', function() {
            var meetingLinkContainer = Cal.meetingLinkInput.closest('.mb-3');
            if (meetingLinkContainer) {
                meetingLinkContainer.classList.toggle('d-none', this.value !== 'online');
            }
            if (Cal.meetingPlatformHidden) {
                Cal.meetingPlatformHidden.value = (this.value === 'zoom' || this.value === 'google-meet') ? this.value : '';
            }
        });
        var meetingLinkContainer = Cal.meetingLinkInput.closest('.mb-3');
        if (meetingLinkContainer) {
            meetingLinkContainer.classList.toggle('d-none', Cal.meetingTypeSelect.value !== 'online');
        }
    }

    function createVacancyFromSelectedSlot() {
        if (!Cal.bookingDate.value || !Cal.bookingTime.value) {
            alert('Please select a time on the calendar first.');
            return;
        }
        if (Cal.bookingEndTimeInput && Cal.bookingEndTimeInput.value) {
            Cal.bookingEndTime.value = Cal.bookingEndTimeInput.value;
        }
        if (!Cal.bookingEndTime.value) {
            alert('Please set an end time.');
            return;
        }

        var recurring = confirm('Weekly recurring vacancy?\n\nOK = recurring every week\nCancel = one-time only');
        var pattern = recurring ? 'weekly' : 'one-time';
        fetch('/api/calendar/vacancy', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({
                slot_date: Cal.bookingDate.value,
                slot_time: Cal.bookingTime.value,
                end_time: Cal.bookingEndTime.value,
                recurrence_pattern: pattern
            })
        }).then(function(r) { return r.json(); }).then(function(data) {
            if (data.status === 'success') {
                Cal.loadSnapshot();
                Cal.loadVacancies();
                Cal.loadVacancySlots();
            } else {
                alert(data.message || 'Failed.');
            }
        }).catch(function() {
            alert('Network error.');
        });
    }

    if (Cal.createVacancyBtn) {
        Cal.createVacancyBtn.addEventListener('click', createVacancyFromSelectedSlot);
    }

    var bookingRecurrence = document.getElementById('bookingRecurrence');
    var recurringDateWrap = document.getElementById('recurringDateWrap');
    var meetingRemarksInput = document.getElementById('meetingRemarksInput');

    if (bookingRecurrence) {
        bookingRecurrence.addEventListener('change', function() {
            if (recurringDateWrap) {
                recurringDateWrap.classList.toggle('d-none', this.value !== '1');
            }
        });
    }

    if (Cal.bookingPatient && (meetingRemarksInput || Cal.meetingTitleInput)) {
        Cal.bookingPatient.addEventListener('change', function() {
            var selected = Cal.bookingPatient.options[Cal.bookingPatient.selectedIndex];
            var status = selected ? (selected.dataset.patientStatus || '') : '';
            var isOther = this.value === 'other';

            if (bookingRecurrence) {
                bookingRecurrence.value = (status === 'ongoing') ? '1' : '0';
                if (recurringDateWrap) {
                    recurringDateWrap.classList.toggle('d-none', bookingRecurrence.value !== '1');
                }
            }

            if (Cal.otherNameWrap) {
                Cal.otherNameWrap.classList.toggle('d-none', !isOther);
            }
            if (isOther && Cal.bookingTypeSelect) {
                Cal.bookingTypeSelect.value = 'special';
                Cal.refreshSpecialControls();
                if (Cal.specialTitleWrap) Cal.specialTitleWrap.classList.add('d-none');
            } else if (!isOther && Cal.bookingTypeSelect && Cal.bookingTypeSelect.value === 'special' && !isOther) {
                Cal.bookingTypeSelect.value = 'appointment';
                Cal.refreshSpecialControls();
            }
            if (Cal.bookingStatusHint) {
                if (isOther) {
                    Cal.bookingStatusHint.textContent = I18N.otherModeHint;
                } else if (!status) {
                    Cal.bookingStatusHint.textContent = I18N.selectPatientMode;
                } else if (status === 'ongoing') {
                    Cal.bookingStatusHint.textContent = I18N.ongoingModeHint;
                } else {
                    Cal.bookingStatusHint.textContent = I18N.candidateModeHint;
                }
            }
        });
    }

    Cal.refreshSpecialControls = function() {
        if (!Cal.bookingTypeSelect) {
            return;
        }
        var isSpecial = Cal.bookingTypeSelect.value === 'special';
        Cal.bookingTypeSelect.style.borderColor = isSpecial ? '#7c3aed' : '';
        Cal.bookingTypeSelect.style.color = isSpecial ? '#7c3aed' : '';
        if (Cal.specialMetaWrap) {
            Cal.specialMetaWrap.classList.toggle('d-none', !isSpecial);
        }
        if (Cal.specialTitleWrap) {
            Cal.specialTitleWrap.classList.toggle('d-none', !isSpecial);
        }
        if (Cal.specialPatternSelect && Cal.specialRepeatUntilWrap) {
            var needsUntil = isSpecial && Cal.specialPatternSelect.value === 'weekly';
            Cal.specialRepeatUntilWrap.classList.toggle('d-none', !needsUntil);
            if (!needsUntil && Cal.specialRepeatUntilInput) {
                Cal.specialRepeatUntilInput.value = '';
            }
        }
        if (Cal.bookSlotSubmitBtn) {
            if (isSpecial) {
                Cal.bookSlotSubmitBtn.classList.remove('btn-primary');
                Cal.bookSlotSubmitBtn.classList.add('btn-purple');
                Cal.bookSlotSubmitBtn.style.backgroundColor = '#7c3aed';
                Cal.bookSlotSubmitBtn.style.borderColor = '#7c3aed';
            } else {
                Cal.bookSlotSubmitBtn.classList.remove('btn-purple');
                Cal.bookSlotSubmitBtn.classList.add('btn-primary');
                Cal.bookSlotSubmitBtn.style.backgroundColor = '';
                Cal.bookSlotSubmitBtn.style.borderColor = '';
            }
        }
    };

    if (Cal.bookingTypeSelect) {
        Cal.bookingTypeSelect.addEventListener('change', function() {
            Cal.refreshSpecialControls();
            var otherBookingTypeWrap = document.getElementById('otherBookingTypeWrap');
            if (otherBookingTypeWrap) {
                otherBookingTypeWrap.style.display = Cal.bookingTypeSelect.value === 'other' ? 'block' : 'none';
            }
        });
    }
    if (Cal.specialPatternSelect) {
        Cal.specialPatternSelect.addEventListener('change', Cal.refreshSpecialControls);
    }
    Cal.refreshSpecialControls();

    Cal.eventMatchesFilter = function(event) {
        if (Cal.activeFilter === 'all') {
            return true;
        }

        var meta = event.extendedProps && event.extendedProps.meta ? event.extendedProps.meta : {};

        if (Cal.activeFilter === 'blocked') {
            return meta.type === 'block' && meta.block_type === 'blocked';
        }
        if (Cal.activeFilter === 'special') {
            return meta.type === 'block' && meta.block_type === 'special';
        }
        if (Cal.activeFilter === 'all' && meta.type === 'group_session') {
            return true;
        }
        if (Cal.activeFilter === 'ongoing') {
            return meta.type === 'appointment' && meta.patient_status === 'ongoing';
        }
        if (Cal.activeFilter === 'candidate') {
            return meta.type === 'appointment' && (meta.patient_status === 'candidate' || meta.patient_status === 'waiting' || meta.patient_status === 'waiting for scheduling');
        }
        if (Cal.activeFilter === 'archived') {
            return meta.type === 'appointment' && meta.patient_status === 'archived';
        }
        return true;
    };

    Cal.applyCalendarFilter = function() {
        Cal.calendar.getEvents().forEach(function(event) {
            event.setProp('display', Cal.eventMatchesFilter(event) ? 'auto' : 'none');
        });
    };

    Cal.filterButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            Cal.activeFilter = btn.dataset.filter;
            Cal.filterButtons.forEach(function(b) {
                b.classList.remove('btn-primary');
                b.classList.add('btn-outline-primary');
            });
            btn.classList.remove('btn-outline-primary');
            btn.classList.add('btn-primary');
            Cal.applyCalendarFilter();
        });
    });

    Cal.renderWeekendList = function(container, list) {
        if (!list || list.length === 0) {
            container.innerHTML = '<div class="small text-muted">' + I18N.noWeekendItems + '</div>';
            return;
        }
        container.innerHTML = list.map(function(item) {
            var badge = item.type === 'blocked' ? 'bg-danger' : 'bg-primary';
            return '<div class="border rounded-3 p-2 mb-2">' +
                '<div class="d-flex justify-content-between align-items-center mb-1">' +
                    '<span class="badge ' + badge + ' small">' + item.type + '</span>' +
                    '<span class="small text-muted">' + item.time + '</span>' +
                '</div>' +
                '<div class="small fw-semibold">' + item.title + '</div>' +
                '<div class="small text-muted">' + item.duration + ' min</div>' +
            '</div>';
        }).join('');
    };

    Cal.renderFollowUps = function(list) {
        if (!list || list.length === 0) {
            Cal.followUpExpanded = false;
            Cal.followUpAlerts.innerHTML = '<div class="small text-muted">' + I18N.noPendingFollowUps + '</div>';
            return;
        }

        var visibleItems = Cal.followUpExpanded ? list : list.slice(0, 5);
        var hiddenCount = Math.max(0, list.length - visibleItems.length);

        var cardsHtml = visibleItems.map(function(item) {
            return '<div class="alert alert-warning py-2 mb-2 small">' +
                '<a href="/patient/' + item.patient_id + '?tab=info" class="fw-bold text-dark text-decoration-underline">' + item.patient_name + '</a> (' + item.status + ')<br>' +
                'Last one-time meeting: ' + item.last_meeting_date + '<br>' +
                item.message +
            '</div>';
        }).join('');

        var moreButtonHtml = list.length > 5
            ? '<button type="button" class="btn btn-link btn-sm px-0 text-decoration-none" id="followUpShowMoreBtn" aria-expanded="' + (Cal.followUpExpanded ? 'true' : 'false') + '">' + (Cal.followUpExpanded ? I18N.showLess : I18N.showMore + ' (' + hiddenCount + ')') + '</button>'
            : '';

        Cal.followUpAlerts.innerHTML = cardsHtml + moreButtonHtml;

        var toggleBtn = document.getElementById('followUpShowMoreBtn');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', function () {
                Cal.followUpExpanded = !Cal.followUpExpanded;
                Cal.renderFollowUps(list);
            });
        }
    };

    Cal.renderOngoingList = function(events) {
        var names = (events || [])
            .filter(function(evt) { return evt.meta && evt.meta.type === 'appointment' && evt.meta.patient_status === 'ongoing'; })
            .map(function(evt) { return evt.title; })
            .filter(function(name) { return name && name !== 'Unavailable'; });
        var uniqueNames = Array.from(new Set(names));
        Cal.ongoingThisWeek.textContent = uniqueNames.length ? String(uniqueNames.length) : I18N.none;
    };

    Cal.renderAvailableSlots = function(slots) {
        Cal.availableCount.textContent = slots.length;

        if (!slots.length) {
            Cal.availableSlotsContainer.innerHTML = '<div class="small text-muted">' + I18N.noOpenSlotsWeek + '</div>';
            return;
        }

        var grouped = slots.reduce(function(acc, slot) {
            if (!acc[slot.date]) {
                acc[slot.date] = [];
            }
            acc[slot.date].push(slot);
            return acc;
        }, {});

        var sortedDays = Object.keys(grouped).sort();

        Cal.availableSlotsContainer.innerHTML = sortedDays.map(function(day) {
            var daySlots = grouped[day];
            var entries = daySlots.map(function(slot) {
                return '<div class="d-flex justify-content-between align-items-center border rounded-3 p-2 mb-2">' +
                    '<div class="small text-muted">' + slot.time + ' · ' + slot.duration_minutes + ' min</div>' +
                    '<button type="button" class="btn btn-sm btn-outline-primary pick-slot" data-date="' + slot.date + '" data-time="' + slot.time + '" data-duration="' + slot.duration_minutes + '">' + I18N.useSlot + '</button>' +
                '</div>';
            }).join('');

            return '<details class="border rounded-3 p-2 mb-2 slot-day-details">' +
                '<summary class="fw-semibold">' + day + ' (' + daySlots.length + ' slots)</summary>' +
                '<div class="mt-2">' + entries + '</div>' +
            '</details>';
        }).join('');
    };

    if (Cal.availableSlotsContainer) {
        Cal.availableSlotsContainer.addEventListener('click', function(event) {
            var btn = event.target.closest('.pick-slot');
            if (!btn) return;
            event.preventDefault();
            Cal.setSelectedSlot(btn.dataset.date, btn.dataset.time, parseInt(btn.dataset.duration || '60', 10));
            if (Cal.bookingTypeSelect) {
                Cal.bookingTypeSelect.value = 'appointment';
                Cal.refreshSpecialControls();
            }
            if (Cal.bookingTabTrigger) {
                bootstrap.Tab.getOrCreateInstance(Cal.bookingTabTrigger).show();
            }
            if (Cal.bookingPatient && isAdmin) {
                Cal.bookingPatient.focus();
            }
        });
    }

    Cal.loadSnapshot = function() {
        if (!Cal.currentWeekStart) return;
        fetch('/api/calendar/snapshot?week_start=' + encodeURIComponent(Cal.currentWeekStart))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                Cal.calendar.removeAllEvents();
                (data.events || []).forEach(function(evt) { Cal.calendar.addEvent(evt); });
                (data.external_events || []).forEach(function(evt) {
                    if (!evt.start) return;
                    Cal.calendar.addEvent({
                        id: 'gcal_ext_' + evt.google_event_id,
                        title: evt.title || '(Google Calendar)',
                        start: evt.start,
                        end: evt.end || evt.start,
                        color: '#d1d5db',
                        textColor: '#374151',
                        editable: false,
                        extendedProps: { meta: { type: 'external_google' } }
                    });
                });
                Cal.applyCalendarFilter();
                Cal.renderWeekendList(Cal.fridaySpecials, data.weekend_specials ? data.weekend_specials.friday : []);
                Cal.renderWeekendList(Cal.saturdaySpecials, data.weekend_specials ? data.weekend_specials.saturday : []);
                Cal.renderFollowUps(data.follow_up_alerts || []);
                Cal.renderAvailableSlots(data.available_slots || []);
                Cal.renderOngoingList(data.events || []);
                Cal.loadBookingManagement();
                Cal.loadVacancies();
                Cal.loadVacancySlots();
            })
            .catch(function() { console.warn('loadSnapshot failed'); });
    };

    Cal.calendar.render();

    if (Cal.bookingManagementMode) {
        Cal.bookingManagementMode.querySelectorAll('button[data-mode]').forEach(function(btn) {
            btn.addEventListener('click', function() {
                Cal.activeManagementMode = this.dataset.mode || 'upcoming';
                Cal.bookingManagementMode.querySelectorAll('button[data-mode]').forEach(function(b) {
                    b.classList.remove('btn-primary');
                    b.classList.add('btn-outline-primary');
                });
                this.classList.remove('btn-outline-primary');
                this.classList.add('btn-primary');
                Cal.loadBookingManagement();
            });
        });
    }

    if (Cal.calendarPrevWeek) {
        Cal.calendarPrevWeek.addEventListener('click', function() {
            Cal.goToWeek(Cal.shiftWeek(Cal.nowWeekAnchor, -1));
        });
    }
    if (Cal.calendarTodayWeek) {
        Cal.calendarTodayWeek.addEventListener('click', function() {
            Cal.goToWeek(Cal.getWeekStartString(new Date()));
        });
    }
    if (Cal.calendarNextWeek) {
        Cal.calendarNextWeek.addEventListener('click', function() {
            Cal.goToWeek(Cal.shiftWeek(Cal.nowWeekAnchor, 1));
        });
    }

    if (Cal.availableWeekSelect) {
        Cal.refreshWeekOptions();
        Cal.availableWeekSelect.addEventListener('change', function() {
            var targetWeek = this.value;
            if (targetWeek) {
                Cal.goToWeek(targetWeek);
            }
        });
    }

    if (Cal.blockRecurrencePattern) {
        Cal.blockRecurrencePattern.addEventListener('change', function() {
            var isWeekly = this.value === 'weekly';
            if (Cal.blockRepeatUntilWrap) {
                Cal.blockRepeatUntilWrap.classList.toggle('d-none', !isWeekly);
            }
            if (!isWeekly && Cal.blockRepeatUntilInput) {
                Cal.blockRepeatUntilInput.value = '';
            }
        });
    }

    var addBlockForm = document.getElementById('addBlockForm');
    if (addBlockForm) {
        addBlockForm.addEventListener('submit', function(e) {
            e.preventDefault();
            var formData = new FormData(addBlockForm);
            fetch('/api/calendar/block', {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken },
                body: new URLSearchParams(formData)
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.status === 'success') {
                    addBlockForm.reset();
                    if (Cal.blockRepeatUntilWrap) {
                        Cal.blockRepeatUntilWrap.classList.add('d-none');
                    }
                    Cal.loadSnapshot();
                    Cal.loadBookingManagement();
                } else {
                    Cal.showActionModal({ title: 'Save Failed', message: data.message || 'Could not save override.' });
                }
            });
        });
    }

    if (Cal.createPublicBookingLinkBtn) {
        Cal.createPublicBookingLinkBtn.addEventListener('click', function() {
            fetch('/api/calendar/public-link', {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken }
            }).then(function(r) { return r.json(); }).then(function(data) {
                if (data.status === 'success') {
                    if (Cal.publicBookingLinkInput) {
                        Cal.publicBookingLinkInput.value = data.url || '';
                    }
                    if (Cal.sendPublicBookingMailBtn && data.mailto) {
                        Cal.sendPublicBookingMailBtn.href = data.mailto;
                        Cal.sendPublicBookingMailBtn.classList.remove('d-none');
                    }
                    Cal.showActionModal({ title: 'Link Created', message: 'Public self-booking link is ready.' });
                } else {
                    Cal.showActionModal({ title: 'Error', message: data.message || 'Could not create link.' });
                }
            }).catch(function() {
                Cal.showActionModal({ title: 'Error', message: 'Could not create link.' });
            });
        });
    }

    if (Cal.copyPublicBookingLinkBtn) {
        Cal.copyPublicBookingLinkBtn.addEventListener('click', function() {
            var value = (Cal.publicBookingLinkInput && Cal.publicBookingLinkInput.value) ? Cal.publicBookingLinkInput.value : '';
            if (!value) {
                Cal.showActionModal({ title: 'No Link', message: 'Generate a link first.' });
                return;
            }
            navigator.clipboard.writeText(value).then(function() {
                Cal.showActionModal({ title: 'Copied', message: 'Link copied to clipboard.' });
            }).catch(function() {
                Cal.showActionModal({ title: 'Copy Failed', message: 'Could not copy the link.' });
            });
        });
    }

    var bookSlotForm = document.getElementById('bookSlotForm');
    bookSlotForm.addEventListener('submit', function(e) {
        e.preventDefault();

        if (!Cal.bookingDate.value || !Cal.bookingTime.value) {
            Cal.showActionModal({ title: 'Time Required', message: 'Please select a time on the calendar first.' });
            return;
        }

        if (Cal.bookingEndTimeInput && Cal.bookingEndTimeInput.value) {
            Cal.bookingEndTime.value = Cal.bookingEndTimeInput.value;
        }
        if (!Cal.bookingEndTime.value) {
            Cal.showActionModal({ title: 'End Time Required', message: 'Please set an end time for the booking.' });
            return;
        }

        if (Cal.bookingTypeSelect && Cal.bookingTypeSelect.value === 'special') {
            if (Cal.specialPatternSelect && Cal.specialPatternSelect.value === 'weekly' && (!Cal.specialRepeatUntilInput || !Cal.specialRepeatUntilInput.value)) {
                Cal.showActionModal({ title: 'Repeat Until Required', message: 'Please select a repeat-until date for recurring special slots.' });
                return;
            }
        }

        if (!isAdmin && !Cal.canSelfSchedule) {
            Cal.showActionModal({ title: 'Booking Disabled', message: 'Self-booking is disabled for your account.' });
            return;
        }

        var formData = new FormData(bookSlotForm);
        if (Cal.bookingPatient && Cal.bookingPatient.value === 'other') {
            var otherVal = Cal.otherNameInput ? Cal.otherNameInput.value.trim() : '';
            if (!otherVal) {
                Cal.showActionModal({ title: 'Name Required', message: 'Please enter a name for the other booking.' });
                return;
            }
            formData.set('booking_type', 'special');
            formData.set('special_title', otherVal);
        }

        if (Cal.bookingTypeSelect && Cal.bookingTypeSelect.value === 'other') {
            var otherBookingTypeInput = document.getElementById('otherBookingTypeInput');
            var otherVal = otherBookingTypeInput ? otherBookingTypeInput.value.trim() : '';
            if (!otherVal) {
                Cal.showActionModal({ title: 'Type Required', message: 'Please specify the booking type.' });
                return;
            }
            formData.set('booking_type', otherVal);
        }

        fetch('/api/calendar/book', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken },
            body: new URLSearchParams(formData)
        }).then(function(r) { return r.json(); }).then(function(data) {
            if (data.status === 'success') {
                Cal.showActionModal({ title: 'Booking Saved', message: data.message || 'The booking was saved successfully.' });
                Cal.loadSnapshot();
            } else {
                Cal.showActionModal({ title: 'Booking Failed', message: data.message || 'Booking failed.' });
            }
        }).catch(function() {
            Cal.showActionModal({ title: 'Error', message: 'Network error — could not save booking.' });
        });
    });

    Cal.syncWeekFromAnchor();
    Cal.refreshWeekOptions();
    Cal.calendar.gotoDate(Cal.parseIsoDate(Cal.nowWeekAnchor));
    Cal.loadSnapshot();

    setInterval(function() {
        var nextAnchor = Cal.getWeekStartString(new Date());
        if (nextAnchor !== Cal.nowWeekAnchor) {
            Cal.nowWeekAnchor = nextAnchor;
            Cal.currentWeekStart = nextAnchor;
            Cal.calendar.refetchEvents();
            Cal.calendar.gotoDate(Cal.parseIsoDate(nextAnchor));
            Cal.loadSnapshot();
        }
    }, 60000);
});
