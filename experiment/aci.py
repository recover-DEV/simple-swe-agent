"""Tools for inspecting, editing and testing a local Python repository."""

import hashlib
import os
import subprocess
import sys
from difflib import unified_diff
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TypedDict

from langchain_core.tools import StructuredTool

MAX_SOURCE_BYTES = 128_000
MAX_OUTPUT = 8_000


class PreparedEdit(TypedDict):
    path: str
    before_digest: str
    after_digest: str
    updated: str
    diff: str


def atomic_write(path: Path, data: bytes) -> None:
    """Replace a file only after its new contents have been written."""
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            temporary.write(data)
            temporary.close()
            os.replace(temporary_path, path)
        finally:
            temporary.close()
            temporary_path.unlink(missing_ok=True)


class RepositoryACI:
    def __init__(self, root: Path, timeout: int = 45):
        self.root = root.resolve(strict=True)
        self.timeout = timeout

    def source_path(self, relative: str) -> Path:
        """Resolve a repository-relative path to an existing Python file."""
        requested = Path(relative)
        if requested.anchor or '..' in requested.parts or requested.suffix.lower() != '.py':
            raise ValueError('Use a relative .py path inside the repository.')
        if any(part.startswith('.') for part in requested.parts):
            raise ValueError('Hidden paths are unavailable.')
        path = self.root / requested
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(self.root) or resolved != path or not resolved.is_file():
            raise ValueError('The path must identify a regular file inside the repository.')
        if resolved.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError('The file is too large for this tool.')
        return resolved

    def search_repo(self, query: str) -> dict:
        if not query.strip():
            raise ValueError('Search requires a nonempty query.')
        matches = []
        for candidate in sorted(self.root.rglob('*.py')):
            relative = candidate.relative_to(self.root).as_posix()
            try:
                text = self.source_path(relative).read_text(encoding='utf-8')
            except (OSError, ValueError):
                continue
            if query.casefold() in relative.casefold():
                matches.append({'path': relative})
            for number, line in enumerate(text.splitlines(), start=1):
                if query.casefold() in line.casefold():
                    matches.append({'path': relative, 'line': number, 'text': line[:280]})
            if len(matches) >= 25:
                break
        return {'ok': True, 'matches': matches[:25], 'limit_reached': len(matches) >= 25}

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> dict:
        lines = self.source_path(path).read_text(encoding='utf-8').splitlines()
        if start_line < 1 or (end_line is not None and end_line < start_line):
            raise ValueError('Use a valid 1-based inclusive line range.')
        end = min(len(lines), start_line + 149, end_line if end_line is not None else len(lines))
        text = '\n'.join(f'{n}: {lines[n - 1]}' for n in range(start_line, end + 1))
        return {'ok': True, 'path': path, 'total_lines': len(lines), 'text': text[:MAX_OUTPUT],
                'truncated': len(text) > MAX_OUTPUT or end < len(lines)}

    def prepare_edit(self, path: str, old: str, new: str) -> PreparedEdit:
        source = self.source_path(path)
        relative = source.relative_to(self.root)
        parts = tuple(part.casefold() for part in relative.parts)
        name = parts[-1]
        if {'test', 'tests'}.intersection(parts[:-1]) or name.startswith('test_') or name.endswith('_test.py') or name == 'conftest.py':
            raise ValueError('Test files are read-only.')
        before = source.read_bytes()
        text = before.decode('utf-8')
        old = old.replace('\r\n', '\n')
        new = new.replace('\r\n', '\n')
        normalized = text.replace('\r\n', '\n')
        offset = normalized.find(old)
        if not old or old == new or offset < 0 or normalized.find(old, offset + 1) != -1:
            raise ValueError('Supply a nonempty snippet that occurs exactly once and actually changes.')
        updated = normalized.replace(old, new, 1)
        diff = '\n'.join(unified_diff(normalized.split('\n'), updated.split('\n'),
                                     fromfile=relative.as_posix(), tofile=relative.as_posix(), lineterm=''))
        if '\r\n' in text and '\n' not in text.replace('\r\n', ''):
            updated = updated.replace('\n', '\r\n')
        after = updated.encode('utf-8')
        if len(after) > MAX_SOURCE_BYTES or len(diff) > MAX_OUTPUT:
            raise ValueError('Use a smaller edit so the full diff can be reviewed.')
        return {'path': relative.as_posix(), 'before_digest': hashlib.sha256(before).hexdigest(),
                'after_digest': hashlib.sha256(after).hexdigest(), 'updated': updated, 'diff': diff}

    def apply_edit(self, edit: PreparedEdit) -> dict:
        path = self.source_path(edit['path'])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest == edit['after_digest']:
            return {'ok': True, 'path': edit['path'], 'already_applied': True, 'diff': edit['diff']}
        if digest != edit['before_digest']:
            raise ValueError('The file changed after the diff was prepared. Read it and request a new edit.')
        atomic_write(path, edit['updated'].encode('utf-8'))
        return {'ok': True, 'path': edit['path'], 'diff': edit['diff']}

    def run_tests(self) -> dict:
        command = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider']
        allowed = {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'TMPDIR', 'SYSTEMDRIVE'}
        env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
        try:
            result = subprocess.run(command, cwd=self.root, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, encoding='utf-8', errors='replace',
                                    timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired:
            return {'ok': False, 'exit_code': None, 'error': f'pytest exceeded {self.timeout} seconds.'}
        return {'ok': result.returncode == 0, 'exit_code': result.returncode,
                'output': result.stdout[-MAX_OUTPUT:]}

    def model_tools(self) -> list[StructuredTool]:
        """Describe the ACI operations for native model tool calling."""
        return [
            StructuredTool.from_function(self.search_repo, description='Find Python paths or lines containing a literal query.'),
            StructuredTool.from_function(self.read_file, description='Read an existing Python file or a 1-based inclusive line range.'),
            StructuredTool.from_function(self.prepare_edit, name='replace_text',
                                         description='Request replacement of one exact snippet in a source file. Omit read_file line numbers.'),
            StructuredTool.from_function(self.run_tests, description='Run the repository pytest suite and return its exit code and output.'),
        ]
