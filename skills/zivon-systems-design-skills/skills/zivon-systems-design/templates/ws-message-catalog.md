| Type | Dir (C→S / S→C) | Schema | Ordering/seq | Idempotent? | On loss | Billable? | Notes |
|---|---|---|---|---|---|---|---|
| session.start | C→S | {device, locale, anchor, capabilities} | first | yes | retry | no | |
| audio.chunk | C→S | binary: header+opus frame | seq | n/a | drop old partials | yes (STT s) | |
