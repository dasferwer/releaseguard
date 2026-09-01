from prometheus_client import Counter, Gauge, Histogram

RELEASES_CREATED = Counter("releaseguard_releases_created_total", "Created releases")
RELEASE_TRANSITIONS = Counter(
    "releaseguard_transitions_total", "Release state transitions", ["target"]
)
WEBHOOKS = Counter("releaseguard_webhooks_total", "CI webhooks", ["result"])
CANARY_DECISIONS = Counter("releaseguard_canary_decisions_total", "Canary decisions", ["decision"])
ACTIVE_RELEASES = Gauge("releaseguard_active_releases", "Active releases")
HTTP_LATENCY = Histogram("releaseguard_http_seconds", "HTTP request duration", ["method", "path"])
