# Foundations — a six-book series on system design

Written for someone arriving from data engineering or data science rather than
from web backend work.

| # | Book | Covers |
|---|------|--------|
| 00 | Reading path | Index, reading routes |
| 01 | From Pipelines to Systems | Spark/Airflow → system design vocabulary; state; the component card |
| 02 | What a Server Is | Latency to scale; request anatomy; page cache; concurrency; races |
| 03 | How Data Is Stored | Database from an empty file; indexes; B-tree vs LSM; ACID; replication; sharding |
| 04 | How Data Moves | DNS/TCP/TLS/HTTP; APIs; load balancing; queues vs logs; delivery; streaming; resilience |
| 05 | Designing a System, Step by Step | The seven steps; one box → 10M users; two full worked designs |
| 06 | Data and ML Platforms | Platform layers; pipelines; lakehouse; training and feedback loops; serving |

## Build

Each book is a standalone self-contained HTML file assembled from a shared
stylesheet plus a body fragment:

    ./build.sh

- `src/_head.html` — shared design tokens and components (the only stylesheet)
- `src/NN-name.html` — one book body, with a `<!--TITLE:...-->` marker
- `links.json` — cross-book URLs, substituted into `__L0__`…`__L6__` at build time

To change cross-links, edit `links.json` and rebuild. Output files are written
to this directory and published as separate artifacts.
