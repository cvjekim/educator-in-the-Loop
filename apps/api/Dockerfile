FROM python:3.12-slim
WORKDIR /app
COPY apps/api/requirements.txt apps/api/requirements.txt
COPY manager-agent/requirements.txt manager-agent/requirements.txt
COPY lecture-note-agent/requirements.txt lecture-note-agent/requirements.txt
COPY practice-agent/requirements.txt practice-agent/requirements.txt
COPY written-exam-agent/requirements.txt written-exam-agent/requirements.txt
COPY project-exam-agent/requirements.txt project-exam-agent/requirements.txt
RUN pip install --no-cache-dir -r apps/api/requirements.txt
COPY apps/api apps/api
COPY apps/__init__.py apps/__init__.py
COPY manager-agent/app.py manager-agent/app.py
COPY manager-agent/src manager-agent/src
COPY manager-agent/prompts manager-agent/prompts
COPY lecture-note-agent/app.py lecture-note-agent/app.py
COPY lecture-note-agent/src lecture-note-agent/src
COPY practice-agent/app.py practice-agent/app.py
COPY practice-agent/src practice-agent/src
COPY practice-agent/prompts practice-agent/prompts
COPY written-exam-agent/app.py written-exam-agent/app.py
COPY written-exam-agent/src written-exam-agent/src
COPY written-exam-agent/prompts written-exam-agent/prompts
COPY project-exam-agent/app.py project-exam-agent/app.py
COPY project-exam-agent/src project-exam-agent/src
COPY project-exam-agent/prompts project-exam-agent/prompts
RUN useradd --uid 10001 --create-home educator && mkdir /data && chown educator /data
USER educator
ENV PYTHONDONTWRITEBYTECODE=1 API_DATABASE=/data/service.sqlite3
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
