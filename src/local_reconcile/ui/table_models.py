from PySide6.QtCore import QAbstractTableModel,Qt
from PySide6.QtGui import QColor

class DataTableModel(QAbstractTableModel):
    def __init__(self,headers=(),rows=(),parent=None):
        super().__init__(parent);self.headers=tuple(headers);self.rows=list(rows)
    def rowCount(self,parent=None):return len(self.rows)
    def columnCount(self,parent=None):return len(self.headers)
    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid():return None
        value=self.rows[index.row()][index.column()] if index.column()<len(self.rows[index.row()]) else ""
        if role in (Qt.DisplayRole,Qt.ToolTipRole):return "" if value is None else str(value)
        if role==Qt.TextAlignmentRole:return int(Qt.AlignVCenter|Qt.AlignLeft)
        if role==Qt.ForegroundRole:
            text=str(value)
            if text=="已确认":return QColor("#087c66")
            if text in ("歧义","存在冲突","范围受限"):return QColor("#a56817")
        return None
    def headerData(self,section,orientation,role=Qt.DisplayRole):
        if role==Qt.DisplayRole:
            return self.headers[section] if orientation==Qt.Horizontal else str(section+1)
        return None
