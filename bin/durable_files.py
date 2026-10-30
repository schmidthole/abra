"""small no-follow file primitives shared by durable json helpers."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat

MAX_BYTES = 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def revision(raw):
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def parent_directory(path, create=False):
    """pin each directory without following symlinks, including ancestors."""
    path = Path(path)
    require(
        path.is_absolute() and ".." not in path.parts,
        "path must be absolute without parent traversal",
    )
    require(path.name not in ("", ".", ".."), "invalid filename")
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        yield fd, path.name
    finally:
        os.close(fd)


def read_bytes(directory, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode), "expected a regular file")
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "checkpoint exceeds byte limit")
    return raw
