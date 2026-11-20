"""Command-line entry point for starting, inspecting and resuming a repair."""

import argparse
import json
import re
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command, StateSnapshot
from openai import OpenAIError

from experiment.aci import RepositoryACI, atomic_write
from experiment.agent import build_agent
from experiment.model import create_model

PROJECT = Path(__file__).resolve().parent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Repair a local Python repository with a LangGraph agent.')
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('start', help='Copy a repository and start a repair.')
    start.add_argument('run_id')
    start.add_argument('--repo', type=Path, required=True)
    issue = start.add_mutually_exclusive_group(required=True)
    issue.add_argument('--issue')
    issue.add_argument('--issue-file', type=Path)
    start.add_argument('--max-steps', type=int, default=12)

    status = commands.add_parser('status', help='Show the last checkpoint and any pending diff.')
    status.add_argument('run_id')
    resume = commands.add_parser('resume', help='Continue a stopped run or decide a pending approval.')
    resume.add_argument('run_id')
    decision = resume.add_mutually_exclusive_group()
    decision.add_argument('--approve', dest='approved', action='store_const', const=True, default=None)
    decision.add_argument('--reject', dest='approved', action='store_const', const=False)
    resume.add_argument('--comment', default='')
    return parser.parse_args(argv)


def ignore_copy(directory: str, names: list[str]) -> set[str]:
    candidates = {name for name in names if name.startswith('.') or name in {'__pycache__', 'runs', 'results'}}
    return candidates.union(name for name in names if (Path(directory) / name).is_symlink()
                            or (Path(directory) / name).is_junction())


def start_run(args: argparse.Namespace, directory: Path) -> dict:
    source = args.repo.resolve(strict=True)
    issue = args.issue if args.issue is not None else args.issue_file.read_text(encoding='utf-8')
    if not source.is_dir() or args.max_steps < 1 or not issue.strip():
        raise ValueError('Provide a repository directory, a nonempty issue and a positive step limit.')
    directory.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source, directory / 'repo', ignore=ignore_copy)
    return {'messages': [('human', issue)], 'steps': 0, 'max_steps': args.max_steps}


def resume_input(args: argparse.Namespace, snapshot: StateSnapshot) -> Command | None:
    if not snapshot.values or not snapshot.next:
        raise ValueError('There is no unfinished checkpoint for this run.')
    if snapshot.interrupts:
        if args.approved is None:
            raise ValueError('This checkpoint is waiting for --approve or --reject. Use status to view the diff.')
        return Command(resume={'approved': args.approved, 'comment': args.comment})
    if args.approved is not None or args.comment:
        raise ValueError('This checkpoint has no pending approval. Resume without a decision.')
    return None


def write_trace(snapshot: StateSnapshot, path: Path) -> None:
    rows = []
    step = 0
    for message in snapshot.values['messages']:
        if isinstance(message, HumanMessage):
            rows.append({'event': 'issue', 'message': message.content})
        elif isinstance(message, AIMessage):
            rows.append({'event': 'model', 'tool_calls': message.tool_calls, 'message': message.content})
        elif isinstance(message, ToolMessage):
            step += 1
            rows.append({'event': 'tool_result', 'step': step, 'tool': message.name,
                         'call_id': message.tool_call_id, 'result': json.loads(message.content)})
    for pending in snapshot.interrupts:
        rows.append({'event': 'approval_pending', 'request': pending.value})
    rows.append({'event': 'status', 'steps': snapshot.values['steps'], 'next': snapshot.next,
                 'stop_reason': snapshot.values.get('stop_reason'),
                 'last_test_exit_code': snapshot.values.get('last_test_exit_code')})
    path.parent.mkdir(parents=True, exist_ok=True)
    data = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows)
    atomic_write(path, data.encode('utf-8'))


def show_status(snapshot: StateSnapshot, directory: Path) -> None:
    state = snapshot.values
    print(f'Run: {directory.name} | Tool calls: {state["steps"]}/{state["max_steps"]}')
    print(f'Repository: {directory / "repo"}')
    for pending in snapshot.interrupts:
        print('Approval required. Review the diff and resume with --approve or --reject.')
        print(pending.value['diff'])
    if snapshot.next and not snapshot.interrupts:
        print(f'Pending checkpoint: {", ".join(snapshot.next)}')
    if not snapshot.next:
        print(f'Stopped: {state.get("stop_reason")}')
        last_message = state['messages'][-1]
        if isinstance(last_message, AIMessage) and last_message.content:
            print(last_message.content)
    exit_code = state.get('last_test_exit_code')
    print(f'Latest pytest exit code: {exit_code}' if exit_code is not None else 'Current changes have no confirmed pytest result.')


def run_command(args: argparse.Namespace) -> None:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', args.run_id):
        raise ValueError('Use a run ID with 1–64 ASCII letters, numbers, hyphens or underscores.')
    directory = PROJECT / 'runs' / args.run_id
    initial = start_run(args, directory) if args.command == 'start' else None
    database = directory / 'checkpoint.sqlite3'
    if initial is None and not database.is_file():
        raise ValueError(f'No checkpoint for {args.run_id}.')

    # A separate SQLite lock serializes invocations and is released when a process exits.
    with closing(sqlite3.connect(directory / 'invocation.lock', timeout=0)) as lock:
        lock.execute('BEGIN EXCLUSIVE')
        with SqliteSaver.from_conn_string(str(database)) as checkpointer:
            aci = RepositoryACI(directory / 'repo')
            graph = build_agent(aci, create_model(aci, PROJECT / '.env'), checkpointer)
            config = {'configurable': {'thread_id': args.run_id}}
            snapshot = graph.get_state(config)
            if args.command == 'start' or args.command == 'resume':
                data = initial if initial is not None else resume_input(args, snapshot)
                max_steps = initial['max_steps'] if initial is not None else snapshot.values['max_steps']
                config['recursion_limit'] = max_steps * 4 + 10
                try:
                    graph.invoke(data, config, durability='sync')
                finally:
                    snapshot = graph.get_state(config)
                    if snapshot.values:
                        write_trace(snapshot, PROJECT / 'results' / 'logs' / f'{args.run_id}.jsonl')
            if not snapshot.values:
                raise ValueError(f'No saved graph state for {args.run_id}.')
            if args.command == 'status':
                write_trace(snapshot, PROJECT / 'results' / 'logs' / f'{args.run_id}.jsonl')
            show_status(snapshot, directory)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run_command(args)
    except OpenAIError as error:
        status = getattr(error, 'status_code', None)
        print(f'Model request failed ({type(error).__name__}, HTTP status: {status}). Check the model configuration and resume.',
              file=sys.stderr)
        return 1
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
