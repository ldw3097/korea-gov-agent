"""Run inside the deployed image: real model + isolated synthetic DB, no live user data."""
import os
from pathlib import Path
import tempfile
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from lh_agent.app import Settings, create_app
from lh_agent.seed import seed


def main():
    # Diagnostic frames only: no exception payloads, model output, or credentials.
    from lh_agent.work import WorkRuntime
    import traceback
    original_agent = WorkRuntime.agent
    async def diagnostic_agent(self, rid):
        try:
            return await original_agent(self, rid)
        except Exception as error:
            print('Probe error type: ' + type(error).__name__)
            print('Probe frames: ' + str([(Path(f.filename).name, f.name, f.lineno) for f in traceback.extract_tb(error.__traceback__)]))
            raise
    WorkRuntime.agent = diagnostic_agent
    with tempfile.TemporaryDirectory(prefix='lh-work-probe-') as folder:
        settings = Settings(database_url='sqlite:///' + str(Path(folder) / 'probe.db'), environment='test',
                            model_api_key=os.environ['MODEL_API_KEY'],
                            model_name=os.environ['MODEL_NAME'], model_base_url=os.environ['MODEL_BASE_URL'])
        app = create_app(settings)
        with TestClient(app, base_url=settings.origin, headers={'Origin': settings.origin}) as client:
            with app.state.sessions() as db:
                seed(db, 'synthetic-probe-password-2026')
            assert client.post('/api/auth/login', json={'username': 'alice', 'password': 'synthetic-probe-password-2026'}).status_code == 200
            project = client.post('/api/projects', json={'name': '합성 연결 검증', 'instructions': '한국어로 간결하게 작성한다.'}).json()
            file = client.post('/api/files?name=probe-notes.txt', content='합성 자료: 완료 업무 3건, 예정 업무 2건. 식별 표식 Synthetic Work 2026.'.encode()).json()
            assert client.put(f"/api/projects/{project['id']}/files/{file['id']}").status_code == 204
            tid = client.post('/api/threads', json={'title': '합성 문서 생성 검증', 'project_id': project['id']}).json()['id']
            response = client.post(f'/api/threads/{tid}/runs', json={'request_id': str(uuid4()), 'mode': 'work',
                'content': '첨부된 합성 자료만 사용해 제목, 요약, 다음 할 일을 담은 짧은 보고서를 probe-report.md 파일로 만들어 줘. 질문 없이 진행해. 파일 본문에 식별 표식도 그대로 넣어 줘.'})
            assert response.status_code == 202
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                data = client.get(f'/api/threads/{tid}/workspace').json()
                run = data['runs'][0]
                if run['status'] in ('completed', 'failed', 'waiting_input', 'cancelled'):
                    break
                time.sleep(0.3)
            if run['status'] != 'completed':
                raise RuntimeError('Real work failed: ' + run['status'] + ' / ' + str(run['error']))
            assert data['artifacts'], 'No document created'
            artifact = data['artifacts'][0]
            document = client.get('/api/artifacts/' + artifact['id']).json()
            assert 'Synthetic Work 2026' in document['content']
            assert client.get('/api/artifacts/' + artifact['id'] + '/download').status_code == 200
            assert any(e['kind'] == 'file_read' for e in run['events'])
            assert any(e['kind'] == 'document_created' for e in run['events'])
            print('Real Work probe passed: project, file context, model stream, document tool, preview API, download.')
            print('All probe data was isolated from the deployed app database and removed.')


if __name__ == '__main__':
    main()
