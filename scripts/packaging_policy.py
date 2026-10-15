"""Do not shadow Windows' unversioned ICU with an unrelated toolchain ICU."""
from pathlib import Path
import re

def filter_windows_system_icu(binaries):
    return [entry for entry in binaries
            if Path(entry[0]).name.lower()!="icuuc.dll"
            and not re.fullmatch(r"icudt\d+\.dll",Path(entry[0]).name.lower())]
