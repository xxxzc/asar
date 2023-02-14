FROM rasa/rasa:3.4.3-full

USER root

WORKDIR /app

COPY . .

RUN pip config set global.index-url https://mirrors.ustc.edu.cn/pypi/web/simple
RUN pip install aiohttp ruamel.yaml supervisor "sanic-ext<22"

ENTRYPOINT [ "bash" ]

CMD ["run.sh"]