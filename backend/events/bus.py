"""Event bus — Redis pub/sub wrapper.

Modules never call each other directly; they publish to the bus and whoever
subscribed consumes. Hermes Agent sits OUTSIDE this graph (plan.md §0/§6) — at
the edges only, as a consumer/producer, never as a node inside it.

Phase 1 scaffold: client + publish/subscribe primitives; wired into modules in
Phase 4.
"""

import json
import os
import redis

# Host-friendly default (matches db.py): Hermes MCP servers run on the host and
# do NOT load .env, so they rely on this default. Docker containers override via
# env_file (.env) with the in-network `redis://redis:6379/0`.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


class EventBus:
    """Thin wrapper over Redis pub/sub."""

    def __init__(self, url: str = REDIS_URL):
        self._client = redis.Redis.from_url(url, decode_responses=True)

    def publish(self, event: str, payload: dict) -> None:
        """Publish an event (event name from events/catalog.py) with a JSON payload."""
        self._client.publish(event, json.dumps(payload, default=str))

    def subscribe(self, event: str, handler) -> None:
        """Blocking subscription: call handler(event, payload) for each message.

        Run in a worker thread/process. For production consumption prefer a
        dedicated subscriber process per job.
        """
        pubsub = self._client.pubsub()
        pubsub.subscribe(event)
        for message in pubsub.listen():
            if message["type"] == "message":
                handler(event, json.loads(message["data"]))

    def subscribe_multi(self, events: list[str], handler) -> None:
        """Subscribe to several channels; call handler(event, payload) for each."""
        pubsub = self._client.pubsub()
        pubsub.subscribe(*events)
        for message in pubsub.listen():
            if message["type"] == "message":
                handler(message["channel"], json.loads(message["data"]))


# Module-scoped shared instance.
bus = EventBus()
