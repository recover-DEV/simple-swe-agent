import json
import subprocess
import sys
from pathlib import Path

import httpx2
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from experiment.aci import RepositoryACI
from experiment import model as model_adapter

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / 'examples' / 'pagination'
OLD = 'start = page * page_size'
NEW = 'start = (page - 1) * page_size'

DRIVER = '''
import runpy
import sys
from pathlib import Path

import run_agent

fixture = runpy.run_path(sys.argv[1])
run_agent.PROJECT = Path(sys.argv[2])
run_agent.create_model = lambda aci, env_file: fixture[sys.argv[3]]
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


def cli(workspace, *args, model='scripted_model'):
    return subprocess.run([sys.executable, '-c', DRIVER, __file__, str(workspace), model, *args],
                          cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                          timeout=30, check=False)


def trace(workspace, name):
    path = workspace / 'results' / 'logs' / f'{name}.jsonl'
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


@pytest.mark.parametrize('decision', ['--approve', '--reject'])
def test_approval_survives_process_exit(tmp_path, decision):
    started = cli(tmp_path, 'start', 'pagination', '--repo', str(EXAMPLE / 'repo'),
                  '--issue-file', str(EXAMPLE / 'issue.md'))
    assert started.returncode == 0, started.stderr
    assert 'Approval required' in started.stdout
    assert NEW in started.stdout
    working_file = tmp_path / 'runs' / 'pagination' / 'repo' / 'pagination.py'
    assert OLD in working_file.read_text(encoding='utf-8')

    resumed = cli(tmp_path, 'resume', 'pagination', decision, '--comment', 'reviewed')
    assert resumed.returncode == 0, resumed.stderr
    assert 'Stopped: model_finished' in resumed.stdout
    rows = trace(tmp_path, 'pagination')
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
    assert OLD in (EXAMPLE / 'repo' / 'pagination.py').read_text(encoding='utf-8')


def test_resume_after_provider_failure_preserves_completed_steps(tmp_path):
    stopped = cli(tmp_path, 'start', 'recover', '--repo', str(EXAMPLE / 'repo'),
                  '--issue', 'Fix pagination.', model='failing_model')
    assert stopped.returncode == 1
    assert 'Simulated provider interruption' in stopped.stderr
    assert trace(tmp_path, 'recover')[-1]['steps'] == 1

    resumed = cli(tmp_path, 'resume', 'recover')
    assert resumed.returncode == 0, resumed.stderr
    assert 'Approval required' in resumed.stdout
    results = [row['tool'] for row in trace(tmp_path, 'recover') if row['event'] == 'tool_result']
    assert results == ['run_tests', 'search_repo', 'read_file']


def test_step_limit_ends_before_another_model_call(tmp_path):
    result = cli(tmp_path, 'start', 'limited', '--repo', str(EXAMPLE / 'repo'),
                 '--issue', 'Fix pagination.', '--max-steps', '1', model='failing_model')
    assert result.returncode == 0, result.stderr
    assert 'Stopped: step_limit' in result.stdout
    assert trace(tmp_path, 'limited')[-1]['steps'] == 1


def test_aci_checks_edit_scope_and_replays_approved_write_safely(tmp_path):
    source = tmp_path / 'worker.py'
    source.write_text('old = 1\n', encoding='utf-8')
    tests = tmp_path / 'test_worker.py'
    tests.write_text('old = 1\n', encoding='utf-8')
    aci = RepositoryACI(tmp_path)
    with pytest.raises(ValueError, match='relative'):
        aci.read_file('../outside.py')
    with pytest.raises(ValueError, match='read-only'):
        aci.prepare_edit('test_worker.py', 'old', 'new')

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
