FROM node:20-alpine AS builder

# NEXT_PUBLIC_* vars are embedded at build time by Next.js — they cannot be
# injected at container runtime. Pass them via docker compose build.args.
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
ENV NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=${NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY}

WORKDIR /app
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web/ .
RUN npm run gen:types
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
