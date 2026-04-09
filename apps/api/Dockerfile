FROM python:3.12-slim
WORKDIR /app
COPY apps/api/requirements.txt apps/api/requirements.txt
RUN pip install --no-cache-dir -r apps/api/requirements.txt
COPY packages/schemas/python packages/schemas/python
COPY packages/design-ir packages/design-ir
COPY packages/llm packages/llm
COPY packages/kicad packages/kicad
COPY packages/verification packages/verification
RUN pip install --no-cache-dir -e packages/schemas/python -e packages/design-ir -e packages/llm -e packages/kicad -e packages/verification
COPY apps/api apps/api
WORKDIR /app/apps/api
ENV PYTHONPATH=/app/apps/api/src
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
