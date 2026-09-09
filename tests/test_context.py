from agent_runtime.context import compact, estimate_tokens, render_context, summarize
from agent_runtime.models import ContextPolicy, Message


def test_structured_retains_early_fact_and_compresses_big_tool_output():
    messages = [Message(content='owner=Atlas; limit=50', important=True, facts={'owner': 'Atlas', 'limit': '50'})]
    messages += [Message(content=f'irrelevant discussion {i}: ' + 'x ' * 100) for i in range(30)]
    messages += [Message(role='tool', content='tool payload ' * 500), Message(content='Return owner and limit')]
    baseline = compact(messages, ContextPolicy(strategy='naive', token_budget=400))
    structured = compact(messages, ContextPolicy(strategy='structured', token_budget=400))
    assert 'Atlas' not in render_context(baseline)
    assert structured.facts == {'owner': 'Atlas', 'limit': '50'}
    assert structured.estimated_tokens <= 400
    assert len(structured.messages) <= 8
    assert any('compressed' in m.content for m in structured.messages if m.role == 'tool') or structured.dropped_messages > 0
    assert len(summarize(list(range(1000)))) < 450


def test_hard_budget_unicode_fact_overflow_and_latest_update():
    messages = [Message(content='数' * 10000, facts={str(i): '很长的事实' * 100 for i in range(10)})]
    result = compact(messages, ContextPolicy(token_budget=128))
    assert estimate_tokens(render_context(result)) <= 128 and result.dropped_facts > 0
    updated = compact([Message(content='old', facts={'owner': 'A'}), Message(content='new', facts={'owner': 'B'})], ContextPolicy())
    assert updated.facts['owner'] == 'B'


def test_context_deterministic_and_recent_window():
    messages = [Message(content=str(i)) for i in range(20)]
    policy = ContextPolicy(strategy='naive', recent_window=3)
    assert [m.content for m in compact(messages, policy).messages] == ['17', '18', '19']
    assert compact(messages, policy) == compact(messages, policy)
