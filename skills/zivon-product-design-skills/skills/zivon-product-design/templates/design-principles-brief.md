# Design principles applied (brief - place at the top of the features doc)

For each (≤10): **Principle** (source) → **rule for Zivon** → **where you'll see it** → **how we test it** → evidence tag.

| # | Principle (source) | Rule for Zivon | Where it shows | Test | Evidence |
|---|---|---|---|---|---|
| 1 | Useful (Rams) | A feature must serve a named learning job | decision log | G1/G2 pass | WEAK-STRONG |
| 2 | As little design as possible (Rams) | Remove until it hurts | removal test | … | |
| 3 | Start still, direct manipulation (PhET) | Sims load static; key object draggable | sim surfaces | novice acts correctly unaided | STRONG |
| 4 | Redundancy/modality (Mayer) | Narration + visuals; text on request | TTS + captions | … | STRONG |
| 5 | Visibility of status (Nielsen) | Mic/audio/loading states always legible | voice dock | … | STRONG |
| 6 | Honest design (Rams) | Disclose AI, MT, limits | copy keys | … | WEAK |
| 7 | Interactive engagement (Hake) | Predict → play → explain | checks, tutor | … | STRONG |
| 8 | Children-first privacy | Minimize, consent, no profiling | data-handling | … | STRONG (law) |
