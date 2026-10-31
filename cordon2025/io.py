"""2025-only I/O boundary using donor IOFIX3/PATHFIX3 primitives.

No activate(), no global monkey-patching, no model operations. Numerical output
stays strict (no NaN/default=str). Critical publications fail closed; optional
telemetry is explicitly best effort. Every completed write is hash read back.
"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import csv
import json
import os
import time
import numpy as np

ATTEMPTS = 8


def donor():
    from .common import parent_module
    return parent_module('r1_15a2_runtime_io_hotfix_profile488')


def native_path(path, *, os_name=None):
    return donor()._native_path(path, os_name=os_name)


def retry(operation, *, attempts=ATTEMPTS):
    delay = 0.025
    for attempt in range(attempts):
        try:
            return operation()
        except OSError as exc:
            if not donor()._transient(exc) or attempt + 1 == attempts:
                raise
            time.sleep(delay)
            delay = min(delay * 1.8, 0.5)


def mkdir(path, *, exist_ok=True):
    retry(lambda: os.makedirs(native_path(path), exist_ok=exist_ok))


def sha256(path):
    return retry(lambda: donor().safe_sha256_file(path))


def read_json(path):
    def read():
        with open(native_path(path), encoding='utf-8-sig') as stream:
            def invalid(value):
                raise ValueError('NONFINITE_JSON_CONSTANT:' + value)
            return json.load(stream, parse_constant=invalid)
    return retry(read)


def read_csv(path):
    def read():
        with open(native_path(path), encoding='utf-8-sig', newline='') as stream:
            sample = stream.read(8192)
            stream.seek(0)
            return list(csv.DictReader(stream, delimiter=';' if sample.count(';') >= sample.count(',') else ','))
    return retry(read)


@contextmanager
def atomic_output(path, *, binary=False, encoding='utf-8', newline=None):
    """Yield a short sibling temp stream; publish only after flush+fsync+hash.

    A serializer exception leaves the old destination untouched. A failed
    post-publish readback never becomes a successful checkpoint.
    """
    target = Path(path)
    mkdir(target.parent)
    backend = donor()
    temporary = backend._short_temp_path(target, 'c2')
    stream = None
    try:
        mode = 'xb' if binary else 'x'
        kwargs = {} if binary else {'encoding': encoding, 'newline': newline}
        stream = retry(lambda: open(native_path(temporary), mode, **kwargs))
        yield stream
        stream.flush()
        os.fsync(stream.fileno())
        stream.close()
        stream = None
        expected = sha256(temporary)
        backend.replace_with_retry(temporary, target, attempts=ATTEMPTS)
        if sha256(target) != expected:
            raise OSError('CORDON_ATOMIC_READBACK_HASH_MISMATCH:' + str(target))
    finally:
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
        try:
            backend._unlink(temporary, missing_ok=True)
        except OSError:
            pass


def write_json(path, value):
    with atomic_output(path) as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)


def write_text(path, value):
    with atomic_output(path) as stream:
        stream.write(value)


def write_csv(path, rows, fields=None):
    if fields is None:
        rows = list(rows)
        fields = list(dict.fromkeys(k for row in rows for k in row))
    with atomic_output(path, encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter=';')
        writer.writeheader()
        writer.writerows(rows)


def write_npz(path, **arrays):
    normalized = {}
    for key, value in arrays.items():
        array = np.asarray(value)
        if array.dtype.hasobject:
            raise ValueError('NPZ_OBJECT_DTYPE_FORBIDDEN:' + key)
        if np.issubdtype(array.dtype, np.number) and not np.all(np.isfinite(array)):
            raise ValueError('NPZ_NONFINITE_ARRAY:' + key)
        normalized[key] = array
    with atomic_output(path, binary=True) as stream:
        np.savez_compressed(stream, **normalized)


def copy_verified(source, destination):
    """Strict source existence, whole-source hash verification, atomic copy."""
    source = Path(source)
    if not donor()._is_file(source):
        raise FileNotFoundError(str(source))
    before = sha256(source)
    with atomic_output(destination, binary=True) as stream:
        with open(native_path(source), 'rb') as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b''):
                stream.write(block)
        if sha256(source) != before:
            raise OSError('SOURCE_CHANGED_DURING_COPY')
    if sha256(destination) != before:
        raise OSError('COPY_READBACK_HASH_MISMATCH')
    return Path(destination)


def exception_text(exc):
    """COM and third-party exceptions may themselves fail in str()/repr()."""
    for convert in (str, repr):
        try:
            return convert(exc)
        except Exception:
            pass
    return '<unprintable ' + type(exc).__name__ + '>'


def telemetry_json(path, value):
    try:
        write_json(path, value)
        return {'published': True, 'optional': True}
    except Exception as exc:
        return {'published': False, 'optional': True, 'error_type': type(exc).__name__, 'error': exception_text(exc)}


def safe_failure_report(folder, primary, *, traceback_text='', emergency_stream=None):
    """Never replace the original failure with a secondary reporting exception."""
    report = {'status': 'BLOCKED', 'reason': exception_text(primary), 'exception': type(primary).__name__,
              'apply_permitted': False, 'live_visum_tested': False, 'reporting_errors': []}
    if folder is not None:
        try:
            write_text(Path(folder) / 'TRACEBACK.txt', traceback_text)
        except Exception as exc:
            report['reporting_errors'].append({'operation': 'traceback', 'type': type(exc).__name__, 'reason': exception_text(exc)})
        try:
            write_json(Path(folder) / 'COMMAND_STATUS.json', report)
        except Exception as exc:
            report['reporting_errors'].append({'operation': 'status', 'type': type(exc).__name__, 'reason': exception_text(exc)})
    if emergency_stream is not None:
        try:
            emergency_stream.write(json.dumps(report, ensure_ascii=True, allow_nan=False) + '\n')
            emergency_stream.flush()
        except Exception:
            pass
    return report
