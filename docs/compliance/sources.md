# Compliance source register

One row per source this folder relies on. `S-NN` ids are cited from
[`cbse-exam-content.md`](cbse-exam-content.md) and
[`decision-log.md`](decision-log.md). A source that was blocked, partial, or
secondary is labelled as such rather than dropped — the next agent should not
re-discover the same wall.

**Retrieval date for every row: 2026-11-15** (single research session).
No paywalls, no logins, no credentials were used. `robots.txt` was checked
before fetching: `cbse.gov.in` serves no `robots.txt` (404), `cbseacademic.nic.in`
answers `robots.txt` with a generic "inaccessible" page (no `Disallow`), and
`indiankanoon.org` allows every document cited here.

| ID | Source | URL | Fetch status | What it establishes |
|---|---|---|---|---|
| S-01 | **The Copyright Act, 1957** (14 of 1957), consolidated text, Copyright Office, Government of India — 57 pp. PDF | <https://copyright.gov.in/documents/copyrightrules1957.pdf> | 200, 956,958 bytes, SHA-256 `8c70b510…`; **TLS chain incomplete** (server omits the intermediate), fetched with verification disabled — see "Fetch caveats" | ss. 2(k), 2(o), 13, 14, 17, 28, 28A, 51, 52 in full |
| S-02 | **India Code record** for the Copyright Act, 1957 (Act ID 195714) | <https://www.indiacode.nic.in/handle/123456789/1367> | Partial: the index answered through the search layer; three direct fetches returned `504`/timeout. Section text verified against S-01 | Act identity, enactment date, section list (cross-check only) |
| S-03 | **CBSE Website Policy** (Website Policy, Copyright Policy, Hyperlink Policy), PDF, 196,107 bytes, SHA-256 `299f6d11…`, file dated 2023-03-13 | <https://www.cbse.gov.in/cbsenew/documents/WEBSITE_POLICY.pdf> | 200 | The only public CBSE statement that permits reproduction: "Material featured on this site may be reproduced free of charge in prescribed format or media without requiring specific permission", subject to accuracy, non-derogatory/non-misleading context, and prominent source acknowledgement; excludes explicitly-marked third-party material; hyperlink policy asks prior permission |
| S-04 | **CBSE — Previous Years' Question Papers** index (Class X and XII; main + compartment, 2022–2026) | <https://www.cbse.gov.in/cbsenew/question-paper.html> | 200, 975,148 bytes | Official public release of past papers exists; five-year window for Class XII Physics is 2022–2026 |
| S-05 | **CBSE — Marking Scheme of Last Years** index | <https://www.cbse.gov.in/cbsenew/marking-scheme.html> | 200, 624,765 bytes | Official marking schemes for past papers are published on the same site, 2022–2026 |
| S-06 | **CBSE Class XII Physics 2026 question paper** (ZIP of all sets, 12,491,401 bytes, SHA-256 `23c665ad…`) | <https://www.cbse.gov.in/cbsenew/question-paper/2026/XII/Physics.zip> | 200; 16 PDFs, sets 55/1/1 … 55/5/3 plus 55(B) | Papers are published as multiple sets; the paper itself carries **no copyright notice**; bilingual (Hindi/English) cover; metadata must capture the set code |
| S-07 | **CBSE Class XII Sample Question Paper & Marking Scheme, 2026–27** index | <https://cbseacademic.nic.in/SQP_CLASSXII_2026-27.html> | 200, 48,215 bytes | SQPs and MS are published in English and Hindi (`Physics-SQP.pdf` / `Physics-SQP_hi.pdf`); hosted on `cbseacademic.nic.in`, not `cbse.gov.in` |
| S-08 | **CBSE Class XII Physics (042) Sample Question Paper 2026–27**, PDF, 841,132 bytes, SHA-256 `ab406f5a…` | <https://cbseacademic.nic.in/web_material/SQP/ClassXII_2026_27/Physics-SQP.pdf> | 200 | Cover page names CBSE and the session; **no copyright or reuse notice inside the file** |
| S-09 | **CBSE Class XII Physics (042) Marking Scheme 2026–27**, PDF, 894,203 bytes, SHA-256 `7aec844a…` | <https://cbseacademic.nic.in/web_material/SQP/ClassXII_2026_27/Physics-MS.pdf> | 200 | Marking scheme is a separate published artefact; no reuse notice inside |
| S-10 | **CBSE notification 132/2026** — Sample Question Papers for Classes X & XII, 2026-27 (dated 2026-09-21), PDF, 839,124 bytes, SHA-256 `89b341d0…` | <https://cbseacademic.nic.in/web_material/Notifications/2026/132_Notification_2026.pdf> | 200 | CBSE's own framing: SQPs "provide a broad template and serve as a guide", give "a broad understanding of the question paper design", and "need to be used for classroom teaching and learning activities" |
| S-11 | **CBSE Academic homepage** footer + policy-page probes | <https://cbseacademic.nic.in/> | 200, 61,928 bytes; footer reads "© 2026 CBSE Academic Unit"; `/copyright.html`, `/terms.html`, `/website_policy.html`, `/disclaimer.html` all `404` | No published reuse policy for the subdomain that hosts the SQPs — the S-03 policy says "this Portal" (cbse.gov.in) |
| S-12 | **CBSE Public Advisory, 20 Aug 2018** — commercial websites creating CBSE look-alike pages, PDF, 251,262 bytes, SHA-256 `5f2ae42f…` | <https://www.cbse.gov.in/cbsenew/Examination_Circular/2018/10_CIRCULAR.pdf> | 200 | CBSE treats look-alike commercial surfaces and logo use as a live enforcement issue |
| S-13 | **CBSE Public Advisory, 12 Feb 2024** — misuse of CBSE name/logo on X, PDF, 176,473 bytes, SHA-256 `a971c99d…` | <https://www.cbse.gov.in/cbsenew/documents/Public_Advisory_13022024.pdf> | 200 | Continuing name/logo enforcement; supports the no-affiliation rule |
| S-14 | **Institute of Chartered Accountants of India v. Shaunak H. Satya**, Supreme Court of India, 2011-09-02, (2011) 8 SCC 781 | <https://indiankanoon.org/doc/1548289/> | 200 | Question papers, model answers and evaluation instructions are copyrightable literary works; examining bodies take assignments from paper-setters; papers are disclosed to everyone at the exam and published after it |
| S-15 | **Agarwala Publishing House v. Board of High School & Intermediate Education, U.P.**, Allahabad High Court, 1966-04-19 | <https://indiankanoon.org/doc/1183558/> | 200 | Examination papers are "original literary works"; absent assignment, copyright stays with the paper-setters; "Government work" under s. 2(k) requires the work to be made under the *direction or control* of Government — a board's papers did not qualify |
| S-16 | **Rupendra Kashyap v. Jiwan Publishing House (P) Ltd.**, Delhi High Court, 1996-07-01 (interim order 1993-12-16) | <https://indiankanoon.org/doc/134584/> | 200 | CBSE held to be a "public undertaking" and first owner of copyright in its question papers; a commercial publisher's reproduction of past papers was enjoined; fair dealing under s. 52(1)(a)(i) rejected because the defence protects the student, not a publisher selling copies |
| S-17 | **Ravinder Singh & Sons v. Evergreen Publications (India)**, Delhi High Court, 2018-01-10 | <https://indiankanoon.org/doc/97547022/> | 200 | Near-verbatim reproduction of ICSE question papers with answers was restrained; a genuinely transformative guide may be fair |
| S-18 | **The Chancellor, Masters & Scholars of the University of Oxford v. Rameshwari Photocopy Services**, Delhi High Court (Division Bench), 2016-12-09, RFA(OS) 81/2016 | <https://indiankanoon.org/doc/114459608/> | 200 | s. 52(1)(i) read purposively for teacher/pupil course packs; fairness measured by "extent justified by the purpose"; the court stressed that **profit** is what separates publication from in-course reproduction |
| S-19 | **CBSE UPDATE — Compendium of CBSE Circulars, Vol. II**, PDF, 10,102,448 bytes, SHA-256 `adbe1525…` | <https://cbseacademic.nic.in/web_material/CBSE_Update(Compendium_of_CBSE%20Circulars)Vol-II.pdf> | 200 | A CBSE-published book states "The rights reserved — No part of this publication may be reproduced … without prior permission of the copyright owner", showing CBSE does not apply one permissive rule to everything it publishes |
| S-20 | **Copyright Office — About Us** (list of amendments to the Act) | <https://copyright.gov.in/Aboutus.aspx> | 200 (same TLS caveat as S-01) | The Act was amended in 1983, 1984, 1992, 1994, 1999 and 2012; the 2012 amendment is the most substantial. Used to date the consolidated text |
| S-21 | **CBSE Academic — Competency-Based Education / question banks** | <https://cbseacademic.nic.in/cbe/assessment.html> | 200, 60,482 bytes | Item banks are partner-built: "developed in collaboration with Sri Aurobindo Society and ACER", "with British Council and AlphaPlus", and "by Educational Initiatives in Collaboration with CBSE" |

## Secondary or partial sources (used only for leads, never as the sole basis)

| ID | Source | Why it is secondary |
|---|---|---|
| X-01 | SpicyIP case note on the DU Photocopy Division Bench judgment (2016) | Commentary; the holding is taken from S-18 |
| X-02 | SpicyIP note on the ICSE/ISC guide-book injunction (2016) | Commentary; the holding used here is from S-17 |
| X-03 | Search-index snippets of the 2026 DPIIT copyright-policy debate | Policy commentary; no enacted change to s. 52 located. Watch item only |

## Fetch caveats (recorded, not hidden)

- `copyright.gov.in` presents an **incomplete TLS certificate chain** (leaf only,
  no intermediate). `curl` verification fails with `unable to get local issuer
  certificate`. The PDF was retrieved with verification disabled and its SHA-256
  recorded above; treat it as a public document with transport integrity
  unverified, not as a signed artefact.
- `indiacode.nic.in` is reachable but slow: the handle page returned `504` or
  timed out on direct fetches. Section text was read from S-01 instead; India
  Code is cited only for the Act's identity.
- `cbseacademic.nic.in` publishes **no** copyright/terms page (four probes,
  all 404). That absence is itself a finding (F-06), not an oversight in this
  research.
- No attempt was made to access CBSE's internal portals (Pariksha Sangam,
  SARAS, e-affiliation). They are login-gated and out of scope.
- No attempt was made to bypass any paywall, CAPTCHA, or login.
