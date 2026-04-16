FROM docker.1ms.run/library/python:3.12-slim

WORKDIR /app

# Use Tsinghua mirror for apt
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY . .

CMD ["celery", "-A", "app.tasks.celery_app", "worker", "--loglevel=info"]
