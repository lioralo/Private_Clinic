# Changes Documentation - March 9, 2026

## Overview
Fixed multiple issues with ongoing patient crashes, color coding, calendar refresh, and unified booking interface.

## Changes Made

### 1. **Fixed Port Closing Issue in `run.py`** ✅
**Problem**: When Ctrl+C was pressed, the Flask app process wasn't properly terminating, causing the port (5000) to remain occupied.

**Solution**:
- Added `psutil` dependency for robust process management
- Implemented proper process group cleanup using `psutil.Process.children()`
- Added graceful termination with force-kill fallback
- Implemented proper signal handling with flag to prevent signal recursion
- Added auto-cleanup via `atexit` module for edge cases
- Added 0.5-second delay after process termination to ensure port release

**Files Modified**: `run.py`, `requirements.txt`

---

### 2. **Fixed Ongoing Patients Crash (Convert Modal)** ✅
**Problem**: The convert modal was missing critical fields (`duration`, `days`) causing form submission errors and crashes when converting candidates to ongoing.

**Solution**:
- Added `duration` field selector (30, 60, 90, 120 minutes)
- Added `days` checkboxes for recurrence day selection (Sun-Thu)
- Properly structure recurrence fields in modal  
- Enhanced error handling in `convert_patient()` function:
  - Input validation for dates and times
  - Type conversion with error handling
  - Database error handling with rollback
  - User-friendly error messages
  - Audit logging for patient conversion

**Files Modified**: `templates/patient_detail.html`, `app.py` (convert_patient function)

---

### 3. **Fixed Color Coding for Waiting Patients** ✅
**Problem**: Candidate and waiting patients were using the same color scheme, making it unclear which waiting patients have bookings scheduled.

**Solution**:
- Updated color logic to differentiate waiting patients:
  - `Ongoing` = Green (bg-success)
  - `Candidate` = Yellow (bg-warning)
  - `Waiting WITH recurring appointments` = Blue (bg-info) - indicates scheduled
  - `Waiting WITHOUT appointments` = Gray (bg-secondary) - indicates not yet scheduled
  - `Archived` = Gray (bg-secondary)

**Files Modified**: `templates/index.html`, `templates/patient_detail.html`

---

### 4. **Fixed Calendar Not Refreshing After Booking** ✅
**Problem**: After booking appointments from the patient detail page, the admin calendar in manage_slots didn't update automatically.

**Solution**:
- Added "Refresh" button to calendar toolbar
- Implemented auto-refresh every 30 seconds using `calendar.refetchEvents()`
- Calendar now properly reflects changes from both interfaces

**Files Modified**: `templates/manage_slots.html`

---

### 5. **Created Unified Booking Interface in Manage Slots** ✅
**Problem**: Booking existed in two disconnected places (patient detail vs. management tool) with different functionality. No way to book from scheduler tool.

**Solution**:
- Redesigned slot modal with dual modes:
  
  **Mode 1: Availability Management (Override)**
  - Manage slot availability (Open/Blocked/Occupied)
  - Set duration and status
  - Existing functionality preserved
  
  **Mode 2: Patient Booking**
  - Select patient from dropdown
  - Set appointment details (duration, cost, meeting type, link)
  - **RECURRING APPOINTMENT SUPPORT**:
    - Checkbox to enable recurring scheduling
    - Interval selection (weekly/bi-weekly)
    - Day of week selection
    - End limit options (by date or count)
  - Auto-marks slot as occupied after booking
  - Audit logging for admin actions

- Updated `manage_slots()` route:
  - Now passes all patients to template for dropdown
  
- Enhanced `admin_manage_slots()` function:
  - Detects mode and routes to appropriate handler
  - Comprehensive validation and error handling
  - Both single and recurring appointment support
  - Transaction rollback on errors
  - Automatic slot override creation/update

**Files Modified**: `templates/manage_slots.html`, `app.py`

---

### 6. **Enhanced Error Handling Throughout** ✅
- Added try-except blocks with proper error messages
- Implemented database transaction rollback on errors
- Improved validation for dates, times, and numeric fields
- User-friendly flash messages for all error conditions
- Audit logging for convert and booking operations

**Files Modified**: `app.py` (multiple functions)

---

## Testing Recommendations

### 1. **Ongoing Patient Conversion**
- Go to candidate patient
- Click "Convert to Ongoing"
- Fill all fields (should no longer crash):
  - Start date and time
  - Duration
  - Cost
  - Recurrence days (select at least Monday)
  - End limit (count or date)
- Verify patient converts successfully with audit log

### 2. **Patient Color Coding**
- View patients list (/patients)
- Verify colors:
  - Ongoing patients = Green
  - Candidate patients = Yellow
  - Waiting patients with recurring = Blue
  - Waiting patients without appointments = Gray

### 3. **Calendar Auto-Refresh**
- Open manage_slots in one window
- Book appointment from patient detail in another
- Verify calendar refreshes within 30 seconds
- Test manual "Refresh" button

### 4. **Unified Booking Interface**
- Go to Manage Slots
- Click on a time slot
- Switch between modes:
  - **Override Mode**: Manage availability
  - **Patient Booking Mode**: Book for patient
- Test booking single appointment
- Test booking with recurring option
- Verify slot is marked occupied
- Verify calendar updates

### 5. **Recurring Appointments from Scheduler**
- Book appointment from manage_slots
- Enable "Make recurring"
- Select interval (weekly/bi-weekly)
- Select days of week
- Set end limit (count or date)
- Verify recurring series appears in calendar

---

## Security Improvements
- Validated all user inputs (dates, times, numeric values)
- Protected against type errors and injection
- Proper authorization checks maintained
- Audit logging for sensitive operations

## Performance Improvements
- Calendar auto-refresh efficient (30-second intervals)
- Manual refresh button for immediate updates
- Better error isolation prevents cascading failures

## Backwards Compatibility
- All existing functionality preserved
- Can still use patient detail page for bookings
- Slot override management unchanged
- New booking interface is additive

---

## Files Modified Summary
1. `run.py` - Process management enhancements
2. `requirements.txt` - Added psutil
3. `app.py` - Multiple function improvements:
   - `manage_slots()` - Pass all_patients to template
   - `admin_manage_slots()` - Unified booking interface
   - `convert_patient()` - Complete rewrite with validation
   - `add_appointment()` - Recurring appointment support
   - `api_slots()` - Time handling improvements
   - `seed_data()` - Error handling
4. `templates/patient_detail.html` - Enhanced convert modal
5. `templates/index.html` - Improved color coding
6. `templates/manage_slots.html` - Unified booking modal + calendar refresh
7. `CHANGES.md` - Comprehensive documentation
