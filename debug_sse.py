import asyncio
import copy
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(r"E:\workspace\Multi-agent\.flow\wt\g1")
for p in ("domain", "application", "persistence"):
    sys.path.insert(0, str(ROOT / "packages" / p / "src"))

from flowpilot_api import InMemoryEventStream, TrustedRequestIdentity, create_app
from flowpilot_api.testing import StaticRequestSecurity
from flowpilot_application import (
    TaskEventStreamConfig,
    TaskEventSubscriptionService,
)
from flowpilot_domain import ActorType, Task
from flowpilot_persistence import MemoryDataUnitOfWorkFactory, OutboxEvent

NOW = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)

case = json.loads(
    (ROOT / "contracts" / "conformance" / "rc2-cases.json").read_text(
        encoding="utf-8"
    )
)
valid = copy.deepcopy(
    [c["instance"] for c in case["cases"] if c["case_id"] == "task.completed.valid"][0]
)
task = Task.from_mapping(valid)

identity = TrustedRequestIdentity(
    tenant_id="tenant-a",
    subject_id="user-123",
    subject_type=ActorType("user"),
    purpose="it_support",
    security_context_id=valid["security_context"]["context_id"],
    security_context_ref=valid["security_context"]["context_ref"],
    security_context_hash=valid["security_context"]["context_hash"],
)

uow = MemoryDataUnitOfWorkFactory()
uow.database.seed_task(task)
stream = InMemoryEventStream()
subscription = TaskEventSubscriptionService(
    unit_of_work=uow,
    stream=stream,
    config=TaskEventStreamConfig(poll_interval=0.01),
    clock=lambda: NOW,
)
security = StaticRequestSecurity(identity)
app = create_app(
    task_event_subscription=subscription,
    event_stream=stream,
    request_security=security,
)


async def main():
    async with uow() as unit:
        await unit.outbox.append(
            OutboxEvent(
                event_id="evt_00000001",
                tenant_id="tenant-a",
                aggregate_type="task",
                aggregate_id="task_12345678",
                sequence=1,
                event_type="task.created.v1",
                payload={"status": "RECEIVED", "task_ref": "task://task_12345678"},
                occurred_at=NOW,
                available_at=NOW,
            )
        )
        await unit.commit()
    print("seeded", flush=True)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/v1/tasks/events",
        "raw_path": b"/v1/tasks/events",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("test", 123),
        "server": ("test", 80),
    }
    calls = 0

    async def receive():
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    sent = []

    async def send(message):
        sent.append(message["type"])
        if message["type"] == "http.response.start":
            print("ASGI START", flush=True)
        elif message["type"] == "http.response.body":
            body = message.get("body", b"")
            if body:
                print("ASGI BODY:", body[:120], flush=True)

    task = asyncio.create_task(app(scope, receive, send))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 4
    while not task.done():
        if loop.time() > deadline:
            print("=== TIMEOUT; task stacks ===", flush=True)
            for other in asyncio.all_tasks():
                if other is asyncio.current_task():
                    continue
                print("--- task:", other.get_name(), flush=True)
                for frame in other.get_stack():
                    print(
                        "   ",
                        frame.f_code.co_filename.replace(str(ROOT), "."),
                        frame.f_code.co_name,
                        frame.f_lineno,
                        flush=True,
                    )
            break
        await asyncio.sleep(0.05)
    if task.done():
        print("app task DONE", flush=True)
        try:
            task.result()
        except Exception as exc:
            print("APP RAISED:", type(exc).__name__, exc, flush=True)
    print("subscription.last_error:", repr(subscription.last_error), flush=True)
    print("sent:", sent, flush=True)
    await subscription.close()


asyncio.run(main())
