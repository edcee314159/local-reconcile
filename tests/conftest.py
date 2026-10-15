from dataclasses import replace
import hashlib
from local_reconcile.domain import RawTable, RawRow, RawCell, MappingSpec

def raw_table(role, rows, headers=("日期","金额","对方","编号","摘要")):
    digest=hashlib.sha256(repr(rows).encode()).hexdigest()
    raw=tuple(RawRow(f"{role}-{i}",i+2,tuple(RawCell(v,"number" if isinstance(v,(int,float,bool)) else "text") for v in row)) for i,row in enumerate(rows))
    return RawTable(role,f"{role}.csv",digest,None,1,None,tuple(headers),raw)

def mapping(**changes):
    return replace(MappingSpec(party_col=2,reference_col=3,summary_col=4,declared_account="SYNTHETIC-001",confirmed=True),**changes)

def dataset(role,rows,**changes):
    from local_reconcile.normalize import normalize
    return normalize(raw_table(role,rows),mapping(**changes))
