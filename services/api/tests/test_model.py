import asyncio
import json

import httpx
import pytest

from lh_agent.app import Settings
from lh_agent.model import ModelClient, ModelError


def adapter(monkeypatch, chunks):
    wire = ''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks).encode()
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=wire, headers={'Content-Type':'text/event-stream'}))
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=transport, **kwargs))
    return ModelClient(Settings(model_api_key='synthetic-only'))


def test_provider_nullable_tool_fields_and_terminal_delta(monkeypatch):
    client = adapter(monkeypatch, [
        {'choices':[{'delta':{'role':'assistant','content':None,'tool_calls':None}}]},
        {'choices':[{'delta':{'content':'실제 형태의 합성 응답','tool_calls':None}}]},
        {'choices':[{'delta':None,'finish_reason':'stop'}]},
        {'choices':None},
    ])
    async def collect():
        return [part async for part in client.stream([{'role':'user','content':'synthetic'}], True)]
    assert asyncio.run(collect()) == [{'text':'실제 형태의 합성 응답'}]


def test_interrupted_stream_never_looks_complete(monkeypatch):
    client = adapter(monkeypatch, [{'choices':[{'delta':{'content':'partial'}}]}])
    async def collect():
        return [part async for part in client.stream([], False)]
    with pytest.raises(ModelError, match='MODEL_STREAM_INTERRUPTED'):
        asyncio.run(collect())
