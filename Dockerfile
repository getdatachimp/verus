FROM python:3.11.1-bullseye
COPY ./dist/verus-0.0.1-py3-none-any.whl /usr/var/lib/
RUN pip install /usr/var/lib/verus-0.0.1-py3-none-any.whl
CMD [ "verus" ]