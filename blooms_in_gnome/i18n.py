import gettext
import os
from pathlib import Path

DOMAIN = "blooms-in-gnome"

_LOCALE_DIRS = [
    Path(__file__).resolve().parent.parent / "locale",
    Path.home() / ".local" / "share" / "locale",
    Path("/usr/share/locale"),
]

_LANG = os.environ.get("BLOOMS_LANG") or os.environ.get("LANG", "").split(".")[0]

_translation = None
for d in _LOCALE_DIRS:
    p = str(d)
    try:
        _translation = gettext.translation(DOMAIN, localedir=p, languages=[_LANG] if _LANG else None, fallback=True)
        break
    except Exception:
        continue

if _translation is None:
    _translation = gettext.NullTranslations()

_ = _translation.gettext
