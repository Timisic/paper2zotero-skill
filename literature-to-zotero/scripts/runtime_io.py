"""Platform boundaries for locks, private files and Unicode text evidence."""
from contextlib import contextmanager
import errno
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Iterator


@contextmanager
def file_lock(path: Path, *, blocking: bool = False) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if sys.platform == 'win32':
            import msvcrt
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b'\0')
                stream.flush()
            while True:
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as error:
                    if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    if not blocking:
                        raise ValueError('another operation is active for this run') from None
                    time.sleep(0.05)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError:
                raise ValueError('another operation is active for this run') from None
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def private_text(path: Path, text: str) -> None:
    """Secure before writing; close before replacing or cleaning up on Windows."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '-', suffix='.tmp')
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            if os.name == 'nt':
                subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                '-File', str(Path(__file__).with_name('protect-config.ps1')),
                                '-ConfigPath', str(temporary)], check=True, capture_output=True, timeout=20,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            stream.write(text)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def text_hash(text: str) -> str:
    """Notes hash UTF-8 text with LF newlines; binary attachments hash raw bytes."""
    return hashlib.sha256(text.replace('\r\n', '\n').replace('\r', '\n').encode('utf-8')).hexdigest()
