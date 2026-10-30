# Review protocol (run on every render)

Reviewer = you first, the user second. Cite timestamps for every finding.

## A. Machine/model pass (do this if you can watch video or inspect frames)
1. Secrets sweep: check frames at the start, every key moment, and at least every 2 s in screen-recording segments.
   Look for API keys, tokens, .env content, emails, private URLs, tabs, notification banners, other people's
   faces or names, and any minor. Any hit = FAIL; report timestamp and fix (crop, blur-to-solid-fill, or reshoot).
2. Hook check: what is in frames 0-3 s? Does text plus picture alone communicate the promise?
3. Pacing count: list the cut times; compute seconds between visual changes per beat; flag any gap over 8 s and any
   stretch of cuts under 1.2 s that adds noise.
4. Caption check: spelling, number accuracy, timing drift, emphasis words (one per phrase), safe-zone placement.
5. Peak check: is the result on screen long enough to read (1.5 s minimum)? Is it the loudest/busiest moment?
6. Audio check: loudness consistent, no pops at joins, music not masking voice.
7. Ending check: no cut-off sentence, no dead air over 300 ms, clear last frame (text card or loop).
State plainly whether you watched it in motion or inspected stills.

## B. Human pass (ask the user to do these; they take 5 minutes)
- Audio-off test: can you follow the story from picture and captions alone? (Hitchcock test)
- Black-and-white test (desaturate): does the energy still build and peak visually?
- Third-view test: if a segment feels weaker on the third watch, cut it.
- Stranger test: have someone who has not seen the raw footage watch it next to you. Watch their face. Where they
  look away is your re-cut target.
- Phone test: watch at arm's length on a phone, not on a monitor.

## C. Verdict format
SHIP / FIX (numbered list, timestamp + problem + fix) / RESHOOT (what is missing). End with the single change that
would improve it most. Limit yourself to 2 revision rounds before asking the user whether it is good enough.
