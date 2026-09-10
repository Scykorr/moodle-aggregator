FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /app
COPY web/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 aggregator \
    && useradd --uid 10001 --gid aggregator --no-create-home aggregator \
    && mkdir /data && chown aggregator:aggregator /data
COPY moodle_check.py ./moodle_check.py
COPY web/app.py web/registry.py web/catalog.py ./
COPY web/static ./static
USER 10001:10001
EXPOSE 8080
CMD ["python", "app.py"]
