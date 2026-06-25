# Design System Update Guide

## Current Status

### ✅ Completed Merges
- All 7 remote branches merged into main
- AI S design reference files added to repository
- Core functionality verified and working

### ✅ Design Updates Applied
- `layout.html` - Base layout with Tailwind CSS color system
- `static/style.css` - Custom CSS variables and design tokens
- `crm.html` - Patient list with modern stats cards and table
- `admin_home.html` - Dashboard with new layout
- `patient_home.html` - Partial update to header section

### ✅ Fixes Applied
- Fixed duplicate `patient_appearance` column in schema.sql
- Added missing `datetime` imports in test_app.py
- Fixed backup_files handling to return Path objects

## Design System Overview

### Color Palette
- **Primary**: `#134e4a` (Teal) - Main brand color
- **Secondary**: `#6c7792` (Gray-Blue) - Secondary actions
- **Tertiary**: `#e3b453` (Amber/Gold) - Highlights
- **Background**: `#f7f9fb` (Light Gray) - Page background

### Typography
- **Headlines**: Manrope, Assistant (for Hebrew)
- **Body**: Inter, Assistant
- **Sizes**: Use Tailwind scale (text-sm, text-base, text-lg, etc.)

### Components
- **Buttons**: Use primary color with rounded-xl
- **Cards**: bg-white, rounded-2xl, shadow-sm, border border-slate-100
- **Badges**: Rounded-full with appropriate background colors
- **Icons**: Material Symbols Outlined (preferred) or Bootstrap Icons

### Key Tailwind Classes to Use
```
Colors: text-primary, bg-primary, border-slate-100
Spacing: gap-4, p-5, mb-6, px-4
Rounded: rounded-lg, rounded-xl, rounded-2xl, rounded-full
Shadows: shadow-sm
Typography: font-bold, font-semibold, text-slate-500
```

## Templates to Update

### High Priority (User-Facing)
1. `patient_dashboard.html` - Main patient view
2. `calendar.html` - Appointment calendar
3. `patient_detail.html` - Detailed patient info
4. `edit_patient.html` / `add_patient.html` - Forms

### Medium Priority (Administrative)
5. `admin_profile.html` - Settings and backups
6. `groups.html` - Group management
7. `manage_resources.html` - Resource management  
8. `messages.html` - Messaging interface

### Low Priority (Secondary)
9. `login.html` - Login form
10. `register.html` - Registration form
11. `index.html` - Landing page redirect
12. `resources.html` - Resources display

## Implementation Pattern

### Before (Bootstrap)
```html
<div class="card border-0 shadow-sm">
  <div class="card-header bg-white border-0">
    <h5 class="fw-bold mb-0">Title</h5>
  </div>
  <div class="card-body px-4 pb-4">
    Content...
  </div>
</div>
```

### After (Tailwind)
```html
<div class="bg-white rounded-2xl shadow-sm border border-slate-100">
  <div class="p-5 border-b border-slate-100">
    <h5 class="font-bold">Title</h5>
  </div>
  <div class="p-5">
    Content...
  </div>
</div>
```

## Next Steps

1. **Continue template updates** - Use the pattern above for remaining templates
2. **Test consistency** - Verify each page looks cohesive with others
3. **Run tests** - Fix remaining test failures as templates are updated
4. **Review AI S components** - Reference React components in AI S/ folder for inspiration
5. **Polish details** - Fine-tune spacing, colors, and interactions

## Resources

- Design files: `/workspaces/Private_Clinic/AI S/`
- Current styles: `/workspaces/Private_Clinic/static/style.css`
- Color config: `/workspaces/Private_Clinic/templates/layout.html` (Tailwind config)
