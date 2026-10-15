"""Collect pinned wheels, license texts and corresponding Qt sources outside source."""
from pathlib import Path
from hashlib import sha256
from importlib import metadata
import argparse,json,shutil,sys,urllib.request,tarfile
from packaging.utils import parse_wheel_filename

QT_VERSION="6.10.3"
SOURCE_URLS=[
 f"https://download.qt.io/official_releases/qt/6.10/{QT_VERSION}/submodules/qtbase-everywhere-src-{QT_VERSION}.tar.xz",
 f"https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{QT_VERSION}-src/pyside-setup-everywhere-src-{QT_VERSION}.tar.xz",
 f"https://download.qt.io/official_releases/qt/6.10/{QT_VERSION}/submodules/qtsvg-everywhere-src-{QT_VERSION}.tar.xz",
 f"https://download.qt.io/official_releases/qt/6.10/{QT_VERSION}/submodules/qtimageformats-everywhere-src-{QT_VERSION}.tar.xz",
]
def prepare(source_root,output_root,downloads):
    source_root,output_root,downloads=map(Path,(source_root,output_root,downloads))
    third=output_root/"third_party";licenses=third/"licenses";sources=third/"sources"
    licenses.mkdir(parents=True,exist_ok=True);sources.mkdir(parents=True,exist_ok=True);downloads.mkdir(parents=True,exist_ok=True)
    runtime={"pyside6-essentials","shiboken6","openpyxl","et-xmlfile","defusedxml"}
    locked=[]
    for wheel in sorted((downloads/"wheels").glob("*.whl")):
        name,version,_,_=parse_wheel_filename(wheel.name)
        locked.append((name,f"{name}=={version} --hash=sha256:{sha256(wheel.read_bytes()).hexdigest()}"))
    if not runtime.issubset({n for n,_ in locked}):raise RuntimeError("Missing pinned runtime wheels")
    (source_root/"requirements.lock").write_text("\n".join(line for name,line in locked if name in runtime)+"\n",encoding="utf-8")
    (source_root/"requirements-dev.lock").write_text("\n".join(line for _,line in locked)+"\n",encoding="utf-8")
    dependency_manifest=[]
    for name in sorted(runtime):
        dist=metadata.distribution(name)
        dependency_manifest.append({"name":name,"version":dist.version})
        for item in dist.files or []:
            path=Path(str(item))
            if any("license" in part.lower() or "copying" in part.lower() for part in path.parts):
                actual=Path(dist.locate_file(item))
                if actual.is_file():
                    destination=licenses/name/Path(*path.parts[1:])
                    destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(actual,destination)
    base_python=Path(sys.base_prefix)
    for candidate in (base_python/"LICENSE.txt",base_python/"LICENSE"):
        if candidate.is_file():shutil.copy2(candidate,licenses/"Python-LICENSE.txt")
    manifest=[]
    for url in SOURCE_URLS:
        name=url.rsplit("/",1)[1];download=downloads/name
        if not download.exists():
            request=urllib.request.Request(url,headers={"User-Agent":"LocalReconcile-build/0.1"})
            with urllib.request.urlopen(request,timeout=90) as response,download.with_suffix(download.suffix+".partial").open("wb") as stream:
                shutil.copyfileobj(response,stream,1024*1024)
            download.with_suffix(download.suffix+".partial").replace(download)
        with tarfile.open(download,"r:xz") as archive:
            for member in archive:
                relative=Path(member.name)
                if member.isfile() and ("LICENSES" in relative.parts or (len(relative.parts)==2 and any(k in relative.name.upper() for k in ("LICENSE","COPYING")))):
                    if member.size>5*1024*1024:raise RuntimeError("License text exceeds limit")
                    contents=archive.extractfile(member).read()
                    target=(licenses/"Qt-sources"/relative).resolve()
                    if not target.is_relative_to(licenses.resolve()):raise RuntimeError("Unsafe upstream archive path")
                    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(contents)
        destination=sources/name
        shutil.copy2(download,destination)
        manifest.append({"file":name,"url":url,"sha256":sha256(download.read_bytes()).hexdigest(),"modified":False})
        print("Prepared "+name,flush=True)
    (sources/"source-manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    (third/"dependency-manifest.json").write_text(json.dumps(dependency_manifest,indent=2),encoding="utf-8")
    print("Licenses and corresponding library source archives prepared",flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--source-root",type=Path,required=True);p.add_argument("--output-root",type=Path,required=True);p.add_argument("--downloads",type=Path,required=True);a=p.parse_args()
    prepare(a.source_root,a.output_root,a.downloads)
