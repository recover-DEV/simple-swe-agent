import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import httpx2
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from experiment.aci import RepositoryACI
from experiment import model as model_adapter
from run_agent import choose_mode

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / 'examples' / 'pagination'
OLD = 'start = page * page_size'
NEW = 'start = (page - 1) * page_size'
WRONG = 'start = (page + 1) * page_size'

DRIVER = '''
import runpy
import sys
from pathlib import Path

import run_agent

fixture = runpy.run_path(sys.argv[1])
run_agent.PROJECT = Path(sys.argv[2])
run_agent.create_model = lambda aci, env_file, **options: fixture[sys.argv[3]]
raise SystemExit(run_agent.main(sys.argv[4:]))
'''


def request_tool(name, step, **args):
    return AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': f'call-{step}'}])


def scripted_model(messages):
    results = [message for message in messages if isinstance(message, ToolMessage)]
    if not results:
        return request_tool('run_tests', 0)
    last = results[-1]
    observed = json.loads(last.content)
    step = len(results)
    if last.name == 'run_tests':
        if observed['ok']:
            return AIMessage(content='Pagination tests passed.')
        return request_tool('search_repo', step, query='def paginate')
    if last.name == 'search_repo':
        return request_tool('read_file', step, path=observed['matches'][0]['path'])
    if last.name == 'read_file':
        assert OLD in observed['text']
        return request_tool('replace_text', step, path=observed['path'], old=OLD, new=NEW)
    if observed['ok']:
        return request_tool('run_tests', step)
    return AIMessage(content=f"Edit not applied: {observed['error']}")


def failing_model(messages):
    if any(isinstance(message, ToolMessage) for message in messages):
        raise ValueError('Simulated provider interruption')
    return scripted_model(messages)


def workflow_patch_model(messages):
    context = json.loads(messages[-1].content)
    source = context['numbered_source']
    assert context['pytest']['exit_code'] == 1
    assert 'test_first_page' in context['pytest']['output']
    if WRONG in source:
        return request_tool('replace_text', 2, path=context['path'], old=WRONG, new=NEW)
    assert OLD in source
    proposed = WRONG if context['issue'] == 'Try a second patch' else NEW
    return request_tool('replace_text', 1, path=context['path'], old=OLD, new=proposed)


def workflow_multi_source_model(messages):
    context = json.loads(messages[-1].content)
    output = context['pytest']['output']
    failed = next(line for line in output.splitlines() if line.startswith('FAILED test.py::'))
    test = failed.split('::', 1)[1].split()[0]
    path = {'test_first': 'z_worker.py', 'test_second': 'a_worker.py', 'test_third': 'mid_worker.py'}[test]
    assert context['path'] == path
    assert context['test_path'] == 'test.py'
    assert 'from z_worker import compute as first' in context['numbered_test']
    return request_tool('replace_text', 1, path=path, old='return 0', new='return 1')


def workflow_batch_model(messages):
    path = json.loads(messages[-1].content)['path']
    assert path == 'price.py'
    first = request_tool('replace_text', 1, path=path, old='rate = 0', new='rate = 1')
    second = request_tool('replace_text', 2, path=path,
                          old='rate = 1\nfee = 0', new='rate = 1\nfee = 2')
    return AIMessage(content='', tool_calls=[*first.tool_calls, *second.tool_calls])


def workflow_review_model(messages):
    context = json.loads(messages[-1].content)
    path = context['path']
    feedback = context.get('review_feedback')
    if feedback:
        assert feedback['comment'] == 'Use 1 + 1 for the fee.'
        assert '+fee = 2' in feedback['rejected_diff']
        assert context['numbered_source'] == '1: rate = 1\n2: fee = 0'
        if 'repeated_diff' not in feedback:
            return request_tool('replace_text', 4, path=path, old='fee = 0', new='fee = 2')
        assert feedback['repeated_diff'] == feedback['rejected_diff']
        return request_tool('replace_text', 5, path=path, old='fee = 0', new='fee = 1 + 1')
    batch = workflow_batch_model(messages)
    third = request_tool('replace_text', 3, path=path, old='fee = 2', new='fee = 3')
    return AIMessage(content='', tool_calls=[*batch.tool_calls, *third.tool_calls])


def cli(workspace, *args, model='scripted_model'):
    return subprocess.run([sys.executable, '-c', DRIVER, __file__, str(workspace), model, *args],
                          cwd=ROOT, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                          capture_output=True, text=True, encoding='utf-8',
                          timeout=30, check=False)


def trace(workspace, name, strategy='agent'):
    logs = workspace / 'results' / 'logs'
    path = (logs / strategy if strategy else logs) / f'{name}.jsonl'
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


@pytest.mark.parametrize('reply, mode', [('', 'copy'), ('2', 'in-place')])
def test_choose_mode_prompts_in_terminal(monkeypatch, reply, mode):
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(sys.stdout, 'isatty', lambda: True)
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return reply

    monkeypatch.setattr('builtins.input', answer)
    assert choose_mode(None) == mode
    assert 'edit original repository' in prompts[0]


@pytest.mark.parametrize('mode', ['copy', 'in-place'])
@pytest.mark.parametrize('decision', ['--approve', '--reject'])
def test_approval_survives_process_exit(tmp_path, decision, mode):
    original = tmp_path / 'original'
    shutil.copytree(EXAMPLE, original)
    started = cli(tmp_path, 'start', 'pagination', f'--{mode}', '--repo', str(original),
                  '--issue-file', str(EXAMPLE / 'issue.md'))
    assert started.returncode == 0, started.stderr
    assert 'Approval required' in started.stdout
    issue_title = (EXAMPLE / 'issue.md').read_text(encoding='utf-8').splitlines()[0]
    assert f'Issue: {issue_title}' in started.stdout
    assert NEW in started.stdout
    runs = tmp_path / 'runs'
    run_directory = runs / '_strategies' / 'agent' / 'pagination'
    working_file = (run_directory / 'repo' if mode == 'copy' else original) / 'pagination.py'
    assert f'Repository: {working_file.parent} ({mode})' in started.stdout
    assert OLD in working_file.read_text(encoding='utf-8')
    if mode == 'in-place':
        assert not (run_directory / 'repo').exists()
    legacy = mode == 'copy' and decision == '--reject'
    if legacy:
        run_directory = run_directory.rename(runs / 'pagination')
        working_file = run_directory / 'repo' / 'pagination.py'
        (run_directory / 'target.json').unlink()
        logs = tmp_path / 'results' / 'logs'
        (logs / 'agent' / 'pagination.jsonl').rename(logs / 'pagination.jsonl')

    resumed = cli(tmp_path, 'resume', 'pagination', decision, '--comment', 'reviewed')
    assert resumed.returncode == 0, resumed.stderr
    assert 'Stopped: model_finished' in resumed.stdout
    rows = trace(tmp_path, 'pagination', None if legacy else 'agent')
    results = [row for row in rows if row['event'] == 'tool_result']
    assert results[0]['result']['exit_code'] == 1
    if decision == '--approve':
        assert NEW in working_file.read_text(encoding='utf-8')
        assert results[-1]['result']['exit_code'] == 0
        assert rows[-1]['steps'] == 5
    else:
        assert OLD in working_file.read_text(encoding='utf-8')
        assert results[-1]['result']['comment'] == 'reviewed'
        assert rows[-1]['steps'] == 4
    expected_original = NEW if mode == 'in-place' and decision == '--approve' else OLD
    assert expected_original in (original / 'pagination.py').read_text(encoding='utf-8')
    conversation = (run_directory / 'conversation.md').read_text(encoding='utf-8')
    assert f'实际工作目录：`{working_file.parent}`' in conversation
    if decision == '--approve':
        assert f'+    {NEW}' in conversation


def test_resume_after_provider_failure_preserves_completed_steps(tmp_path):
    stopped = cli(tmp_path, 'start', 'recover', '--repo', str(EXAMPLE),
                  '--issue', 'Fix pagination.', model='failing_model')
    assert stopped.returncode == 1
    assert 'Simulated provider interruption' in stopped.stderr
    assert trace(tmp_path, 'recover')[-1]['steps'] == 1

    resumed = cli(tmp_path, 'resume', 'recover')
    assert resumed.returncode == 0, resumed.stderr
    assert 'Approval required' in resumed.stdout
    results = [row['tool'] for row in trace(tmp_path, 'recover') if row['event'] == 'tool_result']
    assert results == ['run_tests', 'search_repo', 'read_file']


def test_generated_ids_keep_tasks_separate_and_allow_resume(tmp_path):
    first = cli(tmp_path, 'start', '--repo', str(EXAMPLE), '--issue', 'First task',
                model='failing_model')
    assert first.returncode == 1, first.stderr
    first_id = first.stdout.splitlines()[0].removeprefix('Run ID: ')
    assert first_id.startswith('pagination-')
    assert UUID(first_id.rsplit('-', 1)[-1]).version == 4

    second = cli(tmp_path, 'start', '--repo', str(EXAMPLE), '--issue', 'Second task', '--strategy', 'workflow',
                 model='workflow_patch_model')
    assert second.returncode == 0, second.stderr
    second_id = second.stdout.splitlines()[0].removeprefix('Run ID: ')
    assert second_id.startswith('pagination-')
    assert UUID(second_id.rsplit('-', 1)[-1]).version == 4
    assert first_id != second_id

    duplicate = cli(tmp_path, 'start', second_id, '--repo', str(EXAMPLE), '--issue', 'Duplicate task')
    assert duplicate.returncode == 1
    assert 'Run ID already exists' in duplicate.stderr

    resumed = cli(tmp_path, 'resume', first_id)
    assert resumed.returncode == 0, resumed.stderr
    assert 'Issue: First task' in resumed.stdout
    assert 'Approval required' in resumed.stdout
    assert trace(tmp_path, first_id)[0]['message'] == 'First task'
    assert trace(tmp_path, second_id, 'workflow')[0]['message'] == 'Second task'
    index = (tmp_path / 'runs' / 'INDEX.md').read_text(encoding='utf-8')
    for title, run_id, strategy in [('First task', first_id, 'agent'), ('Second task', second_id, 'workflow')]:
        row = next(line for line in index.splitlines() if line.startswith(f'| {title} |'))
        location = f'_strategies/{strategy}/{run_id}'
        assert f'[{run_id}]({location}/conversation.md)' in row
        assert f'runs/{location}/repo' in row


def test_history_backfills_existing_run_without_inventing_original_repository(tmp_path):
    existing = tmp_path / 'runs' / 'old-id'
    (existing / 'repo').mkdir(parents=True)
    logs = tmp_path / 'results' / 'logs'
    logs.mkdir(parents=True)
    log = logs / 'old-id.jsonl'
    log.write_text('{"event":"issue","message":"Old task"}\n', encoding='utf-8')

    result = cli(tmp_path, 'history')
    assert result.returncode == 0, result.stderr
    index = (tmp_path / 'runs' / 'INDEX.md').read_text(encoding='utf-8')
    assert '| Old task | 未记录 | [runs/old-id/repo](old-id/repo/) | 副本 |' in index
    assert (existing / 'conversation.md').is_file()
    assert log.read_text(encoding='utf-8') == '{"event":"issue","message":"Old task"}\n'


def test_step_limit_ends_before_another_model_call(tmp_path):
    result = cli(tmp_path, 'start', 'limited', '--repo', str(EXAMPLE),
                 '--issue', 'Fix pagination.', '--max-steps', '1', model='failing_model')
    assert result.returncode == 0, result.stderr
    assert 'Stopped: step_limit' in result.stdout
    assert trace(tmp_path, 'limited')[-1]['steps'] == 1


@pytest.mark.parametrize('retry', [False, True])
def test_workflow_executes_fixed_order_and_retries_on_failure(tmp_path, retry):
    issue = 'Try a second patch' if retry else 'Fix pagination'
    started = cli(tmp_path, 'start', 'fixed', '--strategy', 'workflow', '--copy', '--repo', str(EXAMPLE),
                  '--issue', issue, model='workflow_patch_model')
    assert started.returncode == 0, started.stderr
    assert 'Approval required' in started.stdout
    assert 'Strategy: workflow' in started.stdout
    work_file = tmp_path / 'runs' / '_strategies' / 'workflow' / 'fixed' / 'repo' / 'pagination.py'
    assert OLD in work_file.read_text(encoding='utf-8')

    result = cli(tmp_path, 'resume', 'fixed', '--approve', model='workflow_patch_model')
    assert result.returncode == 0, result.stderr
    if retry:
        assert 'Approval required' in result.stdout
        assert WRONG in work_file.read_text(encoding='utf-8')
        result = cli(tmp_path, 'resume', 'fixed', '--approve', model='workflow_patch_model')
        assert result.returncode == 0, result.stderr

    assert 'Stopped: tests_passed' in result.stdout
    assert NEW in work_file.read_text(encoding='utf-8')
    rows = trace(tmp_path, 'fixed', 'workflow')
    actions = [row for row in rows if row['event'] == 'tool_result']
    expected = ['run_tests', 'read_file', 'search_repo', 'read_file', 'replace_text', 'run_tests']
    if retry:
        expected += ['read_file', 'search_repo', 'read_file', 'replace_text', 'run_tests']
    assert [row['tool'] for row in actions] == expected
    assert [row['result']['exit_code'] for row in actions if row['tool'] == 'run_tests'] == ([1, 1, 0] if retry else [1, 0])
    assert rows[-1]['steps'] == len(expected)
    assert rows[-1]['strategy'] == 'workflow'


@pytest.mark.parametrize(('max_steps', 'stop_reason', 'exit_code'), [(11, 'step_limit', 1), (16, 'tests_passed', 0)])
def test_workflow_uses_test_py_to_find_each_failing_source(tmp_path, max_steps, stop_reason, exit_code):
    repository = tmp_path / 'input'
    repository.mkdir()
    for name in ('a_worker.py', 'mid_worker.py', 'z_worker.py'):
        (repository / name).write_text('def compute():\n    return 0\n', encoding='utf-8')
    (repository / 'pytest.ini').write_text('[pytest]\npython_files = check_*.py\n', encoding='utf-8')
    (repository / 'check_existing.py').write_text('def test_existing():\n    assert True\n', encoding='utf-8')
    (repository / 'test.py').write_text(
        'from z_worker import compute as first\n'
        'from a_worker import compute as second\n'
        'from mid_worker import compute as third\n\n'
        'def test_first():\n    assert first() == 1\n\n'
        'def test_second():\n    assert second() == 1\n\n'
        'def test_third():\n    assert third() == 1\n',
        encoding='utf-8',
    )
    expected_paths = ['z_worker.py', 'a_worker.py']
    if stop_reason == 'tests_passed':
        expected_paths.append('mid_worker.py')
    model = 'workflow_multi_source_model'
    result = cli(tmp_path, 'start', 'multi-source', '--strategy', 'workflow', '--copy', '--repo', str(repository),
                 '--issue', 'Fix the failed tests', '--max-steps', str(max_steps), model=model)
    assert result.returncode == 0, result.stderr
    for path in expected_paths:
        assert 'Approval required' in result.stdout and f'+++ {path}' in result.stdout
        result = cli(tmp_path, 'resume', 'multi-source', '--approve', model=model)
        assert result.returncode == 0, result.stderr
    assert f'Stopped: {stop_reason}' in result.stdout
    rows = trace(tmp_path, 'multi-source', 'workflow')
    actions = [row for row in rows if row['event'] == 'tool_result']
    assert [row['result']['path'] for row in actions if row['tool'] == 'read_file'] == [
        path for source in expected_paths for path in ('test.py', source)
    ]
    assert rows[-1]['steps'] == max_steps
    assert rows[-1]['last_test_exit_code'] == exit_code
    assert actions[-1]['tool'] == 'run_tests'


@pytest.fixture
def price_repository(tmp_path):
    repository = tmp_path / 'input'
    repository.mkdir()
    (repository / 'price.py').write_text('rate = 0\nfee = 0\n', encoding='utf-8')
    (repository / 'test_price.py').write_text(
        'from price import rate, fee\n\ndef test_price():\n    assert (rate, fee) == (1, 2)\n',
        encoding='utf-8',
    )
    return repository


@pytest.mark.parametrize(('max_steps', 'second_decision', 'stop_reason', 'expected_fee'), [
    (12, '--approve', 'tests_passed', 2),
    (12, '--reject', 'edit_rejected', 0),
    (5, None, 'step_limit', 0),
])
def test_workflow_applies_one_model_batch_in_order(
        tmp_path, price_repository, max_steps, second_decision, stop_reason, expected_fee):
    model = 'workflow_batch_model'
    started = cli(tmp_path, 'start', 'batch', '--strategy', 'workflow', '--copy', '--repo', str(price_repository),
                  '--issue', 'Fix rate and fee', '--max-steps', str(max_steps), model=model)
    assert started.returncode == 0, started.stderr
    assert 'Approval required' in started.stdout and '+rate = 1' in started.stdout
    work_file = tmp_path / 'runs' / '_strategies' / 'workflow' / 'batch' / 'repo' / 'price.py'
    assert work_file.read_text(encoding='utf-8') == 'rate = 0\nfee = 0\n'

    result = cli(tmp_path, 'resume', 'batch', '--approve', model=model)
    assert result.returncode == 0, result.stderr
    assert work_file.read_text(encoding='utf-8') == 'rate = 1\nfee = 0\n'
    if second_decision:
        assert 'Approval required' in result.stdout and '+fee = 2' in result.stdout
        result = cli(tmp_path, 'resume', 'batch', second_decision, model=model)
        assert result.returncode == 0, result.stderr
    assert f'Stopped: {stop_reason}' in result.stdout
    assert work_file.read_text(encoding='utf-8') == f'rate = 1\nfee = {expected_fee}\n'

    rows = trace(tmp_path, 'batch', 'workflow')
    assert sum(row['event'] == 'model' for row in rows) == 1
    actions = [row for row in rows if row['event'] == 'tool_result']
    expected = ['run_tests', 'read_file', 'search_repo', 'read_file', 'replace_text']
    if second_decision:
        expected.append('replace_text')
    if stop_reason == 'tests_passed':
        expected.append('run_tests')
    assert [row['tool'] for row in actions] == expected
    assert rows[-1]['steps'] == len(expected)
    assert rows[-1]['last_test_exit_code'] == (0 if stop_reason == 'tests_passed' else None)


def test_workflow_reproposes_after_commented_rejection(tmp_path, price_repository):
    model = 'workflow_review_model'
    started = cli(tmp_path, 'start', 'review', '--strategy', 'workflow', '--copy', '--repo', str(price_repository),
                  '--issue', 'Fix rate and fee', model=model)
    assert started.returncode == 0 and 'Approval required' in started.stdout, started.stderr
    first_approval = cli(tmp_path, 'resume', 'review', '--approve', model=model)
    assert first_approval.returncode == 0, first_approval.stderr
    assert 'Approval required' in first_approval.stdout and '+fee = 2' in first_approval.stdout

    comment = 'Use 1 + 1 for the fee.'
    revised = cli(tmp_path, 'resume', 'review', '--reject', '--comment', comment, model=model)
    assert revised.returncode == 0, revised.stderr
    assert 'Approval required' in revised.stdout and '+fee = 1 + 1' in revised.stdout
    work_file = tmp_path / 'runs' / '_strategies' / 'workflow' / 'review' / 'repo' / 'price.py'
    assert work_file.read_text(encoding='utf-8') == 'rate = 1\nfee = 0\n'

    finished = cli(tmp_path, 'resume', 'review', '--approve', model=model)
    assert finished.returncode == 0, finished.stderr
    assert 'Stopped: tests_passed' in finished.stdout
    assert work_file.read_text(encoding='utf-8') == 'rate = 1\nfee = 1 + 1\n'
    rows = trace(tmp_path, 'review', 'workflow')
    actions = [row for row in rows if row['event'] == 'tool_result']
    repairs = [row for row in actions if row['tool'] == 'replace_text']
    assert [row['call_id'] for row in repairs] == ['call-1', 'call-2', 'call-4', 'call-5']
    assert not repairs[2]['result']['ok'] and 'repeats a diff' in repairs[2]['result']['error']
    assert actions[5]['result']['comment'] == comment
    assert [row['result']['exit_code'] for row in actions if row['tool'] == 'run_tests'] == [1, 0]
    assert rows[-1]['steps'] == 11


def test_workflow_obeys_tool_budget(tmp_path):
    result = cli(tmp_path, 'start', 'limited', '--strategy', 'workflow', '--repo', str(EXAMPLE),
                 '--issue', 'Fix pagination', '--max-steps', '2', model='workflow_patch_model')
    assert result.returncode == 0, result.stderr
    assert 'Stopped: step_limit' in result.stdout
    assert trace(tmp_path, 'limited', 'workflow')[-1]['steps'] == 2


def test_aci_checks_edit_scope_and_replays_approved_write_safely(tmp_path):
    source = tmp_path / 'worker.py'
    source.write_text('old = 1\n', encoding='utf-8')
    for name in ('test_worker.py', 'test.py'):
        (tmp_path / name).write_text('old = 1\n', encoding='utf-8')
    aci = RepositoryACI(tmp_path)
    with pytest.raises(ValueError, match='relative'):
        aci.read_file('../outside.py')
    with pytest.raises(ValueError, match='read-only'):
        aci.prepare_edit('test_worker.py', 'old', 'new')
    with pytest.raises(ValueError, match='read-only'):
        aci.prepare_edit('test.py', 'old', 'new')

    stale = aci.prepare_edit('worker.py', 'old', 'new')
    source.write_text('old = 2\n', encoding='utf-8')
    with pytest.raises(ValueError, match='changed'):
        aci.apply_edit(stale)
    current = aci.prepare_edit('worker.py', 'old', 'new')
    assert aci.apply_edit(current)['ok']
    assert aci.apply_edit(current)['already_applied']
    assert 'new = 2' in source.read_text(encoding='utf-8')


def test_model_adapter_sends_tool_schemas_and_decodes_tool_calls(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODEL', 'tool-test-model')
    monkeypatch.setenv('LLM_BASE_URL', 'https://api.deepseek.com')
    monkeypatch.setenv('LLM_API_KEY', 'test-key')
    create_client = model_adapter.ChatOpenAI

    def fake_provider(request):
        payload = json.loads(request.content)
        assert payload['thinking'] == {'type': 'disabled'}
        assert {tool['function']['name'] for tool in payload['tools']} == {
            'search_repo', 'read_file', 'replace_text', 'run_tests'
        }
        message = {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'call-test', 'type': 'function', 'function': {'name': 'run_tests', 'arguments': '{}'}}
        ]}
        return httpx2.Response(200, json={
            'id': 'response-test', 'object': 'chat.completion', 'created': 0, 'model': 'tool-test-model',
            'choices': [{'index': 0, 'message': message, 'finish_reason': 'tool_calls'}],
        })

    with httpx2.Client(transport=httpx2.MockTransport(fake_provider)) as client:
        def create_local_model(**options):
            return create_client(http_client=client, **options)

        monkeypatch.setattr(model_adapter, 'ChatOpenAI', create_local_model)
        invoke = model_adapter.create_model(RepositoryACI(tmp_path), tmp_path / '.env')
        result = invoke([HumanMessage(content='Run the tests.')])
    assert result.tool_calls[0]['name'] == 'run_tests'
