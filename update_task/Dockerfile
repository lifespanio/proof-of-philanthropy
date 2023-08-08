FROM python:3.8.0-slim as builder

RUN mkdir /app/

COPY ./lifespan_update/requirements.txt /app

RUN pip install --upgrade pip
RUN pip install -r /app/requirements.txt

FROM builder

COPY ./lifespan_update/update.py /app
COPY ./lifespan_update/config.json /app
COPY ./lifespan_update/PoP_abi.json /app
COPY ./lifespan_update/run.sh /app

RUN chmod a+x /app/run.sh

WORKDIR /app

CMD [ "/app/run.sh" ]
