from threading import Event
from concurrent.futures import CancelledError
from PySide6.QtCore import QObject,QRunnable,QThreadPool,Signal,Slot

class _Signals(QObject):
    done=Signal(int,object,object)
    progress=Signal(int,str,int,int)

class _Work(QRunnable):
    def __init__(self,job_id,work,cancel):
        super().__init__();self.job_id=job_id;self.work=work;self.cancel=cancel;self.signals=_Signals()
    def run(self):
        result=error=None
        try:
            if self.cancel.is_set():raise CancelledError()
            result=self.work(lambda s,n,t:self.signals.progress.emit(self.job_id,s,n,t),self.cancel.is_set)
        except Exception as exc:error=exc
        self.signals.done.emit(self.job_id,result,error)

class JobRunner(QObject):
    progress=Signal(str,int,int)
    def __init__(self,parent=None):
        super().__init__(parent);self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1);self.jobs={};self.current=None
    def submit(self,job_id,work,on_result,on_error):
        for _,cancel,_,_ in self.jobs.values():cancel.set()
        # Canceled work may already be committing a file. A single worker keeps
        # every newer save behind that commit instead of letting it be overwritten.
        self.current=job_id;cancel=Event();worker=_Work(job_id,work,cancel)
        worker.signals.done.connect(self._done);worker.signals.progress.connect(self._progress)
        self.jobs[job_id]=(worker,cancel,on_result,on_error);self.pool.start(worker)
    @Slot(int,object,object)
    def _done(self,job_id,result,error):
        item=self.jobs.pop(job_id,None)
        if item is None or job_id!=self.current or item[1].is_set():return
        if isinstance(error,CancelledError):return
        if error is None:item[2](result)
        else:item[3](error)
    @Slot(int,str,int,int)
    def _progress(self,job_id,stage,current,total):
        if job_id==self.current and job_id in self.jobs and not self.jobs[job_id][1].is_set():
            self.progress.emit(stage,current,total)
    def cancel(self,job_id):
        if job_id in self.jobs:self.jobs[job_id][1].set()
        if self.current==job_id:self.current=None
    def shutdown(self):
        for _,cancel,_,_ in self.jobs.values():cancel.set()
        self.current=None;self.pool.waitForDone()
