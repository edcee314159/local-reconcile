from pathlib import Path
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont,QFontDatabase

def create_application(argv):
    app=QApplication.instance()
    if app is None:
        app=QApplication(argv)
        if not QFontDatabase.families():
            import os
            font_path=Path(os.environ.get("WINDIR","C:/Windows"))/"Fonts"/"msyh.ttc"
            if font_path.exists():QFontDatabase.addApplicationFont(str(font_path))
        app.setApplicationName("Local Reconcile")
        app.setOrganizationName("Local Reconcile")
        app.setFont(QFont("Microsoft YaHei",10))
        app.setStyle("Fusion")
        style=Path(__file__).parent/"ui"/"style.qss"
        if style.exists():app.setStyleSheet(style.read_text(encoding="utf-8"))
    return app

def main():
    app=create_application(sys.argv)
    if "--smoke-test" in sys.argv:
        import argparse
        from .smoke import run_smoke
        parser=argparse.ArgumentParser()
        parser.add_argument("--smoke-test",action="store_true")
        parser.add_argument("--output-dir",type=Path,required=True)
        options=parser.parse_args()
        run_smoke(options.output_dir)
        return 0
    from .ui.main_window import MainWindow
    window=MainWindow();window.show()
    return app.exec()

if __name__=="__main__":raise SystemExit(main())
