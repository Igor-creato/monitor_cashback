# Time-Series Storage Decision for Price History

## Current State

`price_history` is stored in MariaDB. The existing FastAPI service writes price
points to the MariaDB table and serves history/chart data from the same table.

This note does not introduce a storage migration. It records the decision to keep
MariaDB now while adding a repository boundary so a future TimescaleDB writer can
be introduced without changing public API contracts.

## When MariaDB Is Enough

MariaDB is enough for the current MVP when:

- the service tracks up to 10k products;
- history retention is around 30 days;
- chart reads stay moderate and mostly target recent history;
- aggregation needs remain simple: raw points, daily points, min/avg/max/current.

For this shape, the operational cost and complexity of a second database are not
justified.

## When TimescaleDB Is Needed

TimescaleDB becomes a better fit when the workload grows into true time-series
scale:

- millions of price points;
- complex aggregations over large windows;
- long retention beyond the short MVP window;
- heavy chart traffic where MariaDB chart reads become a bottleneck.

At that point, hypertables, time-based partitioning, and continuous aggregates
can reduce query cost and make retention policy easier to manage.

## Later Migration Path

The future migration path should be incremental:

1. Create a Timescale writer behind the existing price history repository
   interface.
2. Enable dual write from the fetch pipeline to MariaDB and TimescaleDB.
3. Verify row counts, recent points, chart summaries, and retention behavior
   between both stores.
4. Switch chart reads to the Timescale-backed repository after verification.
5. Clean up the old MariaDB read path only after production confidence is high.

## Why We Are Not Migrating Now

The service already has a working MariaDB schema and tested chart endpoints.
Current scope is MVP-scale price history with short retention. Migrating storage
now would add infrastructure, operational risk, and verification work without a
current performance requirement.

Therefore, this change only adds the adapter boundary and keeps MariaDB as the
active storage engine.
