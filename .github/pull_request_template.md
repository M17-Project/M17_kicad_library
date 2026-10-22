<!--
Use this template when you add or change parts.
The CI checks the changed parts and adds a comment with pictures and the result.
-->

## Parts

<!-- What do you add or change, and why? -->

## Checklist

- [ ] Each part has an official datasheet URL from the manufacturer.
- [ ] Each part has a Mouser number. If Mouser does not sell it, the part has a `source`.
- [ ] The LCSC number is added if JLCPCB has the part.
- [ ] I compared the footprint with the recommended land pattern in the datasheet.
- [ ] I compared the symbol pins with the pinout in the datasheet.
- [ ] Each new embedded 3D model is from the manufacturer and has an entry in `footprints/models.yaml`.
- [ ] Nothing is copied from EasyEDA/LCSC, SnapEDA, Ultra Librarian or other sources that do not allow redistribution.
- [ ] `uv run m17lib generate` and `uv run pytest` pass. The changed files in `symbols/` are in this pull request.
