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

    def chunks(self):
        try:
            while True:
                chunk=self.file.read(64*1024)
                if not chunk:break
                yield chunk
        finally:self.file.close()
