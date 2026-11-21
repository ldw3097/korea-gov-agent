import asyncio
import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from lh_agent.app import Settings, create_app
from lh_agent.db import Artifact, AssistantMessage, Message, Run, Thread
from lh_agent.model import ModelError
from lh_agent.seed import seed

ORIGIN = 'http://127.0.0.1:8000'
PASSWORD = 'synthetic-test-password'


def tool(name, args):
    return {'call': {'index': 0, 'id': 'test-call-' + str(uuid4()), 'function': {'name': name, 'arguments': json.dumps(args)}}}


class Provider:
    ready = True

    def __init__(self):
        self.responses = [[{'text': '합성 응답입니다.'}]]
        self.requests = []
        self.delay = 0.01

    async def stream(self, messages, work):
        index = len(self.requests)
        self.requests.append((list(messages), work))
        response = self.responses[min(index, len(self.responses) - 1)]
        for part in response:
            await asyncio.sleep(self.delay)
            if isinstance(part, Exception):
                raise part
            yield part


@pytest.fixture
def work(tmp_path):
    app = create_app(Settings(database_url=f'sqlite:///{tmp_path}/work.db', environment='test'))
    provider = Provider()
    app.state.work.provider = provider
    with TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN}) as owner:
        with app.state.sessions() as db:
            seed(db, PASSWORD)
        assert owner.post('/api/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code == 200
        other = TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN})
        assert other.post('/api/auth/login', json={'username': 'bob', 'password': PASSWORD}).status_code == 200
        yield app, owner, other, provider
        other.close()


def thread(client, project=None):
    response = client.post('/api/threads', json={'title': '합성 작업', 'project_id': project})
    assert response.status_code == 201
    return response.json()['id']


def submit(client, tid, **kwargs):
    body = {'request_id': str(uuid4()), 'content': '합성 보고서를 작성해 줘.', **kwargs}
    response = client.post(f'/api/threads/{tid}/runs', json=body)
    assert response.status_code == 202, response.text
    return response.json(), body


def wait(client, tid, status='completed', rid=None):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        response = client.get(f'/api/threads/{tid}/workspace')
        data = response.json()
        run = next((r for r in data['runs'] if r['id'] == rid), data['runs'][0])
        if run['status'] == status:
            return data, run
        time.sleep(0.03)
    raise AssertionError(f'Expected {status}, got {run}')


def test_real_job_lifecycle_and_reconnect_without_resubmission(work):
    app, owner, other, provider = work
    tid = thread(owner)
    run, body = submit(owner, tid, mode='chat')
    data, result = wait(owner, tid)
    assert result['status'] == 'completed'
    assert [m['role'] for m in data['messages']] == ['user', 'assistant']
    assert data['messages'][-1]['content'] == '합성 응답입니다.'
    assert len(provider.requests) == 1 and provider.requests[0][1] is False
    again = owner.post(f'/api/threads/{tid}/runs', json=body)
    assert again.status_code == 202
    assert len(owner.get(f'/api/threads/{tid}/workspace').json()['messages']) == 2
    assert len(provider.requests) == 1
    assert other.get(f'/api/threads/{tid}/workspace').status_code == 404
    assert other.post(f"/api/runs/{run['id']}/cancel").status_code == 404
    conflict = owner.post(f'/api/threads/{tid}/runs', json={**body, 'content': 'different'})
    assert conflict.status_code == 409


def test_document_generation_version_download_and_owner_only(work):
    app, owner, other, provider = work
    provider.responses = [
        [tool('create_document', {'filename': 'report.md', 'title': '검토보고서', 'content': '# 첫 문서\n합성 자료'})],
        [{'text': '문서를 만들었습니다.'}],
        [tool('create_document', {'filename': 'report.md', 'title': '검토보고서 수정', 'content': '# 수정 문서\n추가 요청 반영'})],
        [{'text': '수정했습니다.'}],
    ]
    tid = thread(owner)
    run, _ = submit(owner, tid)
    data, _ = wait(owner, tid, rid=run['id'])
    first = data['artifacts'][0]
    assert first['version'] == 1
    assert owner.get('/api/artifacts/' + first['id']).json()['content'] == '# 첫 문서\n합성 자료'
    response = owner.get(f"/api/artifacts/{first['id']}/download")
    assert 'attachment;' in response.headers['content-disposition']
    assert response.content.decode() == '# 첫 문서\n합성 자료'
    assert other.get('/api/artifacts/' + first['id']).status_code == 404
    assert other.get(f"/api/artifacts/{first['id']}/download").status_code == 404
    run, _ = submit(owner, tid, content='이 문서를 수정해 줘.')
    data, _ = wait(owner, tid, rid=run['id'])
    assert sorted(a['version'] for a in data['artifacts']) == [1, 2]
    assert any('기존 문서' in m['content'] for m in provider.requests[2][0])
    assert owner.delete(f'/api/threads/{tid}').status_code == 204
    with app.state.sessions() as db:
        assert db.scalars(select(Artifact)).all() == []
        assert db.scalars(select(AssistantMessage)).all() == []
        assert db.scalars(select(Run)).all() == []


def test_question_answer_resume_and_no_automatic_approval(work):
    app, owner, other, provider = work
    provider.responses = [[tool('ask_user', {'question': '보고 대상과 기한을 알려주세요.'})], [{'text': '추가 정보를 반영했습니다.'}]]
    tid = thread(owner)
    run, _ = submit(owner, tid)
    data, waiting = wait(owner, tid, 'waiting_input')
    assert waiting['question'] == '보고 대상과 기한을 알려주세요.'
    assert data['messages'][-1]['role'] == 'assistant'
    body = {'request_id': str(uuid4()), 'content': '팀장에게 금요일까지 보고합니다.'}
    assert other.post(f"/api/runs/{run['id']}/input", json=body).status_code == 404
    assert owner.post(f"/api/runs/{run['id']}/input", json=body).status_code == 200
    data, _ = wait(owner, tid)
    assert data['messages'][-1]['content'] == '추가 정보를 반영했습니다.'
    assert any(m['content'] == body['content'] for m in provider.requests[1][0])


def test_cancel_stops_running_model_and_blocks_active_deletion(work):
    app, owner, other, provider = work
    provider.delay = 2
    tid = thread(owner)
    run, _ = submit(owner, tid)
    wait(owner, tid, 'running')
    assert owner.delete(f'/api/threads/{tid}').status_code == 409
    assert owner.post(f"/api/runs/{run['id']}/cancel").json()['status'] == 'cancelled'
    data, _ = wait(owner, tid, 'cancelled')
    assert not any(m['role'] == 'assistant' for m in data['messages'])


def test_steering_is_persisted_and_applied_before_final_output(work):
    app, owner, other, provider = work
    provider.delay = 0.3
    provider.responses = [[{'text': '초안'}], [{'text': '짧게 수정한 응답'}]]
    tid = thread(owner)
    run, _ = submit(owner, tid)
    wait(owner, tid, 'running')
    body = {'request_id': str(uuid4()), 'content': '답변을 짧게 해줘.'}
    assert owner.post(f"/api/runs/{run['id']}/input", json=body).status_code == 200
    assert owner.post(f"/api/runs/{run['id']}/input", json=body).status_code == 200
    data, final = wait(owner, tid)
    assert data['messages'][-1]['content'] == '짧게 수정한 응답'
    assert len([m for m in data['messages'] if m['content'] == body['content']]) == 1
    assert any(e['kind'] == 'steering_applied' for e in final['events'])


def test_project_context_files_and_private_permissions(work):
    app, owner, other, provider = work
    project = owner.post('/api/projects', json={'name': '주간 보고', 'instructions': '항상 확인할 사항을 적어줘.'}).json()
    pid = project['id']
    assert other.get('/api/projects').json() == []
    assert other.get('/api/projects/' + pid).status_code == 404
    assert other.patch('/api/projects/' + pid, json={'name': 'hijack'}).status_code == 404
    assert other.post('/api/threads', json={'title': 'hijack', 'project_id': pid}).status_code == 404
    file = owner.post('/api/files?name=notes.txt', content='합성 원문 파일'.encode()).json()
    fid = file['id']
    assert owner.put(f'/api/projects/{pid}/files/{fid}').status_code == 204
    tid = thread(owner, pid)
    run, _ = submit(owner, tid)
    data, final = wait(owner, tid)
    assert data['project_id'] == pid
    context = str(provider.requests[0][0])
    assert '항상 확인할 사항' in context and '합성 원문 파일' in context
    assert any(e['kind'] == 'file_read' for e in final['events'])
    assert other.post(f'/api/threads/{thread(other)}/runs', json={'request_id': str(uuid4()), 'content': 'read', 'file_ids': [fid]}).status_code == 404
    assert owner.delete(f'/api/projects/{pid}/files/{fid}').status_code == 204
    assert owner.get('/api/projects/' + pid).json()['files'] == []


@pytest.mark.parametrize('name,body', [('x.pdf', b'%PDF synthetic'), ('x.txt', b'\xff\xff'), ('x.txt', b'a' * 50001)])
def test_unsupported_input_is_rejected_before_model_call(work, name, body):
    app, owner, _, provider = work
    fid = owner.post('/api/files?name=' + name, content=body).json()['id']
    tid = thread(owner)
    response = owner.post(f'/api/threads/{tid}/runs', json={'request_id': str(uuid4()), 'content': 'read', 'file_ids': [fid]})
    assert response.status_code == 422
    assert provider.requests == []


def test_missing_provider_and_model_failure_do_not_create_fake_answer(work):
    app, owner, _, provider = work
    tid = thread(owner)
    provider.ready = False
    assert owner.post(f'/api/threads/{tid}/runs', json={'request_id': str(uuid4()), 'content': 'test'}).status_code == 503
    provider.ready = True
    provider.responses = [[ModelError('MODEL_AUTH')]]
    submit(owner, tid)
    data, result = wait(owner, tid, 'failed')
    assert result['error'] == 'MODEL_AUTH'
    assert not any(m['role'] == 'assistant' for m in data['messages'])


@pytest.mark.parametrize('filename', ['../outside.md', 'file.html', 'a\\b.md'])
def test_generated_file_paths_and_types_are_bounded(work, filename):
    app, owner, _, provider = work
    provider.responses = [[tool('create_document', {'filename': filename, 'title': 'bad', 'content': 'bad'})]]
    tid = thread(owner)
    submit(owner, tid)
    data, run = wait(owner, tid, 'failed')
    assert run['error'] == 'TOOL_INPUT_INVALID'
    assert data['artifacts'] == []


def test_one_active_work_request_per_thread_and_attachment_delete_guard(work):
    app, owner, _, provider = work
    provider.delay = 2
    fid = owner.post('/api/files?name=x.txt', content=b'synthetic').json()['id']
    tid = thread(owner)
    run, _ = submit(owner, tid, file_ids=[fid])
    assert owner.post(f'/api/threads/{tid}/runs', json={'request_id': str(uuid4()), 'content': 'second'}).status_code == 409
    assert owner.delete('/api/files/' + fid).status_code == 409
    owner.post(f"/api/runs/{run['id']}/cancel")
    assert owner.delete('/api/files/' + fid).status_code == 204


def test_startup_recovers_interrupted_work_without_replaying_model(tmp_path):
    app = create_app(Settings(database_url=f'sqlite:///{tmp_path}/restart.db', environment='test'))
    from lh_agent.db import Base
    Base.metadata.create_all(app.state.engine)
    with app.state.sessions() as db:
        seed(db, PASSWORD)
        for status in ('running', 'queued', 'waiting_input'):
            tid = str(uuid4())
            db.add(Thread(id=tid, owner_id='alice', title=status))
            db.flush()
            db.add(Run(id=str(uuid4()), owner_id='alice', thread_id=tid, mode='work', request_hash=status, status=status))
        db.commit()
    # No provider key is configured, so startup cannot dispatch/replay queued requests.
    with TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN}):
        with app.state.sessions() as db:
            rows = list(db.scalars(select(Run)))
            assert sorted(r.status for r in rows) == ['failed', 'queued', 'waiting_input']
            assert next(r for r in rows if r.status == 'failed').error == 'SERVER_RESTARTED'


def test_repeated_requests_use_only_new_steering_not_old_history(work):
    app, owner, _, provider = work
    tid = thread(owner)
    for index in range(45):
        owner.post(f'/api/threads/{tid}/messages', json={'content': 'old synthetic message ' + str(index)})
    run, _ = submit(owner, tid)
    data, result = wait(owner, tid)
    assert result['status'] == 'completed'
    assert len(provider.requests) == 1
    assert not any(e['kind'] == 'steering_applied' for e in result['events'])
