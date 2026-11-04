# Source catalog: publicly available PDFs for Classes 6-12

Companion of `sources/catalog.json` (machine-readable, the file the pipeline
actually reads). This document is the human-readable research record. A unit
test (`testing/content_factory/unit/test_catalog_sync.py`) fails if the two drift apart.

**Licensing rule (AGENTS.md):** NCERT (officially free) and public-domain /
openly-licensed sources only. No scraping copyrighted textbooks. The pipeline
paraphrases and cites; it never reproduces long extracts.

**Verification status, honestly stated (2026-11-01):** this research was done
from a sandbox that cannot reach `ncert.nic.in` directly. Every NCERT URL below
was confirmed through Google's index of NCERT's own PDF files (title-page text
of the exact file), which is strong but not byte-level proof. The pipeline's
ingest stage therefore re-verifies everything at run time on your machine: it
checks the `%PDF` magic bytes, parses every page, confirms the class label in
the prelims, and fails loudly on any mismatch. Chapter counts are NOT yet
byte-verified and are marked `chapters_verified: false` in the JSON - a 404 on
an unverified entry simply ends that book's chapter list (recorded loudly in
the run output); fix the catalog if the cut is wrong.

## NCERT Science, Classes 6-8 (Curiosity series, NCF-SE 2023)

| Class | Book | Files | License |
|---|---|---|---|
| 6 | *Curiosity - Textbook of Science for Grade 6* | `https://ncert.nic.in/textbook/pdf/fecu1ps.pdf` (prelims), chapters `fecu101.pdf` ... | NCERT terms of use |
| 7 | *Curiosity - Textbook of Science for Grade 7* | `https://ncert.nic.in/textbook/pdf/gecu1ps.pdf` (prelims), chapters `gecu1nn.pdf` | NCERT terms of use |
| 8 | *Curiosity - Textbook of Science for Grade 8* | `https://ncert.nic.in/textbook/pdf/hecu1ps.pdf` (prelims), chapters `hecu1nn.pdf` | NCERT terms of use |

Evidence: title-page text of `fecu1ps.pdf` ("Curiosity, Textbook of Science for
Grade 6"), `gecu1ps.pdf` and `hecu1ps.pdf` ("Curiosity Textbook of Science for
Grade 8") as indexed from ncert.nic.in on 2026-11-01.

## NCERT Science, Classes 9-10

| Class | Book | Files | License |
|---|---|---|---|
| 9 | *Science - Textbook for Grade 9* (2025 edition) | `https://ncert.nic.in/textbook/pdf/iesc1ps.pdf` (prelims), chapters `iesc1nn.pdf` | NCERT terms of use |
| 10 | *Science - Textbook for Class X* | `https://ncert.nic.in/textbook/pdf/jesc1ps.pdf` (prelims), chapters `jesc1nn.pdf` (e.g. `jesc102.pdf` = Ch. 2 Acids, Bases and Salts) | NCERT terms of use |

Evidence: `iesc1ps.pdf` title page reads "Textbook of Science for Grade 9";
`jesc1ps.pdf` prelims read "This textbook of Science for Class X is a
continuation of our attempt in the Class IX Science textbook"; `jesc102.pdf`
content matches Class X Chapter 2. Note the code scheme: the digit after the
subject code is the book/part number, not always the class - which is why the
ingest stage verifies the class label inside each PDF instead of trusting codes.

## NCERT Physics, Classes 11-12

| Class | Book | Files | License |
|---|---|---|---|
| 11 | *Physics Part I - Textbook for Class XI* | `https://ncert.nic.in/textbook/pdf/keph1ps.pdf`, chapters `keph1nn.pdf` (rationalised ed.: Ch. 1-7) | NCERT terms of use |
| 11 | *Physics Part II - Textbook for Class XI* | `https://ncert.nic.in/textbook/pdf/keph2ps.pdf`, chapters `keph2nn.pdf` (Ch. 8-15) | NCERT terms of use |
| 12 | *Physics Part I - Textbook for Class XII* | `https://ncert.nic.in/textbook/pdf/leph1ps.pdf`, chapters `leph1nn.pdf` (Ch. 1-8) | NCERT terms of use |
| 12 | *Physics Part II - Textbook for Class XII* | `https://ncert.nic.in/textbook/pdf/leph2ps.pdf`, chapters `leph2nn.pdf` (Ch. 9-14) | NCERT terms of use |

Evidence: `leph1ps.pdf` / `leph2ps.pdf` confirmed as Class XII Physics Parts
I/II; `leph106.pdf` confirmed as Electromagnetic Induction (Ch. 6, rationalised
numbering). Class 11 codes follow the same scheme and still need a run-time
byte check.

## Openly licensed supplements (non-NCERT)

| Book | Where | License | How the pipeline gets it |
|---|---|---|---|
| OpenStax *High School Physics* | <https://openstax.org/details/books/high-school-physics> | CC BY 4.0 | Manual: download from the page, place at `sources/pdfs/openstax-hs-physics/openstax-hs-physics.pdf` |
| Siyavula / FHSST *Physical Sciences Grade 10* (11 and 12 exist too) | <https://www.siyavula.com/read/science/grade-10> | CC BY | Manual: export the PDF from the reader, place at `sources/pdfs/siyavula-physical-sciences-10/siyavula-physical-sciences-10.pdf` |

Direct PDF links for both sit behind dynamic download buttons, so the catalog
marks them `download: manual`; the pipeline stops with exact placement
instructions if the file is missing. Both are excellent vector-search
supplements for Classes 10-12.

NCERT Exemplar books are a good future addition (also free on ncert.nic.in);
their book codes still need verification, so they are deliberately absent from
v1 rather than guessed.

## NCERT terms of use (summary, from ncert.nic.in)

Textbooks are copyrighted by NCERT. Copies may be downloaded and used as
textbooks or for reference. Republication or redistribution by any individual
or agency is prohibited, and no website may host the files. The Zivon factory
therefore (a) downloads from NCERT only at build time, (b) caches locally,
never redistributes the PDFs (they are gitignored), and (c) outputs paraphrased
study material with citations - never long extracts.

## How to add a source

1. Add an entry to `sources/catalog.json` (see `how_this_file_works` there).
2. Mirror the entry in the tables above.
3. Run `python -m unittest testing.content_factory.unit.test_catalog_sync` to confirm sync.
