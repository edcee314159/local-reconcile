from scripts.packaging_policy import filter_windows_system_icu

def test_never_shadow_windows_icu_with_unrelated_runtime():
    binaries=[("icuuc.dll","foreign/icuuc.dll","BINARY"),("icudt78.dll","foreign/icudt78.dll","BINARY"),("PySide6/Qt6Core.dll","Qt6Core.dll","BINARY")]
    assert filter_windows_system_icu(binaries)==[("PySide6/Qt6Core.dll","Qt6Core.dll","BINARY")]
