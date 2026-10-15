"""Versioned, non-executable project snapshots with atomic replacement."""
from __future__ import annotations
from dataclasses import fields, is_dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import get_type_hints, get_origin, get_args, Union, Literal
import json, math, os, tempfile, types
from . import domain
from .domain import LocalReconcileError, ProjectSnapshot, ReviewState
from .normalize import normalize
from .matching import reconcile
from .review import apply_review

MAX_PROJECT_BYTES = 100*1024*1024
_NAMES = ("RawCell","RawRow","RawTable","MappingSpec","Issue","Transaction","Dataset",
          "MatchConfig","Candidate","Difference","AmbiguityGroup","MatchResult",
          "ConfirmedPair","ReviewEvent","ReviewState","ProjectSnapshot")
_TYPES = {name:getattr(domain,name) for name in _NAMES}

def _encode(value):
    if is_dataclass(value):
        return {"@type":type(value).__name__,**{f.name:_encode(getattr(value,f.name)) for f in fields(value)}}
    if isinstance(value,datetime):
        return {"@datetime":value.isoformat()}
    if isinstance(value,date):
        return {"@date":value.isoformat()}
    if isinstance(value,tuple):
        return {"@tuple":[_encode(v) for v in value]}
    return value

def _valid(value,hint):
    origin,args=get_origin(hint),get_args(hint)
    if origin in (Union,types.UnionType):
        return any(_valid(value,h) for h in args)
    if origin is Literal:
        return value in args and type(value) in tuple(type(a) for a in args)
    if origin is tuple:
        if not isinstance(value,tuple):
            return False
        if len(args)==2 and args[1] is Ellipsis:
            return all(_valid(v,args[0]) for v in value)
        return len(value)==len(args) and all(_valid(v,h) for v,h in zip(value,args))
    if hint is float:
        return type(value) is float and math.isfinite(value)
    return type(value) is hint

def _decode(value,depth=0):
    if depth>30:
        raise ValueError("depth")
    if isinstance(value,list):
        raise ValueError("untyped list")
    if not isinstance(value,dict):
        if value is None or type(value) in (str,int,bool) or (type(value) is float and math.isfinite(value)):
            return value
        raise ValueError("primitive")
    if set(value)=={"@date"}:
        return date.fromisoformat(value["@date"])
    if set(value)=={"@datetime"}:
        return datetime.fromisoformat(value["@datetime"])
    if set(value)=={"@tuple"} and isinstance(value["@tuple"],list):
        return tuple(_decode(v,depth+1) for v in value["@tuple"])
    cls=_TYPES.get(value.get("@type",""))
    if cls is None or set(value)!={f.name for f in fields(cls)}|{"@type"}:
        raise ValueError("schema")
    decoded={f.name:_decode(value[f.name],depth+1) for f in fields(cls)}
    hints=get_type_hints(cls)
    if not all(_valid(decoded[k],hints[k]) for k in decoded):
        raise ValueError("field type")
    return cls(**decoded)

def validate_snapshot(snapshot):
    if not isinstance(snapshot,ProjectSnapshot) or type(snapshot.schema_version) is not int or snapshot.schema_version!=1:
        raise LocalReconcileError("project_version","项目版本不支持，请使用匹配版本的软件")
    ids=[]
    for ds in (snapshot.bank,snapshot.ledger):
        if len(ds.raw.rows)>100000 or len(ds.raw.headers)>200:
            raise LocalReconcileError("project_limit","项目记录数超过限制")
        rows={r.id for r in ds.raw.rows}
        if len(rows)!=len(ds.raw.rows):
            raise LocalReconcileError("project_rows","原始行编号重复")
        if any(len(r.cells)>200 or r.source_line<1 or any(isinstance(c.value,str) and len(c.value)>32767 for c in r.cells) for r in ds.raw.rows):
            raise LocalReconcileError("project_rows","原始记录不符合范围要求")
        ids.extend(rows)
        if normalize(ds.raw,ds.mapping)!=ds:
            raise LocalReconcileError("project_data","规范化数据与输入记录不一致")
    if len(ids)!=len(set(ids)):
        raise LocalReconcileError("project_rows","双方原始行编号冲突")
    if reconcile(snapshot.bank,snapshot.ledger,snapshot.config)!=snapshot.result:
        raise LocalReconcileError("project_result","核对结果与输入或规则不一致")
    replay=replace(snapshot,review=ReviewState())
    for event in snapshot.review.events:
        replay=apply_review(replay,event)
    if replay.review!=snapshot.review:
        raise LocalReconcileError("project_review","复核状态与操作记录不一致")

def protect_input_path(snapshot,path):
    from hashlib import sha256
    path=Path(path)
    if path.name.casefold() in {snapshot.bank.raw.filename.casefold(),snapshot.ledger.raw.filename.casefold()}:
        raise LocalReconcileError("source_overwrite","输出文件不得覆盖或沿用输入文件名，请另存")
    if path.exists() and path.is_file() and path.stat().st_size<=25*1024*1024:
        digest=sha256(path.read_bytes()).hexdigest()
        if digest in {snapshot.bank.raw.sha256,snapshot.ledger.raw.sha256}:
            raise LocalReconcileError("source_overwrite","目标属于本次原始输入，请另存")

def save_project(snapshot,path):
    path=Path(path)
    protect_input_path(snapshot,path)
    temporary=None
    try:
        validate_snapshot(snapshot)
        content=json.dumps(_encode(snapshot),ensure_ascii=False,allow_nan=False,separators=(",",":")).encode("utf-8")
        if len(content)>MAX_PROJECT_BYTES:
            raise LocalReconcileError("project_limit","项目超过 100 MiB，未覆盖旧文件")
        with tempfile.NamedTemporaryFile(dir=path.parent,suffix=".tmp",delete=False) as stream:
            temporary=Path(stream.name)
            stream.write(content);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    except LocalReconcileError:
        raise
    except Exception:
        raise LocalReconcileError("project_save","项目保存失败，请检查目录、文件占用和剩余空间") from None
    finally:
        if temporary and temporary.exists():
            temporary.unlink(missing_ok=True)

def load_project(path):
    try:
        path=Path(path)
        if path.stat().st_size>MAX_PROJECT_BYTES:
            raise LocalReconcileError("project_limit","项目超过 100 MiB")
        content=json.loads(path.read_text(encoding="utf-8"))
        if type(content) is not dict or content.get("schema_version")!=1:
            raise LocalReconcileError("project_version","项目版本不支持或格式不正确")
        snapshot=_decode(content)
        validate_snapshot(snapshot)
        return snapshot
    except LocalReconcileError:
        raise
    except Exception:
        raise LocalReconcileError("project_load","项目无法打开，格式损坏或字段无效；原文件未修改") from None
