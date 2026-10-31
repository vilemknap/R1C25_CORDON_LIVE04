"""Lightweight SQL call timing proxy; no query changes or connection replacement."""
class MeasuredConnection:
    def __init__(self, connection, telemetry, proof=False):
        self.connection=connection;self.telemetry=telemetry
        self.prefix='CAPTURE_PROOF_SQLITE' if proof else 'CAPTURE_MAIN_SQLITE'
    def __getattr__(self, name):return getattr(self.connection,name)
    def _call(self,name,*args,**kw):
        key=self.prefix+'.'+name
        self.telemetry.count(key+'.calls')
        with self.telemetry.span(key):
            result=getattr(self.connection,name)(*args,**kw)
        return result
    def execute(self,*args,**kw):return self._call('execute',*args,**kw)
    def executemany(self,*args,**kw):return self._call('executemany',*args,**kw)
    def executescript(self,*args,**kw):return self._call('executescript',*args,**kw)
    def commit(self):return self._call('commit')
    def close(self):return self._call('close')
