"""Drop-in alternates of a part. Standard library only: the board tool uses this module."""

from __future__ import annotations

# Keys of one item in the 'alternates' list of a part.
ALTERNATE_KEYS = ("manufacturer", "mpn", "mouser", "lcsc")
# KiCad field names. Each field has one value per alternate, in the order of the list.
ALT_FIELD_NAMES = {f"alt_{key}": f"Alt {name}" for key, name in
                   zip(ALTERNATE_KEYS, ("Manufacturer", "MPN", "Mouser", "LCSC"))}
ALT_SEPARATOR = ", "
# Value for an alternate that has no entry in a field, for example no LCSC number.
ALT_EMPTY = "-"


def split_alternates(fields: dict[str, str]) -> list[dict[str, str]]:
    """Read the Alt fields (KiCad field names, as in a BOM export).

    Return one dict per alternate with the keys manufacturer, mpn, mouser and lcsc.
    """
    columns = {key: [v.strip() for v in fields.get(ALT_FIELD_NAMES[f"alt_{key}"], "").split(",")]
               for key in ALTERNATE_KEYS}
    count = len([v for v in columns["mpn"] if v])
    out = []
    for i in range(count):
        item = {}
        for key, values in columns.items():
            value = values[i] if i < len(values) else ""
            item[key] = "" if value == ALT_EMPTY else value
        out.append(item)
    return out
