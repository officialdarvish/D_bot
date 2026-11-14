"""Bound Telegram downloads on disk and stream fixed-size chunks to clients."""
import tempfile


class MediaFile:
    def __init__(self, limit):
        self.limit=limit
        self.file=tempfile.TemporaryFile(mode='w+b')

    def write(self,data):
        if self.file.tell()+len(data)>self.limit:raise ValueError('Media exceeds size limit')
        return self.file.write(data)

    def __getattr__(self,name):return getattr(self.file,name)

    def chunks(self,length=None):
        try:
            remaining=length
            while remaining is None or remaining>0:
                chunk=self.file.read(64*1024 if remaining is None else min(64*1024,remaining))
                if not chunk:break
                if remaining is not None:remaining-=len(chunk)
                yield chunk
        finally:self.file.close()
