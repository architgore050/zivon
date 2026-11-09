| Component | Failure | Detect | Student sees | Auto response | Manual runbook | Data at risk |
|---|---|---|---|---|---|---|
| SSD volume | full | usage metric | lessons still load; new audio unavailable | evict verified cache; pause generation | RB-01 | none if invariant holds |
| Cold provider | unreachable | upload errors | nothing | queue in outbox; stop eviction | RB-03 | un-synced artifacts |
