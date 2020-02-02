FROM python:3.8-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

RUN pip install wheel
RUN pip install aiohttp pyyaml

WORKDIR /app
COPY bot.py .

CMD ["/app/bot.py"]
