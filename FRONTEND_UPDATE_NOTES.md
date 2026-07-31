# Frontend Update Notes

This version redesigns the React frontend while keeping the existing Flask API and PostgreSQL database unchanged.

## Main changes

- Rebuilt the navigation, page headers, cards, filters, tables, comparison pages, tournament browser, and mobile layout.
- Removed visible `N/A`, `Unavailable`, and `Unknown` labels.
- Optional statistics are hidden when their source value is missing. Numeric zero is still shown because it is a valid statistic.
- Optional table columns are automatically hidden when the current result set contains no values for that field.
- Added a clearer loading message explaining that the free Render API may need about 40 seconds to wake up.
- Added friendlier network errors, responsive navigation, accessible keyboard table rows, and URL hash navigation.
- No database reset or backend data reload is needed.

## Deploy

Push the changed frontend files to the repository connected to Render:

```bash
git add frontend FRONTEND_UPDATE_NOTES.md
git commit -m "Redesign World Cup frontend and hide unavailable stats"
git push origin main
```

Render should rebuild the static frontend automatically. The PostgreSQL database is not changed by this update.
