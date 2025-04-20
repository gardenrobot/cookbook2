FROM python:3.10-bullseye

RUN pip install pipenv

ENV PROJECT_DIR /app

WORKDIR /app

COPY Pipfile Pipfile.lock ${PROJECT_DIR}/

RUN pipenv install --system --deploy

COPY run.py ${PROJECT_DIR}/
COPY static/ static/
COPY templates/ templates/

CMD python run.py
