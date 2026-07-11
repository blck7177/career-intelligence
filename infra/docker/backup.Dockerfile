FROM postgres:16-alpine

RUN apk add --no-cache bash coreutils

COPY infra/docker/backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh

ENTRYPOINT ["backup.sh"]
