FROM rasa/rasa:3.4.2-full

USER root

WORKDIR /app

# https://dev.to/0xbf/set-timezone-in-your-docker-image-d22
RUN apt install -yq tzdata && \
    ln -fs /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata

COPY . .

RUN pip config set global.index-url https://mirrors.ustc.edu.cn/pypi/web/simple
RUN pip install aiohttp ruamel.yaml supervisor "sanic-ext<22"

ENTRYPOINT [ "sh" ]

CMD ["run.sh"]