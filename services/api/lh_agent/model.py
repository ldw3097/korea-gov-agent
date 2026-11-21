"""Bounded OpenAI-compatible streaming adapter; no hidden reasoning is exposed."""
import json

import httpx


TOOLS = [
    {'type': 'function', 'function': {
        'name': 'create_document',
        'description': '검토·다운로드할 실제 Markdown 문서를 생성한다. 같은 파일명은 새 버전으로 저장된다.',
        'parameters': {'type': 'object', 'properties': {
            'filename': {'type': 'string', 'description': '경로 없는 .md 파일명'},
            'title': {'type': 'string'}, 'content': {'type': 'string', 'description': '완성된 Markdown 본문'}},
            'required': ['filename', 'title', 'content'], 'additionalProperties': False},
    }},
    {'type': 'function', 'function': {
        'name': 'ask_user', 'description': '업무에 꼭 필요한 정보가 없을 때 질문하고 사용자 답변을 기다린다.',
        'parameters': {'type': 'object', 'properties': {'question': {'type': 'string'}},
                       'required': ['question'], 'additionalProperties': False},
    }},
]


class ModelError(Exception):
    pass


class ModelClient:
    def __init__(self, settings):
        self.settings = settings
        self.ready = bool(settings.model_api_key and settings.model_name)

    async def stream(self, messages, work):
        body = {'model': self.settings.model_name, 'messages': messages, 'stream': True,
                'max_tokens': 6000, 'temperature': 0.4}
        if work:
            body.update(tools=TOOLS, tool_choice='auto')
        async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10), follow_redirects=False) as client:
            async with client.stream('POST', self.settings.model_base_url.rstrip('/') + '/chat/completions',
                                     headers={'Authorization': 'Bearer ' + self.settings.model_api_key}, json=body) as response:
                if response.status_code != 200:
                    raise ModelError('MODEL_AUTH' if response.status_code in (401, 403) else
                                     'MODEL_RATE_LIMIT' if response.status_code == 429 else 'MODEL_UNAVAILABLE')
                size, finished = 0, False
                async for line in response.aiter_lines():
                    size += len(line)
                    if size > 600000:
                        raise ModelError('MODEL_OUTPUT_LIMIT')
                    if not line.startswith('data:'):
                        continue
                    data = line[5:].strip()
                    if data == '[DONE]':
                        finished = True
                        break
                    try:
                        item = json.loads(data)
                    except ValueError:
                        raise ModelError('MODEL_STREAM_INVALID') from None
                    if item.get('error'):
                        raise ModelError('MODEL_UNAVAILABLE')
                    for choice in item.get('choices') or []:
                        delta = choice.get('delta') or {}
                        if isinstance(delta.get('content'), str) and delta['content']:
                            yield {'text': delta['content']}
                        for call in delta.get('tool_calls') or []:
                            yield {'call': call}
                        reason = choice.get('finish_reason')
                        if reason in ('length', 'content_filter'):
                            raise ModelError('MODEL_OUTPUT_LIMIT' if reason == 'length' else 'MODEL_CONTENT_FILTER')
                        if reason in ('stop', 'tool_calls'):
                            finished = True
                if not finished:
                    raise ModelError('MODEL_STREAM_INTERRUPTED')
