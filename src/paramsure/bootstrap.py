from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from .excel_io import iter_excel_files, load_product_parameters
from .store import ParameterStore


def file_fingerprint(path: Path) -> tuple[int, int, str]:
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return stat.st_mtime_ns, stat.st_size, digest.hexdigest()


def auto_index_product_params(store: ParameterStore, params_dir: Path) -> dict:
    if not params_dir.exists():
        return {"params_dir": str(params_dir), "indexed": 0, "skipped": 0, "missing": True}

    indexed = 0
    skipped = 0
    total_params = 0
    files = list(iter_excel_files(params_dir))
    for file in files:
        source_path = str(file)
        mtime_ns, size, sha256 = file_fingerprint(file)
        if store.source_fingerprint(source_path) == (mtime_ns, size, sha256):
            skipped += 1
            continue
        store.clear_source(source_path)
        parameters = load_product_parameters(file)
        count = store.add_parameters(parameters)
        store.mark_source(
            source_path,
            mtime_ns,
            size,
            sha256,
            datetime.now(timezone.utc).isoformat(),
            count,
        )
        indexed += 1
        total_params += count
    return {
        "params_dir": str(params_dir),
        "files": len(files),
        "indexed": indexed,
        "skipped": skipped,
        "parameter_count": total_params,
        "missing": False,
    }
