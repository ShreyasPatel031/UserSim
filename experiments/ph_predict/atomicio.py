"""Atomic file writes: write to a hidden temp file next to the target, then os.replace it into place, so a concurrent
reader (or a resumed run that checks os.path.exists) sees either the old file or the complete new one, never a partial one."""
import contextlib, os, tempfile


@contextlib.contextmanager
def atomic_path(path):
    """with atomic_path(p) as tmp: write the whole file to tmp. It replaces p only if the block finishes without an error."""
    d, base = os.path.split(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix="." + base + ".", suffix=".tmp")   # leading dot: invisible to *.json / day_* globs
    os.close(fd)
    try:
        # mkstemp makes the file 0600; keep the target's mode, or the usual 0644 for a new file
        os.chmod(tmp, os.stat(path).st_mode & 0o777 if os.path.exists(path) else 0o644)
        yield tmp
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
