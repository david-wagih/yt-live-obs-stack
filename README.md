# Observability Live Demo

A local, live-friendly observability stack for a YouTube demo: a small FastAPI app
sends metrics, logs, and traces via OTLP to an OpenTelemetry Collector, which fans
them out to Prometheus, Loki, and Tempo. Grafana visualizes all three.

## Architecture

```
Traffic Generator / User
        |
        v
   FastAPI Demo App  --OTLP gRPC (4317)-->  OpenTelemetry Collector
                                                 |        |        |
                                          metrics|    logs|  traces|
                                                 v        v        v
                                          Prometheus    Loki     Tempo
                                          (scrapes      (OTLP    (OTLP
                                           :9464 on      HTTP     gRPC
                                           collector)    /otlp)   :4317)
                                                 \        |        /
                                                  \       |       /
                                                   v      v      v
                                                       Grafana
```

Telemetry routing:

```
Application
    | OTLP (gRPC :4317)
OpenTelemetry Collector
    |-- metrics -> Prometheus exporter (:9464) -> Prometheus scrapes it
    |-- logs    -> Loki native OTLP endpoint (http://loki:3100/otlp)
    `-- traces  -> Tempo OTLP endpoint (tempo:4317)

Grafana
    |-- Prometheus datasource
    |-- Loki datasource
    `-- Tempo datasource
```

The OpenTelemetry Collector is the single, central telemetry pipeline. No
Promtail, no Grafana Alloy.

## Prerequisites

- Docker + Docker Compose v2
- Python 3.8+ on the host (for the traffic generator; stdlib only, no pip install needed)

## Ports

| Service            | Port |
|---------------------|------|
| FastAPI app          | 8000 |
| Grafana               | 3000 |
| Prometheus            | 9090 |
| Loki                   | 3100 |
| Tempo (HTTP/query)     | 3200 |
| OTel Collector gRPC     | 4317 |
| OTel Collector HTTP     | 4318 |
| OTel Collector Prometheus exporter | 9464 |

Tempo's and the app's internal-only ports (e.g. Tempo's own OTLP receiver) are
not published beyond what's listed above.

## Start it up

```bash
make up      # docker compose up --build -d
make logs    # follow logs
make down    # stop
make clean   # stop and remove volumes/orphans
```

Grafana: http://localhost:3000 (anonymous access enabled, Admin role — no login
needed for the live; default admin/admin credentials also work and are
configurable via `GF_ADMIN_USER` / `GF_ADMIN_PASSWORD` env vars).

## Verification checklist

- [ ] `docker compose up --build` brings up all 6 containers.
- [ ] `curl http://localhost:8000/health` returns `{"status":"ok"}`.
- [ ] `curl http://localhost:9090/api/v1/targets` shows the `otel-collector` job as `up`.
- [ ] `curl http://localhost:9464/metrics` shows `http_server_duration_milliseconds_*` series.
- [ ] Grafana has Prometheus, Loki, and Tempo datasources (Connections -> Data sources).
- [ ] Hitting `/error` produces a log line findable in Grafana Explore -> Loki.
- [ ] Hitting `/slow` produces a trace in Grafana Explore -> Tempo with an obvious slow child span.

## The demo application

| Endpoint        | Behavior |
|------------------|----------|
| `GET /health`      | Always fast, always 200. |
| `GET /`             | Normal request path. |
| `GET /api/orders`     | Business-style endpoint with child spans: `validate-request`, `query-orders-database`, `serialize-response`. |
| `GET /slow`             | Sleeps ~2-5s inside a `simulated-slow-operation` child span (configurable via `SLOW_MIN_SECONDS`/`SLOW_MAX_SECONDS`). |
| `GET /error`             | Always returns HTTP 500 and logs `request failed intentionally` at ERROR. |

`/api/orders` can optionally be made to intermittently fail or slow down via
`ORDERS_FAIL_RATE` / `ORDERS_SLOW_RATE` (0.0-1.0) and `ORDERS_SLOW_SECONDS`,
set as environment variables on the `app` service in `docker-compose.yml`.
Deterministic endpoints (`/error`, `/slow`) always exist regardless, so the live
demo never depends on randomness.

Resource attributes set on every signal: `service.name=observability-demo-api`,
`service.version=1.0.0`, `deployment.environment=local`.

## Verified metric names (do not trust the placeholder names below without re-checking)

The app relies on OpenTelemetry's automatic FastAPI/ASGI instrumentation. After
running the stack and inspecting `curl http://localhost:9464/metrics`, the
actual emitted series are:

- `http_server_duration_milliseconds_count` / `_bucket` / `_sum` — a histogram;
  its `_count` acts as the request counter, `_bucket` gives you latency
  percentiles.
- `http_server_active_requests` — gauge.
- `http_server_response_size_bytes` — histogram.

Useful labels on `http_server_duration_milliseconds_*`: `http_method`,
`http_status_code`, `http_target` (the route, e.g. `/api/orders` — static, so
no cardinality problem), `job` (= `service.name`).

### Verified PromQL

Total request rate:

```promql
sum(rate(http_server_duration_milliseconds_count[1m]))
```

Request rate by HTTP status:

```promql
sum by (http_status_code) (
  rate(http_server_duration_milliseconds_count[1m])
)
```

P95 latency (milliseconds):

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(http_server_duration_milliseconds_bucket[1m])
  )
)
```

Request rate by route:

```promql
sum by (http_target) (
  rate(http_server_duration_milliseconds_count[1m])
)
```

## Verified LogQL

Loki's OTLP resource-attribute mapping creates these stream labels:
`service_name`, `deployment_environment`. (`service.name` -> `service_name`,
dots become underscores.) Everything else (severity, trace_id, span_id, code
location, etc.) arrives as structured metadata on each log line.

All logs for the app:

```logql
{service_name="observability-demo-api"}
```

Filter to failures:

```logql
{service_name="observability-demo-api"} |= "failed"
```

Each log line carries `trace_id` / `span_id` as structured metadata, so you
can pivot from a log line straight to its trace in Grafana Explore (the Loki
datasource is provisioned with a derived field wired to the Tempo datasource
for this — bonus feature, not required for the core demo to work).

## Finding traces

Grafana Explore -> Tempo -> Search, filter by `Service Name =
observability-demo-api`. Or query by span name directly, e.g.
`{name="GET /slow"}`. The `/slow` trace's root span duration is ~2-5s and is
almost entirely accounted for by its `simulated-slow-operation` child span —
an unambiguous demo of "where did the time go."

`/api/orders` traces show three child spans: `validate-request`,
`query-orders-database`, `serialize-response`.

## Live build sequence

1. **App only.** Run the app, hit it with curl. "The user says it's slow — what can we see?" (Nothing, yet.)
2. **Instrument the app.** Walk through `app/telemetry.py`: resource, OTLP exporters for traces/metrics/logs, and why we ship to a collector instead of coupling directly to each backend.
3. **The Collector.** Open `otel-collector/config.yaml`. Explain receivers -> processors -> exporters, then the three pipelines.
4. **Prometheus.** Confirm the scrape target is up, run raw PromQL from the Prometheus UI before touching Grafana.
5. **Grafana dashboard (built live).** Do **not** pre-build this — create panels for Request Rate, Error Rate, P95 Latency, and Request Rate by Route live, using the PromQL above. Tie it back to the RED method.
6. **Loki.** Trigger `/error`, find it in Grafana Explore, look at labels vs. structured metadata.
7. **Tempo.** Trigger `/slow` (or `/api/orders`), open the trace, identify the slow span.
8. **Full incident.** Run `make incident`, watch error rate and P95 latency rise on the dashboard, drill into logs, then traces. Metrics -> logs -> traces, progressively deeper context.

## Traffic generator

```bash
python3 loadgen/generate_traffic.py normal    # /, /api/orders, /health
python3 loadgen/generate_traffic.py errors    # /error only
python3 loadgen/generate_traffic.py slow      # /slow only
python3 loadgen/generate_traffic.py incident  # mix of everything, weighted toward normal

# options
python3 loadgen/generate_traffic.py incident --rate 5 --duration 120
```

Runs until Ctrl-C, or for `--duration` seconds if given. Output is throttled
to every 5th request (plus every error/failed request) so it doesn't flood the
terminal during the live. Also available as `make traffic` / `make errors` /
`make slow` / `make incident`.

## Incident demo steps

1. `make incident` (or `python3 loadgen/generate_traffic.py incident`).
2. Grafana dashboard: error rate and P95 latency visibly rise.
3. Metrics identify the affected route (`http_target` breakdown).
4. Grafana Explore -> Loki: find the `request failed intentionally` logs.
5. Grafana Explore -> Tempo: open a slow trace, find the `simulated-slow-operation` span eating the request.
6. Wrap-up: metrics told you *something* is wrong, logs told you *what*, traces told you *where*.

## Troubleshooting

- **Grafana's Tempo datasource "Test" button says `Method not implemented`.**
  This is a known cosmetic quirk of the Tempo datasource health-check endpoint
  on some Tempo/Grafana version combos — it does not mean queries fail.
  Explore -> Tempo -> Search still works; verified independently against
  `http://localhost:3200/api/search`.
- **Collector shows "Using the 0.0.0.0 address exposes this server..." warnings.**
  Expected and harmless — this is a local Docker Compose teaching environment,
  not a production deployment.
- **`docker compose up` seems stuck on Grafana.** Grafana waits for Prometheus
  and Loki to report healthy first (`depends_on: condition: service_healthy`).
  Tempo and the OTel Collector don't ship a shell/HTTP client in their images,
  so they can't have a Docker-level `HEALTHCHECK`; they're both retried-on by
  their consumers instead (OTLP exporters retry automatically).
- **No metrics/logs/traces show up at all.** Check `docker compose logs
  otel-collector` for exporter errors first — that's the single chokepoint
  all three signals pass through.

## Scope boundaries

Deliberately excluded to keep the first live focused: Kubernetes,
Alertmanager, Mimir, service mesh, Kafka, production HA, auth systems, TLS
infra, complex tail sampling, Grafana Alloy, Promtail.
