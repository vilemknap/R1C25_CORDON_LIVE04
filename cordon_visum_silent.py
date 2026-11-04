"""Silent Visum run (LIVE04.5.3): no dialogs that have to be clicked away.

Standard library only.  For ONE launcher run:

* Visum procedure warnings: the documented GUI user preference
  ``SuppressWarningsDuringProcExec`` = 1 (and ``SaveWarningsToErrorFile`` = 1),
  each write verified by read-back; the Visum message file is redirected into
  the boot folder.  Everything is restored to the exact original values at the
  end, also after an error.  This is the same mechanism as the earlier silent
  R1 TD scripts (parent/reference_v19, SilentProcedureWarnings).
* Python output: ``print`` / stderr / ``warnings`` of the launcher and of every
  imported module go to ``PYTHON_CONSOLE.log`` in the boot folder instead of the
  Visum script output window.

Critical Visum ERROR dialogs are not suppressed by this preference and are
never clicked automatically (no SendKeys).  If the preference is not reachable
through COM in a Visum build, the run continues and ``SILENT_MODE.json``
says ``NOT_ACCESSIBLE`` with the manual setting to use.
"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import io
import json
import os
import sys
import warnings

WARNING_ATTR = 'SuppressWarningsDuringProcExec'
LOG_ATTR = 'SaveWarningsToErrorFile'
GUI_NAMES = ('GUI', 'Gui', 'GUIUserPreferences', 'GuiUserPreferences', 'UserInterface', 'UI',
             'GUIOptions', 'GuiOptions', 'General')
MANUAL_HINT = ('Visum: Edit > User preferences > User interface > Warnings > '
               'Suppress output of warnings during procedure execution')


def _flag(obj, attr):
    v = obj.AttValue(attr)
    if v is None or str(v).strip() == '':
        raise ValueError('EMPTY_PREFERENCE:' + attr)
    if isinstance(v, str) and v.strip().lower() in ('true', 'false'):
        return int(v.strip().lower() == 'true')
    return int(float(str(v).strip().replace(',', '.')) != 0)


def _candidates(visum, probes):
    try:
        prefs = visum.UserPreferences
    except Exception as exc:
        probes.append('UserPreferences: ' + type(exc).__name__)
        return
    for name in GUI_NAMES:
        try:
            sub = getattr(prefs, name)
            if callable(sub):
                sub = sub()
            if sub is not None:
                yield 'UserPreferences.' + name, sub
        except Exception:
            continue
    yield 'UserPreferences', prefs


class _Tee(io.TextIOBase):
    """Line-oriented text sink into the console log (never into Visum)."""
    def __init__(self, handle, label):
        self.handle = handle; self.label = label

    def writable(self):
        return True

    def write(self, text):
        try:
            self.handle.write(text); self.handle.flush()
        except Exception:
            pass
        return len(text)

    def flush(self):
        try:
            self.handle.flush()
        except Exception:
            pass


class SilentVisum:
    def __init__(self, visum, folder):
        self.visum = visum
        self.folder = Path(folder) if folder else None
        self.changes = []
        self.message_old = None
        self.report = {'schema': 'R1C25_SILENT_MODE_V1', 'procedure_warnings': 'NOT_TRIED',
                       'python_console': 'NOT_REDIRECTED', 'restored': False, 'errors': []}
        self._streams = None
        self._log = None
        self._showwarning = None

    # ------------------------------------------------------------ python output
    def redirect_python(self):
        if self.folder is None:
            return
        try:
            self._log = open(self.folder / 'PYTHON_CONSOLE.log', 'a', encoding='utf-8', buffering=1)
        except Exception as exc:
            self.report['errors'].append('console log: ' + repr(exc)[:200])
            return
        self._streams = (sys.stdout, sys.stderr)
        sys.stdout = _Tee(self._log, 'stdout'); sys.stderr = _Tee(self._log, 'stderr')
        self._showwarning = warnings.showwarning

        def show(message, category, filename, lineno, file=None, line=None):
            try:
                self._log.write(warnings.formatwarning(message, category, filename, lineno, line))
            except Exception:
                pass
        warnings.showwarning = show
        self.report['python_console'] = str(self.folder / 'PYTHON_CONSOLE.log')

    def restore_python(self):
        if self._streams is not None:
            sys.stdout, sys.stderr = self._streams
            self._streams = None
        if self._showwarning is not None:
            warnings.showwarning = self._showwarning
            self._showwarning = None
        if self._log is not None:
            try:
                self._log.close()
            except Exception:
                pass
            self._log = None

    # --------------------------------------------------------- visum warnings
    def _set(self, obj, attr, value):
        old = _flag(obj, attr)
        if old != int(value):
            obj.SetAttValue(attr, int(value))
            self.changes.append((obj, attr, old))
        if _flag(obj, attr) != int(value):
            raise RuntimeError('PREFERENCE_READBACK_FAILED:' + attr)
        return old

    def suppress_warnings(self):
        probes = []
        for path, obj in _candidates(self.visum, probes):
            try:
                original = _flag(obj, WARNING_ATTR)      # read-only probe first
            except Exception as exc:
                probes.append('%s: %s' % (path, type(exc).__name__))
                continue
            try:
                self._set(obj, WARNING_ATTR, 1)
            except Exception as exc:
                self.report['errors'].append('%s.%s: %r' % (path, WARNING_ATTR, exc))
                continue
            self.report.update(procedure_warnings='SUPPRESSED_VERIFIED', com_path=path, previous=original)
            try:
                self._set(obj, LOG_ATTR, 1)
                self.report['warnings_to_message_file'] = 'ENABLED'
            except Exception as exc:
                self.report['warnings_to_message_file'] = 'NOT_VERIFIED:' + type(exc).__name__
            self._redirect_message_file()
            return
        self.report.update(procedure_warnings='NOT_ACCESSIBLE', probes=probes[:14], manual_setting=MANUAL_HINT)

    def _redirect_message_file(self):
        if self.folder is None:
            return
        try:
            old = str(self.visum.MessageFileName or '')
            if not old:
                return
            new = str(self.folder / 'VISUM_MESSAGES.txt')
            self.visum.SetMessageFileName(new)
            got = str(self.visum.MessageFileName or '')
            if os.path.normcase(os.path.normpath(got)) != os.path.normcase(os.path.normpath(new)):
                self.visum.SetMessageFileName(old)
                raise RuntimeError('MESSAGE_FILE_READBACK')
            self.message_old = old
            self.report['visum_message_file'] = new
        except Exception as exc:
            self.report['visum_message_file'] = 'NOT_REDIRECTED:' + type(exc).__name__

    def restore_visum(self):
        if self.message_old is not None:
            try:
                self.visum.SetMessageFileName(self.message_old)
            except Exception as exc:
                self.report['errors'].append('message file restore: ' + repr(exc)[:200])
            self.message_old = None
        for obj, attr, old in reversed(self.changes):
            try:
                obj.SetAttValue(attr, old)
                if _flag(obj, attr) != old:
                    raise RuntimeError('READBACK')
            except Exception as exc:
                self.report['errors'].append('restore %s: %r' % (attr, exc))
        self.changes = []
        self.report['restored'] = not any(e.startswith('restore') for e in self.report['errors'])

    def write_report(self):
        if self.folder is None:
            return
        try:
            (self.folder / 'SILENT_MODE.json').write_text(json.dumps(self.report, indent=2, default=str),
                                                         encoding='utf-8')
        except Exception:
            pass


@contextmanager
def silent(visum, folder):
    s = SilentVisum(visum, folder)
    s.redirect_python()
    try:
        if visum is not None:
            try:
                s.suppress_warnings()
            except Exception as exc:          # never block the run on the preference itself
                s.report['errors'].append('suppress: ' + repr(exc)[:300])
        s.write_report()
        yield s.report
    finally:
        try:
            s.restore_visum()
        finally:
            s.restore_python()
            s.write_report()
