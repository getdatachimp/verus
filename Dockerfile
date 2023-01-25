FROM python:3.11.1-bullseye
LABEL org.opencontainers.image.source=https://github.com/getdatachimp/verus
COPY ./dist/verus-0.0.1-py3-none-any.whl /usr/var/lib/
RUN pip install /usr/var/lib/verus-0.0.1-py3-none-any.whl
CMD [ "verus" ]