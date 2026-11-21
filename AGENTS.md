# Search Autoresearch Referee

This repo creates a service that acts like a referee for search retrieval autoresearch tasks.

## Coding practices

This is a python project using uv, flake8, pyright. We should install pre-commit hook and 
fix any issues that arise from these tools during a commit.

Use python available via asdf in 3.15.2

Code is implemented in referee/ folder and python module

## Code structure

Most functionality can be driven from a CLI. Where the CLI is structured with seperation from
a thin frontend using argparse to parse arguments, turning that into a dataclass of arguments.
Then a thicker backend controller is called that executes the task.

This lets us perform e2e testing where we call the controller using a structured dataclass and 
observe the end-to-end functionality, only mocking at certain costly API boundaries. We don't
mock postgres in e2e tests.

The CLI acts as a convenient way to drive a major subsystem of the project. For human and 
agent reproducability. But it's likely the full system may involve wiring together these
subsystems directly through Python code-calls.

The CLI backend should also be able to be used through an API call. IE a service with a REST
API. We should have the same level of translation we have in CLI / API, but avoid business
logic that's not related to just the API.

### Code structure specifics

Under the referee folder (the main python module) we will organize as follows

referee/cli     # cli frontends for runners (kept thin, argparse -> structured task)
referee/api     # fastapi frontends for runners (kept thin, request -> structured task)

Then we will organize each subsystem as

referee/<subsystem>

IE for sessions

referee/session/

In here will hold

- A class to interact with Postgres database through direct SQL with psycopg2 (In this case we'll
  just call this SessionDB)
- A controller backend to accept the structured frontend, do the tasks, then return results as expected

So we'd have

referee/session/db.py
referee/session/controller.py


## Database

A postgres database is used to store the state of the system. Such as session keys (see docs)
The docs may describe tables associated with those subsystems.

Migrations should exist in a database/ folder, as a .sql folder. For now, no migrations are nedeed
and we should just expect to wipe and recreate the database as needed. 

## Types of tests

Unit tests should be used liberally, at your discretion, to test individual classes or 
python modules.

The meat of this repos tests are the e2e tests. As mentioned, we drive a major subsystem
through backend CLI, and observe major functionality. We mock certain API boundaries. Generally
we don't mock databases.

These tests should be behavioral as much as possible about the subsystem. Able to be read clearly
as testing a specific, behavioral requirement of the system.

## Mandatory reading

The docs/ folder discusses major subsystems to implement.

The general usage flow goes like

### Create session

See docs/session.md

Define the parameters of a query set within a dataset, and also
splits. Receive a bearer token for each  split. The orchestrator
will delegate tokens to the caller.

### Run eval tasks

See docs/eval.md

Given a bearer token, access the eval tasks (ie list of queries) to run. Get 
a task_id. The client then submits results back to the service for evaluation.
