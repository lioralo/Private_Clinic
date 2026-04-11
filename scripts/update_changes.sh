#!/bin/bash
awk '
/Changes Documentation - March 9, 2026 \(Session 1\)/ {
    print "# Changes Documentation - 2026-04-09 08:19\n"
    print "## Overview\n"
    print "Optimized calendar blocking date operations to fix an N+1 query performance bottleneck.\n"
    print "## Changes Made\n"
    print "### 1. **Fixed N+1 Query in Blocking Dates** ✅"
    print "**Problem**: The `api_calendar_block` function in `app.py` executed individual `INSERT INTO blocked_slots` and `UPDATE slots_override` statements inside a `for block_day in dates_to_create:` loop, causing significant database roundtrip overhead when dealing with large recurrences.\n"
    print "**Solution**:"
    print "- Refactored the loop to gather tuples for inserts and updates into two lists using list comprehensions."
    print "- Utilized `db.executemany` for batch inserting into `blocked_slots` and batch updating `slots_override`."
    print "- Captured the current timestamp once before the lists generation to ensure precise consistency."
    print "- Benchmarks demonstrated a ~24% improvement for 1000 items (0.0209s down to 0.0159s).\n"
    print "**Files Modified**: `app.py`\n\n---"
    print ""
}
{print}
' CHANGES.md > CHANGES_NEW.md
mv CHANGES_NEW.md CHANGES.md
