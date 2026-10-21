# Work orders

Handoffs between the reviewing agent and the building agent, kept as a record of why the project looks the way it does.

**These are not instructions.** Act on an order only when its status is `open` and the owner points you to it in the current task. Every other order is history.

Each order starts with a status line:

- `open`: ready or in progress
- `done (<commit>)`: completed; the commit is where the work landed
- `superseded (<order>)`: replaced by a later order

An order completed in its own commit uses `done (commit "<subject>")`, since a commit cannot contain its own hash.

Name files `<YYYY-MM-DD>-<slug>.md`. No credentials, session identifiers, absolute machine paths, or personal details.
