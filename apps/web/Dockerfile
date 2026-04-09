FROM node:20-alpine
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY packages/ui-shared/package.json packages/ui-shared/package.json
RUN pnpm install --filter @traceagent/web... --frozen-lockfile=false
COPY apps/web apps/web
COPY packages/ui-shared packages/ui-shared
WORKDIR /app/apps/web
EXPOSE 3000
CMD ["pnpm", "dev", "-p", "3000", "-H", "0.0.0.0"]
