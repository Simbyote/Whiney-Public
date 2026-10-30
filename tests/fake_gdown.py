"""
A stand-in for the gdown module in software tests (sandbox.gdown). A test
puts a local file behind a Drive file ID, makes the download fail the way
Drive does, or acts halfway through it (cancelling), and checks which IDs
the installer asked for.
"""
import shutil
from pathlib import Path


class FakeGdown:
    """gdown.download over local files: serves `files[file_id]`, returns None for an unknown ID, or raises `error`."""

    def __init__(self):
        self.files: dict[str, Path] = {}     # Drive file ID -> local file served as its download
        self.error: Exception | None = None  # raised by download(), as gdown does when Drive refuses
        self.requested: list[str] = []       # file IDs asked for, in order
        self.midway = None                   # called halfway through each download (e.g. to cancel it)

    def download(self, url, output, quiet=False, cancel=None):
        file_id = url.rsplit("id=", 1)[-1]
        self.requested.append(file_id)
        if self.error is not None:
            raise self.error
        if file_id not in self.files:
            return None                      # what gdown returns when it can't get the file
        # Like gdown: write into a temporary <output><8 chars>.part, checking `cancel` between chunks
        tmp = Path(f"{output}abcd1234.part")
        data = self.files[file_id].read_bytes()
        half = len(data) // 2
        with open(tmp, "wb") as f:
            f.write(data[:half])
            if self.midway:
                self.midway()
            if cancel is not None and cancel.is_set():
                raise RuntimeError("Download cancelled")     # gdown's DownloadCancelled
            f.write(data[half:])
        shutil.move(tmp, output)
        return output
