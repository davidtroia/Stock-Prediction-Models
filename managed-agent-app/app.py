"""Minimal client for an Anthropic managed agent.

Creates a session, opens the event stream, sends one user message, prints the
agent's reply as it streams, and exits when the session goes idle.

    export ANTHROPIC_API_KEY=sk-ant-...
    python app.py "Say hello in five words."

Exit codes: 0 finished normally, 1 API/session error, 2 bad usage, 130 Ctrl-C.
"""

from __future__ import annotations

import os
import sys

import anthropic

AGENT_ID = os.environ.get("AGENT_ID", "agent_015WLxPRn331uMQfC9Ne8qos")
ENVIRONMENT_ID = os.environ.get("ENVIRONMENT_ID", "env_013zZJZUFxPGx4M9NHB9zE1o")


def err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def run(client: anthropic.Anthropic, prompt: str) -> int:
    # `agent` accepts the bare agent ID (pins the latest version).
    # The SDK adds the managed-agents beta header itself.
    session = client.beta.sessions.create(
        agent=AGENT_ID,
        environment_id=ENVIRONMENT_ID,
    )
    err(f"[session {session.id}]")

    # Open the stream BEFORE sending, so no events are missed.
    with client.beta.sessions.events.stream(session.id) as stream:
        client.beta.sessions.events.send(
            session.id,
            events=[
                {
                    "type": "user.message",
                    "content": [{"type": "text", "text": prompt}],
                }
            ],
        )

        # The session can report idle before it has picked up our message;
        # only treat idle as "finished" once it has actually started working.
        started = False

        for event in stream:
            kind = event.type

            if kind == "agent.message":
                started = True
                for block in event.content:
                    if block.type == "text":
                        print(block.text, flush=True)
                    else:
                        print("[redacted]", flush=True)

            elif kind == "session.status_running":
                started = True

            elif kind == "session.status_idle":
                if not started:
                    continue
                reason = event.stop_reason.type
                if reason == "end_turn":
                    return 0
                # requires_action (needs a tool confirmation/result this app
                # can't give), retries_exhausted, budget_reached, refusal.
                err(f"[session idle: {reason}]")
                return 1

            elif kind == "session.error":
                err(f"[session error: {event.error.type}]")
                return 1

            elif kind == "session.status_terminated":
                err("[session terminated]")
                return 1

    err("[stream ended before the session went idle]")
    return 1


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        err('usage: python app.py "your message"')
        return 2
    if not os.environ.get("ANTHROPIC_API_KEY"):
        err("ANTHROPIC_API_KEY is not set")
        return 2

    client = anthropic.Anthropic()
    try:
        return run(client, " ".join(sys.argv[1:]))
    except KeyboardInterrupt:
        err("\n[interrupted]")
        return 130
    except anthropic.APIStatusError as e:
        err(f"[API error {e.status_code}: {e.message}]")
        return 1
    except anthropic.APIError as e:  # connection/timeout/etc.
        err(f"[API error: {e}]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
