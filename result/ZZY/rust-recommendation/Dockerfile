# Build context: result/ZZY, or deploy.py's equivalent source whitelist.
# Build on the developer machine, never on the shared two-core server.
FROM rust:1.95-alpine AS builder
RUN apk add --no-cache musl-dev
WORKDIR /src
COPY rust-recommendation/Cargo.toml rust-recommendation/Cargo.lock ./rust-recommendation/
COPY rust-recommendation/src ./rust-recommendation/src
COPY modeling/recommendation/game_aliases.json modeling/recommendation/display_names_zh.json ./modeling/recommendation/
WORKDIR /src/rust-recommendation
RUN cargo build --release --locked

FROM scratch
COPY --from=builder /src/rust-recommendation/target/release/achievement-recommendation-rust /recommendation
WORKDIR /app
ENV TMPDIR=/tmp
ENTRYPOINT ["/recommendation"]
