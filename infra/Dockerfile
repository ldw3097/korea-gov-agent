FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/services/api
WORKDIR /app
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home lhagent && mkdir /data && chown lhagent:lhagent /data
COPY --chown=10001:10001 services/api/lh_agent /app/services/api/lh_agent
COPY --chown=10001:10001 apps/web /app/apps/web
USER lhagent
EXPOSE 3000
CMD ["uvicorn", "lh_agent.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "3000", "--no-access-log", "--no-proxy-headers"]
