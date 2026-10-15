from PySide6.QtGui import QFontDatabase,QFontMetrics
from local_reconcile.app import create_application

def test_chinese_ui_glyphs_available():
    app=create_application([])
    assert QFontDatabase.families(),"GUI must have actual glyphs in headless QA"
    assert QFontMetrics(app.font()).inFontUcs4(ord("财"))
