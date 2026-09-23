# NEO Connector

The Connector provides programmatic access to the NEO agent.

## Core API

- `run_task()` – in-process execution
- `run_task_subprocess()` – isolated subprocess execution
- `run_from_stdin()` – JSON-over-stdin protocol
- `serve_http()` – demo HTTP server (not for production)

## Extending the Connector

We provide skeleton files to demonstrate how NEO can be extended:

- `server.py` – turn NEO into a remote HTTP/gRPC service
- `client.py` – Python client for the remote server
- `hub.py` – route tasks to multiple NEO workers
- `delegate.py` – allow an NEO agent to delegate sub-tasks

**These are templates, not production-ready implementations.**

## Security

When exposing NEO over a network, you are responsible for:

- Authentication & authorisation
- Input validation & sanitisation
- Rate limiting
- Sandboxing / containerisation
- Logging & monitoring
- Timeouts & resource limits

**We do not provide a turnkey server. The Connector is a foundation.**

## Integration Examples

See the skeleton files for example usage.