# Part 2: Dashboards & Alerts — Live Build Reference

Companion to `README.md` (Part 1: standing up the stack). This is the script
for building the Grafana dashboard and alert rules **live**, on top of a
stack that's already running and verified healthy. Nothing in this file is
pre-provisioned — same philosophy as Part 1's dashboard step: build it live,
not from a canned JSON export, so the audience sees each panel/rule come
together from a blank query.

## Before you start

Run through the Part 1 verification checklist first (`README.md` ->
Verification checklist). In particular:

- [ ] `make up` (or `make CONTAINER_ENGINE=podman up`) — all 6 containers healthy.
- [ ] Grafana reachable at http://localhost:3000, Prometheus/Loki/Tempo
      datasources present under Connections -> Data sources.
- [ ] `python3 loadgen/generate_traffic.py normal` produces traffic you can
      see reflected somewhere (even just via `curl http://localhost:9464/metrics` or Prometheus).

Alerting in this file uses **Grafana's built-in (Grafana-managed) alerting
engine** — the one shipped inside the `grafana` container. This is distinct
from a standalone Alertmanager service, which stays out of scope (see
README's Scope boundaries) — no extra container needed.

## Recap: what data lives where

| Signal | Datasource | Query language |
|---|---|---|
| Metrics | Prometheus | PromQL |
| Logs | Loki | LogQL |
| Traces | Tempo | TraceQL / Search |

All verified metric names, labels, PromQL, and LogQL live in `README.md`
under "Verified metric names" / "Verified PromQL" / "Verified LogQL" —
reuse those, don't re-derive them live.

---

## Dashboard build plan (RED method)

Build one dashboard, "Observability Demo — RED", with these panels, in this
order. Each row below is a live-build step: create panel -> paste query ->
explain what it shows -> move on.

### 1. Request Rate

- **Viz type:** Time series
- **Query (Prometheus):**
  ```promql
  sum(rate(http_server_duration_milliseconds_count[1m]))
  ```
- **Unit:** requests/sec (`reqps` in Grafana's unit picker, or leave as short)
- **Talking point:** the "R" in RED — total throughput, no breakdown yet.

### 2. Error Rate (by status code)

- **Viz type:** Time series
- **Query (Prometheus):**
  ```promql
  sum by (http_status_code) (
    rate(http_server_duration_milliseconds_count[1m])
  )
  ```
- **Talking point:** the "E" in RED. Normal traffic never produces 5xx (no
  `/error` hits); this stays flat until `make incident` runs.

### 3. P95 Latency

- **Viz type:** Time series
- **Query (Prometheus):**
  ```promql
  histogram_quantile(
    0.95,
    sum by (le) (
      rate(http_server_duration_milliseconds_bucket[1m])
    )
  )
  ```
- **Unit:** milliseconds (`ms`)
- **Talking point:** the "D" (duration) in RED. `/slow` is ~9% of incident
  traffic, which is enough to drag P95 up sharply once incident mode runs.

### 4. Request Rate by Route

- **Viz type:** Time series (or Bar gauge for variety)
- **Query (Prometheus):**
  ```promql
  sum by (http_target) (
    rate(http_server_duration_milliseconds_count[1m])
  )
  ```
- **Talking point:** which route is driving the load/incident — sets up the
  "drill into logs/traces for that route" pivot.

### 5. (Stretch) Logs panel

- **Viz type:** Logs
- **Datasource:** Loki
- **Query:**
  ```logql
  {service_name="observability-demo-api"}
  ```
- Add this as a panel, or just do it live in Explore instead — either works;
  a dashboard panel is nice for "everything in one view" during the incident
  walkthrough.

### Layout note

Arrange as a 2x2 grid (Request Rate / Error Rate on top, P95 Latency /
Request Rate by Route below) so all four RED signals are visible without
scrolling — matters for OBS framing.

---

## Alert rules build plan

Create these under Alerting -> Alert rules -> New alert rule. Put them all
in one evaluation group so they share a fast evaluation cadence for the
live demo.

- **Folder:** `Observability Demo`
- **Evaluation group:** `demo-alerts`, **evaluation interval: 10s** (fast on
  purpose — this is a demo, not production; default 1m+ intervals make the
  live segment drag).

### Alert 1 — High error rate

- **Query A (Prometheus, Instant):**
  ```promql
  sum(rate(http_server_duration_milliseconds_count{http_status_code=~"5.."}[1m]))
  ```
- **Condition:** WHEN `last()` OF `A` IS ABOVE `0.05`
- **Pending period ("for"):** `30s`
- **Why a raw rate, not a ratio:** `errors / total` divides by zero (NaN)
  whenever there's no traffic at all, which trips "No Data" handling for no
  reason. A raw 5xx rate avoids that — normal traffic never emits 5xx at
  all, so any sustained value above ~0 is meaningful.
- **Labels:** `severity=critical`, `team=demo`
- **Summary annotation:** `5xx rate is {{ $values.A }}/s`

### Alert 2 — High P95 latency

- **Query A (Prometheus, Instant):**
  ```promql
  histogram_quantile(
    0.95,
    sum by (le) (
      rate(http_server_duration_milliseconds_bucket[1m])
    )
  )
  ```
- **Condition:** WHEN `last()` OF `A` IS ABOVE `1000` (milliseconds)
- **Pending period:** `30s`
- **Labels:** `severity=warning`, `team=demo`
- **Summary annotation:** `P95 latency is {{ $values.A }}ms`

### Alert 3 — No traffic / app or collector down

- **Query A (Prometheus, Instant):**
  ```promql
  absent_over_time(http_server_duration_milliseconds_count[2m])
  ```
- **Condition:** WHEN `last()` OF `A` IS ABOVE `0.5`
- **Pending period:** `0s` (fire immediately once absence is confirmed)
- **Labels:** `severity=critical`, `team=demo`
- **Talking point:** this is the "the pipeline itself broke" alert — fires
  if the app crashes, or the collector stops forwarding to Prometheus, i.e.
  the case where every other alert goes silent for the wrong reason.

### Alert 4 — (Stretch) Failed-request log spike

- **Query A (Loki, Instant):**
  ```logql
  count_over_time({service_name="observability-demo-api"} |= "failed" [1m])
  ```
- **Condition:** WHEN `last()` OF `A` IS ABOVE `3`
- **Pending period:** `0s`
- **Talking point:** shows alerting isn't Prometheus-only — Loki data can
  drive an alert rule the same way.

### Contact points / notification policy

For the live: **don't wire up real notification delivery** (email/Slack)
unless you already have a channel to demo against — it adds setup risk for
no visual payoff on stream. Instead:

- Watch state transitions directly in Alerting -> Alert rules: `Normal` (green)
  -> `Pending` (yellow) -> `Firing` (red).
- Alerting -> "State history" / the alert's own timeline panel shows the
  transition over time — good for a post-incident recap shot.

If you do want a live notification, the lowest-setup option is a webhook
contact point pointing at a throwaway URL from a site like webhook.site,
just to show a payload land in real time. Treat that as optional flourish,
not the core of the segment.

---

## Live trigger script

Run these against the running stack to make each alert/panel move on
screen. All from `loadgen/generate_traffic.py` (also exposed as `make`
targets):

| Command | What it drives | Alerts it should trip |
|---|---|---|
| `make traffic` (`normal`) | Baseline Request Rate panel movement | none |
| `make errors` | Error Rate panel spikes, 5xx-only | Alert 1 |
| `make slow` | P95 Latency panel spikes | Alert 2 |
| `make incident` | All panels move; mixed traffic | Alert 1 + Alert 2, briefly |
| *(stop the `app` container)* | Request Rate drops to zero | Alert 3 |

Suggested on-stream order: `make traffic` first (baseline, all green) ->
`make errors` (Alert 1 fires, point at Error Rate panel) -> `make slow`
(Alert 2 fires, point at P95 panel) -> stop `make errors`/`make slow`, run
`make incident` (both panels move together, tie back to RED) -> Explore ->
Loki for the `failed` logs -> Explore -> Tempo for a `/slow` trace -> done.

To stop the app and trip Alert 3:

```bash
podman stop app   # or: docker stop app
# ... show Alert 3 go Pending -> Firing ...
podman start app  # or: docker start app
```

---

## Persisting the dashboard (optional, after the live)

Once the dashboard is built live and you're happy with it, export it as
JSON (dashboard settings -> JSON Model, or Share -> Export) and drop it
under a new `grafana/provisioning/dashboards/` directory with a matching
provider config, so `make up` brings it back pre-built on future runs. Not
needed for the live itself — only do this afterward, if you want the
dashboard to survive `make clean`.

---

## Live build sequence

1. **Recap Part 1.** Stack is up, `/health` is 200, datasources are wired.
   No dashboard exists yet — Grafana is empty save for datasources.
2. **Build the RED dashboard live**, panel by panel, per the plan above.
   Run `make traffic` in a terminal in the background so panels have
   something to render while you build them.
3. **Explain RED** as each panel goes in: Rate, Errors, Duration — the
   three questions "is it up," "is it broken," "is it slow."
4. **Build the alert rules live**, per the plan above. Show a rule
   evaluating with no data first (traffic already running, so should be
   `Normal`), then explain the threshold choice for each.
5. **Trip Alert 1** with `make errors`. Watch it go Pending -> Firing on the
   Error Rate panel and in Alerting -> Alert rules simultaneously.
6. **Trip Alert 2** with `make slow`. Same pattern on P95 Latency.
7. **Full incident.** `make incident` — tie it back to the Part 1 incident
   demo steps (metrics -> logs -> traces), but now with alerts firing
   on-screen instead of just panels moving.
8. **Trip Alert 3** by stopping the `app` container — the "the signal
   itself went missing" case, distinct from the app being merely broken.
9. **Wrap-up.** Alerts turn a dashboard you have to watch into a system
   that tells you when to look.

## Troubleshooting

- **Alert stuck in "No Data" instead of evaluating.** Almost always the
  query datasource picker defaulted to the wrong source, or the query
  isn't marked "Instant" — range queries return a series over time, not a
  single scalar, and the threshold condition needs a scalar.
- **P95 alert never fires during `make slow`.** Check the evaluation
  window (`[1m]` in the query) isn't longer than how long you've been
  running traffic — give it at least one full window before expecting a
  value.
- **Error rate alert flaps Pending/Normal instead of settling on Firing.**
  Traffic generator default rate is 2 req/s; if that's too sparse for your
  `for` duration, either lower the threshold (`0.05` -> `0.02`) or raise
  `--rate` on the loadgen command.
- **Prometheus panel/alert query returns nothing at all.** Confirm the
  collector's remote-write is actually landing — `curl
  http://localhost:9090/api/v1/query?query=up` won't help here (this stack
  uses remote-write, not scrape); instead check `docker compose logs
  otel-collector` (or `podman compose logs otel-collector`) for
  exporter errors, same as the Part 1 troubleshooting section says.
