"""Readable run index and transcripts derived from saved metadata and JSONL logs."""

import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .aci import atomic_write


@dataclass
class RunHistory:
    directory: Path
    source: Path | None
    workspace: Path | None
    mode: str
    rows: list[dict]
    log_updated: float

    @property
    def title(self) -> str:
        issue = next((row.get('message', '') for row in self.rows if row['event'] == 'issue'), '')
        lines = str(issue).strip().splitlines()
        title = lines[0].lstrip('# ').strip() if lines else ''
        return title or '题目未记录'

    @property
    def status(self) -> str:
        status = next((row for row in reversed(self.rows) if row['event'] == 'status'), {})
        if any(row['event'] == 'approval_pending' for row in self.rows):
            label = '等待审批'
        else:
            reason = status.get('stop_reason')
            label = {'model_finished': '已结束', 'step_limit': '达到步数上限',
                     'invalid_tool_call': '工具请求无效'}.get(reason, '可恢复' if status.get('next') else '待记录')
        code = status.get('last_test_exit_code')
        return f'{label} · pytest {code}' if code is not None else label


def read_history(directory: Path, log: Path) -> RunHistory:
    metadata = directory / 'target.json'
    target = json.loads(metadata.read_text(encoding='utf-8')) if metadata.is_file() else {}
    source = Path(target['source']) if target.get('source') else None
    copy = directory / 'repo'
    mode = target.get('mode', 'copy' if copy.is_dir() else '')
    workspace = source if mode == 'in-place' else copy if mode == 'copy' else None
    rows = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines() if line.strip()] if log.is_file() else []
    updated = log.stat().st_mtime if rows else directory.stat().st_mtime
    return RunHistory(directory, source, workspace, mode, rows, updated)


def table_text(value: str) -> str:
    return value.replace('\\', '\\\\').replace('|', '\\|').replace('[', '\\[').replace(']', '\\]')


def directory_link(path: Path | None, project: Path, index_directory: Path) -> str:
    if path is None:
        return '未记录'
    label = path.relative_to(project).as_posix() if path.is_relative_to(project) else path.as_posix()
    label = table_text(label)
    try:
        relative = Path(os.path.relpath(path, index_directory)).as_posix()
    except ValueError:
        return label
    return f'[{label}]({quote(relative)}/)' if path.is_dir() else label


def transcript(record: RunHistory) -> str:
    modes = {'in-place': '直接修复', 'copy': '副本'}
    lines = [f'# {record.title}', '', f'- 运行 ID：`{record.directory.name}`',
             f'- 原仓库：`{record.source or "未记录"}`', f'- 实际工作目录：`{record.workspace or "未记录"}`',
             f'- 模式：{modes.get(record.mode, "未记录")}', f'- 状态：{record.status}', '']
    for row in record.rows:
        event = row['event']
        if event == 'issue':
            lines += ['## 用户任务', '', *(f'> {line}' for line in str(row['message']).splitlines()), '']
        elif event == 'model':
            if row.get('message'):
                lines += ['## Agent 回复', '', str(row['message']), '']
        elif event == 'tool_result':
            result = row['result']
            label = '成功' if result.get('ok') else '失败'
            path = f' · `{result["path"]}`' if result.get('path') else ''
            lines += [f'### {row["step"]}. `{row["tool"]}` · {label}{path}', '']
            if 'exit_code' in result:
                lines += [f'pytest 退出码：`{result["exit_code"]}`', '']
            if result.get('diff'):
                lines += [*(f'    {line}' for line in result['diff'].splitlines()), '']
            else:
                details = result.get('output') or result.get('text') or json.dumps(result, ensure_ascii=False, indent=2)
                lines += ['<details>', '<summary>工具返回</summary>', '',
                          *(f'    {line}' for line in details.splitlines()), '', '</details>', '']
        elif event == 'approval_pending':
            request = row['request']
            lines += [f'## 待审批 · `{request["path"]}`', '',
                      *(f'    {line}' for line in request['diff'].splitlines()), '']
    if not record.rows:
        lines += ['这次运行尚无导出的对话日志。若 checkpoint 已保存，可用 `status` 重新导出。', '']
    return '\n'.join(lines) + '\n'


def refresh_history(project: Path, updated_run: str | None = None) -> Path:
    runs = project / 'runs'
    runs.mkdir(parents=True, exist_ok=True)
    index = runs / 'INDEX.md'
    logs = project / 'results' / 'logs'
    with closing(sqlite3.connect(runs / '.history.lock', timeout=10)) as lock:
        lock.execute('BEGIN EXCLUSIVE')
        records = []
        for directory in runs.iterdir():
            if directory.name.startswith('.') or not directory.is_dir():
                continue
            log = logs / f'{directory.name}.jsonl'
            if log.is_file() or (directory / 'target.json').is_file() or (directory / 'checkpoint.sqlite3').is_file():
                records.append(read_history(directory, log))
        lines = ['# Agent 任务索引', '', '实际工作目录是 Agent 读取、修改和测试代码的位置。', '',
                 '| 题目 | 原仓库 | 实际工作目录 | 模式 | 状态 | 对话 |',
                 '|---|---|---|---|---|---|']
        for record in sorted(records, key=lambda item: item.log_updated, reverse=True):
            history = record.directory / 'conversation.md'
            if updated_run is None or updated_run == record.directory.name or not history.is_file():
                atomic_write(history, transcript(record).encode('utf-8'))
            source = directory_link(record.source, project, runs)
            workspace = directory_link(record.workspace, project, runs)
            mode = {'in-place': '直接修复', 'copy': '副本'}.get(record.mode, '未记录')
            link = f'[{table_text(record.directory.name)}]({quote(record.directory.name)}/conversation.md)'
            lines.append(f'| {table_text(record.title)} | {source} | {workspace} | {mode} | {record.status} | {link} |')
        atomic_write(index, ('\n'.join(lines) + '\n').encode('utf-8'))
    return index
