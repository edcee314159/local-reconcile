"""Verify distributed Qt modules have bundled corresponding sources."""
from pathlib import Path
from hashlib import file_digest
import argparse,json

_BASE={"Qt6Core.dll","Qt6Gui.dll","Qt6Widgets.dll","Qt6Network.dll","Qt6OpenGL.dll","Qt6OpenGLWidgets.dll","Qt6PrintSupport.dll","Qt6Sql.dll","Qt6Test.dll","Qt6Xml.dll","Qt6Concurrent.dll","Qt6DBus.dll"}
_EXTRA={"Qt6Svg.dll":"qtsvg","Qt6SvgWidgets.dll":"qtsvg"}
def audit_release(app_dir):
    app_dir=Path(app_dir);dlls=sorted(app_dir.rglob("*.dll"))
    qt=[p for p in dlls if p.name.startswith("Qt6")]
    unknown=sorted({p.name for p in qt if p.name not in _BASE and p.name not in _EXTRA})
    if unknown:raise ValueError("Uncovered Qt modules: "+", ".join(unknown))
    required={"qtbase","pyside-setup"}|{_EXTRA[p.name] for p in qt if p.name in _EXTRA}
    source_root=app_dir/"third_party"/"sources"
    manifest=json.loads((source_root/"source-manifest.json").read_text(encoding="utf-8"))
    actual_sources=set()
    for item in manifest:
        name=item["file"];path=(source_root/name).resolve()
        if not path.is_relative_to(source_root.resolve()):raise ValueError("Invalid source path")
        with path.open("rb") as f:digest=file_digest(f,"sha256").hexdigest()
        if digest!=item["sha256"]:raise ValueError("Source checksum mismatch")
        actual_sources.add(name.split("-everywhere",1)[0])
    if not required.issubset(actual_sources):raise ValueError("Missing corresponding source: "+str(required-actual_sources))
    if not (app_dir/"third_party"/"licenses"/"Python-LICENSE.txt").is_file():raise ValueError("Missing Python license")
    result={"qt_modules":sorted({p.name for p in qt}),"source_coverage":"complete for listed Qt modules",
            "dlls":[{"file":str(p.relative_to(app_dir)),"size":p.stat().st_size} for p in dlls]}
    (app_dir/"third_party"/"binary-inventory.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    return result

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--app-dir",type=Path,required=True);args=parser.parse_args()
    result=audit_release(args.app_dir)
    print(json.dumps({"qt_modules":result["qt_modules"],"source_coverage":result["source_coverage"]}))
