# Task: Unify Calendar Editor Functions

**File:** `/home/lioraloni/Private_Clinic/templates/calendar.html`

## Problem

Three editor functions share the same pattern but diverge in implementation:

| Function | Lines | Size |
|----------|-------|------|
| `openAppointmentEditor` | 790-1018 | ~229 lines |
| `openGroupSessionEditor` | 1020-1103 | ~84 lines |
| `openBlockEditor` | 1105-1187 | ~83 lines |

They share the same structure:
1. Guard clause: validate payload/source_id
2. Build modal HTML with form fields
3. Show modal via `actionModal.show()`
4. Attach delete button → fetch delete endpoint → `loadSnapshot()` + `loadBookingManagement()`
5. Attach confirm button → fetch update endpoint → same cleanup

## Plan

### Step 1: Define a config schema

Create a single `openSlotEditor(payload, config)` function where `config` specifies:

```javascript
{
    kind: 'appointment' | 'group' | 'block',
    title: 'Edit Appointment',          // modal title
    confirmText: 'Save Changes',       // confirm button text
    deleteEndpoint: '/api/...',        // fetch URL for delete
    updateEndpoint: '/api/...',        // fetch URL for update  
    fields: [                          // form fields
        { name: 'date', label: 'Date', type: 'date', dataKey: 'appointment_date' },
        { name: 'time', label: 'Start Time', type: 'time', dataKey: 'appointment_time' },
        // ...
    ],
    extraBodyHtml: '',                 // optional: recurrence, Google Calendar toggles
    onSave: function(formData) { },    // optional pre-save hook
    onDelete: function() { },           // optional pre-delete hook
}
```

### Step 2: Build HTML from config

Replace the inline template literal with a config-driven HTML builder. Example:

```javascript
function buildEditorHtml(config, payload) {
    var html = '';
    config.fields.forEach(function(f) {
        var value = payload[f.dataKey] || '';
        if (f.type === 'date' || f.type === 'time') {
            html += '<div class="mb-2"><label class="form-label small">' + f.label + '</label>';
            html += '<input type="' + f.type + '" class="form-control form-control-sm" id="editor-' + f.name + '" value="' + escapeHtml(value) + '">';
            html += '</div>';
        }
        // ... other field types
    });
    if (config.extraBodyHtml) html += config.extraBodyHtml;
    html += '<button type="button" class="btn btn-sm btn-outline-danger mt-3" id="editorDeleteBtn">Delete</button>';
    return html;
}
```

### Step 3: Unify delete/save handlers

```javascript
function setupEditorHandlers(config, payload) {
    var deleteBtn = document.getElementById('editorDeleteBtn');
    if (deleteBtn) {
        deleteBtn.onclick = function() {
            if (!confirm('Delete this ' + config.kind + '?')) return;
            fetch(config.deleteEndpoint, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken }
            }).then(function(r) { return r.json(); }).then(function(data) {
                if (data.status === 'success') {
                    actionModal.hide();
                    loadSnapshot();
                    loadBookingManagement();
                } else {
                    alert(data.message || 'Delete failed.');
                }
            }).catch(function() { alert('Network error.'); });
        };
    }

    modalConfirmBtn.onclick = function() {
        var formData = {};
        config.fields.forEach(function(f) {
            var el = document.getElementById('editor-' + f.name);
            formData[f.dataKey] = el ? el.value : '';
        });
        if (config.onSave) {
            var result = config.onSave(formData);
            if (result === false) return;
        }
        fetch(config.updateEndpoint, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams(formData)
        }).then(function(r) { return r.json(); }).then(function(data) {
            if (data.status === 'success') {
                actionModal.hide();
                loadSnapshot();
                loadBookingManagement();
            } else {
                alert(data.message || 'Save failed.');
            }
        }).catch(function() { alert('Network error.'); });
    };
}
```

### Step 4: Create the three configs

```javascript
var APPOINTMENT_CONFIG = {
    kind: 'appointment',
    title: 'Edit Appointment',
    confirmText: 'Save Changes',
    deleteEndpoint: '/api/calendar/...',
    updateEndpoint: '/api/calendar/...',
    fields: [...],
    extraBodyHtml: '...',  // recurrence, Google Calendar toggle
    onSave: function(data) { /* recurrence scope logic */ }
};

var GROUP_CONFIG = { /* ... */ };
var BLOCK_CONFIG = { /* ... */ };
```

### Step 5: Replace old functions

Replace `openAppointmentEditor`, `openGroupSessionEditor`, `openBlockEditor` with:

```javascript
function openAppointmentEditor(payload) {
    openSlotEditor(payload, APPOINTMENT_CONFIG);
}
function openGroupSessionEditor(payload) {
    openSlotEditor(payload, GROUP_CONFIG);
}
function openBlockEditor(payload) {
    openSlotEditor(payload, BLOCK_CONFIG);
}
```

### Expected reduction

~400 lines → ~200 lines (configs are compact, handler logic is shared)

## Notes

- Use `confirm()` and `alert()` instead of `showActionModal()` for delete/error — no Bootstrap backdrop issues
- Same approach we used for the vacancy rebuild — it worked cleanly
- The `openAppointmentEditor` recurrence scope logic (this occurrence, all upcoming, all) can be handled by `onSave` returning false for the scope selector path
