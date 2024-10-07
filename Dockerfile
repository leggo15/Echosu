FROM python:3.12-slim AS web

# pip requirements
RUN --mount=type=bind,dst=/tmp/requirements.txt,src=./requirements.txt \
    --mount=type=cache,mode=0755,target=/root/.cache/pip \
    pip3 install -r /tmp/requirements.txt


WORKDIR /echosu
ENTRYPOINT [ "python3", "./manage.py", "runserver", "0.0.0.0:8080" ]
