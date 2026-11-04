# syntax=docker/dockerfile:1
# Zivon inference router (DEV TOOL, not a product image - not in CI).
#
# Problem: the dev machine's OpenAI-format inference server binds 127.0.0.1 only.
# Containers and minikube pods can never reach a host's loopback.
# Solution: this tiny router runs with host networking (so its 127.0.0.1 IS the
# host loopback, where the server lives) and forwards every TCP connection from
#   192.168.49.1:18080   (minikube's host-side bridge IP - NOT the LAN)
# to
#   127.0.0.1:8080       (the inference server, untouched).
# The factory treats the router as a normal OpenAI-format server; the inference
# server itself is never reconfigured.
#
#   Build: docker build -f docker/inference-router.Dockerfile -t zivon-inference-router:0.1.0 .
#   Run:   docker compose up -d inference-router
#   Then:  ZIVON_BASE_URL=http://192.168.49.1:18080/v1
#
# Knobs (env): ROUTER_BIND (default 192.168.49.1), ROUTER_PORT (18080),
# SERVER_PORT (8080). Bind stays off 0.0.0.0 on purpose: the inference server
# chose loopback-only privacy; the router only re-exposes it to the cluster.

FROM alpine:3.20

RUN apk add --no-cache socat

USER 1000
EXPOSE 18080

CMD ["sh", "-c", "exec socat TCP-LISTEN:${ROUTER_PORT:-18080},bind=${ROUTER_BIND:-192.168.49.1},reuseaddr,fork TCP:127.0.0.1:${SERVER_PORT:-8080}"]
