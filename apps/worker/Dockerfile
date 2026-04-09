FROM python:3.12-slim
WORKDIR /app
COPY apps/worker/requirements.txt apps/worker/requirements.txt
RUN pip install --no-cache-dir -r apps/worker/requirements.txt
COPY packages/schemas/python packages/schemas/python
COPY packages/design-ir packages/design-ir
COPY packages/llm packages/llm
COPY packages/kicad packages/kicad
COPY packages/verification packages/verification
RUN pip install --no-cache-dir -e packages/schemas/python -e packages/design-ir -e packages/llm -e packages/kicad -e packages/verification
COPY apps/worker apps/worker
WORKDIR /app/apps/worker
ENV PYTHONPATH=/app/apps/worker/src
CMD ["python", "-m", "worker.main"]
