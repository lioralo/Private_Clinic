# Changes Documentation - March 9, 2026

## Overview
Fixed critical issues with port closing, calendar booking functionality, recurring appointments, and seed data handling.

## Changes Made

### 1. **Fixed Port Closing Issue in `run.py`** ✅
**Problem**: When Ctrl+C was pressed, the Flask app process wasn't properly terminating, causing the port (5000) to remain occupied.

**Solution**:
- Added `psutil` dependency for robust process management
- Implemented proper process group cleanup using `psutil.Process.children()`
- Added graceful termination with force-kill fallback
- Implemented proper signal handling with `threading.Event` to prevent signal recursion
- Added auto-cleanup via `atexit` module for edge cases
- Added 0.5-second delay after process termination to ensure port release

**Files Modified**:
- `run.py` - Enhanced with better process lifecycle management and cleanup
- `requirements.txt` - Added `psutil` dependency

### 2. **Fixed Calendar Booking and Recurring Appointments** ✅
**Problem**: The `add_appointment()` route was not processing recurring appointment fields from the form, causing recurring appointment creation to fail silently.

**Issues Fixed**:
- `add_appointment()` route now properly handles:
  - `is_recurring` flag
  - `interval` (recurrence interval in weeks)
  - `recurrence_limit_type` (date or count)
  - `recurrence_end_date` for end-date limited recurrence
  - `recurrence_count` for count-limited recurrence
  - `days` (days of week for recurrence)
  - `duration` (appointment duration in minutes)

- Added comprehensive input validation:
  - Date format validation (ISO format)
  - Time format validation (HH:MM format)
  - Type conversion with error handling
  - UNIQUE constraint error handling

- Enhanced error messaging:
  - Specific flash messages for different error types
  - User-friendly error notifications

**Files Modified**:
- `app.py` - Updated `add_appointment()` function with full recurring appointment support

### 3. **Fixed Time Handling in Calendar API** ✅
**Problem**: The `api_slots()` function was using `zfill(5)` twice on time values and not handling malformed times properly, causing calendar rendering issues.

**Solution**:
- Removed problematic double `zfill(5)` calls
- Added robust time format validation
- Implemented proper error handling for ValueError exceptions
- Added continue statements to skip malformed data gracefully
- Ensured times are in proper HH:MM format before processing

**Improvements**:
- Calendar events now render correctly even with edge case time formats
- Better error isolation - malformed single entries don't crash the entire API response
- More reliable recurring appointment projection in calendar

**Files Modified**:
- `app.py` - Fixed time handling in `api_slots()` function for both slot overrides and appointments

### 4. **Fixed Seed Data UNIQUE Constraint Error** ✅
**Problem**: The `/admin/seed_data` endpoint was failing with "UNIQUE constraint failed: users.username" when called multiple times due to attempting to re-insert the same usernames.

**Solution**:
- Added check for existing 'alice' user before insertion
- Wrapped seed data operations in try-except block
- Added proper transaction rollback on error
- Enhanced error messages to distinguish between different error types
- Made the function idempotent (can be called multiple times safely)

**Files Modified**:
- `app.py` - Updated `seed_data()` function with error handling and duplicate checking

## Testing Recommendations

1. **Port Closing**:
   ```bash
   python run.py
   # Press Ctrl+C to test graceful shutdown
   # Verify port 5000 is released: netstat -an | grep 5000
   ```

2. **Calendar Booking**:
   - Login as admin
   - Go to patient details
   - Add a single appointment - should work
   - Add a recurring appointment - should create series properly
   - Verify calendar shows appointments correctly

3. **Recurring Appointments**:
   - Create appointment with "Every 2 Weeks" interval
   - Set limit to "Until Date" or "Number of Meetings"
   - Verify appointments project correctly in calendar view
   - Check audit logs confirm "recurring" appointments

4. **Seed Data**:
   - Click "Seed Data" button multiple times
   - Should not error after first time
   - Check logs for appropriate messages

## Security Improvements

- Better error handling prevents information leakage
- Proper transaction management prevents partial updates
- Input validation prevents malformed data from corrupting database

## Performance Improvements

- Calendar API now skips malformed data instead of crashing
- Process cleanup is more efficient with child process management
- Time parsing errors are caught early, preventing late failures

## Backwards Compatibility

All changes are backwards compatible:
- Existing appointments are unaffected
- Calendar view improvements don't break existing functionality
- Error handling is additive (catches errors that previously crashed)

## Files Modified

1. `run.py` - Process management improvements
2. `requirements.txt` - Added psutil
3. `app.py` - Multiple fixes:
   - `add_appointment()` - Full recurring appointment support
   - `api_slots()` - Time handling improvements
   - `seed_data()` - Error handling and duplicate prevention
