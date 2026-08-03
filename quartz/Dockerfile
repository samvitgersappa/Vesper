# Vesper Second Brain — Quartz v5 static-site builder + trigger server.
#
# The Obsidian vault is mounted read-only at /vault and rsynced into
# /quartz/content on every build. `npx quartz build` emits the static site to
# /out (a named volume shared with the Caddy container, which serves it at a
# private Tailscale-only hostname per ADDENDUM_SECOND_BRAIN.md §7).
#
# A small Node server on :8081 serves the built site (dev convenience) and
# exposes `POST /rebuild` so the automation worker can trigger a rebuild
# without having Node/npm installed in the Python worker image.
#
#   docker compose up --build vesper-quartz
#   curl -X POST localhost:8081/rebuild     # rebuild now
#   open localhost:8081                     # browse the private garden

FROM node:24-alpine

RUN apk add --no-cache rsync git coreutils

WORKDIR /quartz

# Official Quartz v5 template (pinned branch). The repo IS the template.
RUN git clone --depth 1 --branch v5 https://github.com/jackyzha0/quartz.git . \
  && npm ci --no-audit --no-fund

# Our config + build/trigger tooling.
COPY quartz/quartz.config.yaml ./quartz.config.yaml
COPY quartz/entrypoint.sh quartz/rebuild.sh quartz/sanitize.sh quartz/index.template.md quartz/server.mjs ./

ENV VAULT_DIR=/vault \
    CONTENT_DIR=/quartz/content \
    OUTPUT_DIR=/out \
    TRIGGER_PORT=8081 \
    BASE_URL=brain.local \
    PATH="/quartz/node_modules/.bin:${PATH}"

RUN chmod +x ./entrypoint.sh ./rebuild.sh ./sanitize.sh

EXPOSE 8081

CMD ["./entrypoint.sh"]
