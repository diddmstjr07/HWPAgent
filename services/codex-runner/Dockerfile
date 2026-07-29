FROM node:22-bookworm-slim

ARG CODEX_NPM_SPEC=@openai/codex@0.144.1
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates gosu \
  && rm -rf /var/lib/apt/lists/* \
  && npm install --global "${CODEX_NPM_SPEC}" \
  && npm cache clean --force

WORKDIR /app
RUN mkdir -p /app /data && chown -R node:node /app /data
COPY --chown=node:node server.mjs /app/server.mjs
COPY --chown=root:root entrypoint.sh /app/entrypoint.sh
RUN chmod 755 /app/entrypoint.sh

ENV NODE_ENV=production \
    PORT=8787 \
    AI_RUNNER_DATA_DIR=/data
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:8787/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["node", "/app/server.mjs"]
