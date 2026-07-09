# Task: Extract calendar.js to External File

**File:** `/home/lioraloni/Private_Clinic/templates/calendar.html` (2,392 lines)

## Problem

80% of the file (1,912 lines) is a single inline `<script>` block. The JS:
- Is re-downloaded on every page load (no browser caching)
- Can't be linted, minified, or tree-shaken
- Makes the template unreadable (~480 lines of actual HTML)

## Plan

### Step 1: Create `static/js/calendar.js`

Move the entire `<script>` block from calendar.html into a new file. The script block starts at line 479 and ends at line 2391.

### Step 2: Handle Jinja2 expressions in JS

The inline JS contains Jinja2 template expressions like `{{ t('Notice')|tojson }}` and `{{ initial_week_start|tojson }}`. These MUST be rendered by Flask. Approach:

**Option A (recommended):** Create a small `<script>` block in calendar.html that defines a `window.I18N` object, then pull the rest from an external file:

```html
<script>
    window.I18N = {
        notice: {{ t('Notice')|tojson }},
        ok: {{ t('OK')|tojson }},
        cancel: {{ t('Cancel')|tojson }},
        // ... all other t() calls
    };
    window.CALENDAR_CONFIG = {
        initialWeekStart: {{ initial_week_start|tojson if initial_week_start is defined else 'null' }},
    };
</script>
<script src="{{ url_for('static', filename='js/calendar.js') }}"></script>
```

The external `calendar.js` would use `window.I18N.notice` instead of `I18N.notice`.

**Option B:** Move only the non-Jinja2 parts to external files, keeping inline only the few Jinja2 references.

### Step 3: Extract by functional area

Split `calendar.js` into logical modules:

| Module | Contains | ~Lines |
|--------|----------|--------|
| `calendar-i18n.js` | I18N object + translations | 50 |
| `calendar-fullcalendar.js` | FullCalendar init, event rendering, snapshot loading | 400 |
| `calendar-booking.js` | Booking pane, form handling, recurrence logic | 350 |
| `calendar-vacancy.js` | Vacancy CRUD (already simplified) | 200 |
| `calendar-editors.js` | openAppointmentEditor, openGroupSessionEditor, openBlockEditor | 400 |
| `calendar-modals.js` | showActionModal, showScopeModal, backdrop cleanup | 100 |
| `calendar-utils.js` | escapeHtml, date helpers, common functions | 200 |

### Step 4: Verify

- Load the calendar page and verify all functionality
- Check browser console for undefined references
- Run: `grep -c "{{ " templates/calendar.html` — should be ~50 (only the I18N object)

## Notes

- The persistent backdrop cleanup listener (line 536) and `showActionModal` are template-independent and can be moved verbatim
- The `calendar.render()` call must remain AFTER all module scripts are loaded
- All Jinja2 `|tojson` expressions produce valid JSON that survives `JSON.parse()` — no issues with special characters
