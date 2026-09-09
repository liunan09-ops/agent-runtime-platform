import json
import os

import httpx
import pytest

from agent_runtime.api import create_app
from agent_runtime.models import ContextState, RunRequest, RunState, Status, TraceEvent
from agent_runtime.persistence import Store
from agent_runtime.providers import CompatibleProvider, ProviderError, parse_action
from agent_runtime.safety import redact


async def test_persistence_restart_and_interrupted_recovery(tmp_path):
    url = f'sqlite+aiosqlite:///{tmp_path}/restart.db'
    store = Store(url)
    await store.initialize()
    state = RunState(session_id='demo', execution_mode='direct', user_request='synthetic')
    state.transition(Status.RUNNING)
    events = [TraceEvent(seq=0, kind='request', data={})]
    await store.save(state, events)
    await store.save(state, events)
    await store.close()
    reopened = Store(url)
    await reopened.initialize(recover_interrupted=True)
    trace = await reopened.get(state.request_id)
    assert trace.state.status == 'FAILED' and trace.state.errors[-1].code == 'INTERRUPTED'
    assert len([e for e in trace.events if e.kind == 'request']) == 1
    await reopened.close()


async def test_replay_never_invokes_tools_or_llm(runtime):
    state = await runtime.run(RunRequest(mode='direct', tool={'name': 'calculator', 'args': {'expression': '5*9'}}))
    runtime.registry.unregister('calculator')
    trace = await runtime.replay(state.request_id)
    assert trace.state.final_result == state.final_result
    assert trace.state.replay_of == state.request_id and trace.state.request_id != state.request_id
    assert trace.state.tool_call_count == trace.state.llm_call_count == 0
    assert (await runtime.store.get(trace.state.request_id)).state == trace.state
    with pytest.raises(KeyError):
        await runtime.replay('absent')
    pending = RunState(session_id='demo', execution_mode='direct', user_request='pending')
    await runtime.store.save(pending, [])
    with pytest.raises(ValueError, match='terminal'):
        await runtime.replay(pending.request_id)


async def test_api_end_to_end_and_validation(tmp_path):
    app = create_app(f'sqlite+aiosqlite:///{tmp_path}/api.db')
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/health')).json()['status'] == 'ok'
        assert len((await client.get('/tools')).json()) == 5
        assert (await client.post('/runs', json={'mode': 'direct'})).status_code == 422
        assert (await client.get('/runs/absent')).status_code == 404
        assert (await client.post('/replay/absent')).status_code == 404
        assert (await client.delete('/runs/absent')).status_code == 409
        response = await client.post('/runs', json={'mode': 'react', 'mock_script': [
            {'type': 'tool', 'name': 'calculator', 'args': {'expression': '8*8'}},
            {'type': 'final', 'result': {'$last_observation': True}}]})
        assert response.status_code == 200
        state = response.json()
        assert state['final_result'] == {'value': 64}
        assert (await client.get('/runs/' + state['request_id'])).json() == state
        assert (await client.get('/traces/' + state['request_id'])).json()['events'][-1]['kind'] == 'final'
        replay = (await client.post('/replay/' + state['request_id'])).json()
        assert replay['state']['final_result'] == state['final_result']
        assert '/runs' in (await client.get('/openapi.json')).json()['paths']


async def test_compatible_provider_wire_contract_and_usage():
    def handler(request):
        body = json.loads(request.content)
        assert str(request.url) == 'https://provider.invalid/v1/chat/completions'
        assert body['response_format'] == {'type': 'json_object'}
        assert 'reasoning' not in body
        return httpx.Response(200, json={'model': 'fixture', 'choices': [{'message': {
            'content': '{"type":"final","result":42}', 'reasoning_content': 'never stored'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7}})
    provider = CompatibleProvider(api_key='synthetic-placeholder', base_url='https://provider.invalid/v1', transport=httpx.MockTransport(handler))
    completion = await provider.complete(ContextState(), [], [])
    assert parse_action(completion.content).result == 42 and completion.usage['total_tokens'] == 7
    assert 'never stored' not in str(completion)


@pytest.mark.parametrize('response', [httpx.Response(503, text='sensitive upstream detail'), httpx.Response(200, json={}), httpx.Response(200, text='bad json')])
async def test_provider_failure_does_not_leak_response(response):
    provider = CompatibleProvider(api_key='synthetic-placeholder', transport=httpx.MockTransport(lambda _: response))
    with pytest.raises(ProviderError) as exc:
        await provider.complete(ContextState(), [], [])
    assert 'sensitive upstream detail' not in str(exc.value)


async def test_redaction_in_state_and_trace(runtime, monkeypatch):
    secret = 'synthetic-runtime-credential-value'
    monkeypatch.setenv('DEEPSEEK_API_KEY', secret)
    state = await runtime.run(RunRequest(mode='direct', user_request=secret, tool={'name': 'missing', 'args': {'password': secret}}))
    trace = await runtime.store.get(state.request_id)
    assert secret not in state.model_dump_json() and secret not in trace.model_dump_json()
    assert redact({'reasoning_content': 'hidden'})['reasoning_content'] == '[REDACTED]'


@pytest.mark.live
@pytest.mark.skipif(os.getenv('RUN_LIVE_TESTS') != '1' or not os.getenv('DEEPSEEK_API_KEY'), reason='live opt-in and key required')
async def test_live_deepseek(runtime):
    state = await runtime.run(RunRequest(mode='react', provider='deepseek', user_request='Use calculator to compute 17*19. Return its entire output object.', timeout_s=90, llm_timeout_s=40))
    assert state.status == 'SUCCESS' and state.final_result == {'value': 323}
    assert state.token_usage and state.token_usage['total_tokens'] > 0
    assert state.tool_history[0].call.name == 'calculator'
