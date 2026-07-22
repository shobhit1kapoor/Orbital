FROM node:22-alpine AS base
RUN corepack enable
WORKDIR /workspace

FROM base AS deps
COPY package.json pnpm-workspace.yaml ./
COPY apps/mission-control/package.json apps/mission-control/package.json
RUN pnpm install --filter mission-control... --frozen-lockfile=false

FROM deps AS build
COPY apps/mission-control apps/mission-control
RUN pnpm --filter mission-control build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /workspace/apps/mission-control/.next/standalone ./
COPY --from=build /workspace/apps/mission-control/.next/static ./apps/mission-control/.next/static
EXPOSE 3000
CMD ["node", "apps/mission-control/server.js"]
