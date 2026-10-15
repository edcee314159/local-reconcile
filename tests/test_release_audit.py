from pathlib import Path
import pytest
from scripts.audit_release import audit_release

def test_uncovered_qt_module_blocks_release(tmp_path):
    (tmp_path/"Qt6MadeUp.dll").write_bytes(b"not a real dll")
    with pytest.raises(ValueError,match="Uncovered Qt"):
        audit_release(tmp_path)
