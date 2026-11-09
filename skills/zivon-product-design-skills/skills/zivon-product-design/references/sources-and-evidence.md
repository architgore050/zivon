# Sources and evidence (dated 7 Nov 2026)

Status: **V** = page opened/read in this session; **S** = surfaced in search results only (snippet-level); **C** = canonical work cited from memory, not re-fetched. Re-verify C/S items before quoting. Nothing below is reproduced verbatim; all rules are paraphrased.

## Design doctrine
| Source | Status | Supports |
|---|---|---|
| Vitsœ, "Good design" - Dieter Rams's ten principles (vitsoe.com/gb/about/good-design). CC BY-NC-ND 4.0 | V (list + licence note) | `01` A |
| Rams, *Less but better* (1995) | S (referenced) | `01` A |
| Nielsen, "10 Usability Heuristics for UI Design" (nngroup.com/articles/ten-usability-heuristics) - 1994 factor analysis of 249 problems; unchanged since | V (summary pages) | `01` B |
| NN/g, "How to conduct a heuristic evaluation" | S | `08` B |
| Norman, *The Design of Everyday Things* | C | `01` C |
| Shneiderman, "Eight Golden Rules" | C/S | optional cross-check |

## Learning science
| Source | Status | Supports |
|---|---|---|
| Adams, Reid, LeMaster, McKagan, Perkins, Dubson, Wieman (2008), *A Study of Educational Simulations Part II - Interface Design*, J. Interactive Learning Research 19(4) - phet.colorado.edu/publications/archive/PhET%20interview%20Paper%20Part%20II.pdf. >200 interviews, 89 students | **V (read in full)** | `01` E, `04` all |
| Adams et al. (2008), *Part I - Engagement and Learning*, 19(3) | S | `01` E |
| Perkins et al. (2006), *PhET: Interactive Simulations for Teaching and Learning Physics*, The Physics Teacher 44 | S | context |
| Mayer, *Multimedia Learning* (2nd ed. 2009, 3rd ed. 2020) - principle lists via university summaries (OSU, Dartmouth, Emory, JSU, FutureLearn PDF) | V (summaries) | `01` D, `05` |
| Clark & Mayer (2003), *E-learning and the Science of Instruction* (coherence/contiguity, cited by PhET) | C | `01` E |
| Hake (1998), *Interactive-engagement vs traditional methods*, Am. J. Phys. 66, 64 - 62 courses, N=6542; IE gain ≈0.48 vs ≈0.23 | V (abstract/summaries) | `01` F |
| Hake, *Lessons From the Physics-Education Reform Effort* (arXiv physics/0106087) | V (snippets) | `01` F |
| PhysPort, "Ten results of physics education research" (McKagan) | V (snippets) | `01` F |
| Hestenes, Wells, Swackhamer (1992) Force Concept Inventory | S/C | misconception-targeted checks |
| Bjork - desirable difficulties; retrieval practice (general literature) | C | `04` §3 |
| Sweller - cognitive load theory | C | underlies Mayer/PhET claims |

## Voice and conversation design
| Source | Status | Supports |
|---|---|---|
| Google Conversation Design guidelines; Amazon Alexa design guide (referenced by practitioner pages) | S | `01` G, `05` |
| Pearl (2016), *Designing Voice User Interfaces* | S (referenced) | `01` G |
| Practitioner syntheses: Rasa "13 rules", UXdesign.cc "Nielsen's heuristics for voice", ServiceNow Horizon conversation guide | S/V (snippets) | `01` G |

## Law and data
| Source | Status | Supports |
|---|---|---|
| India DPDP Act 2023; DPDP Rules 2025 (MeitY, notified 13-14 Nov 2025; G.S.R. 846(E)) | **Primary not read.** Secondary: Biometric Update, Mondaq, Sansa Legal, ORF, DSK Legal, India Briefing, Anantam IAS | `06` §4 |
| Key secondary claims: verifiable parental consent for <18; tracking/behavioural monitoring/targeted ads to children barred (§9(3)) with purpose-limited exemptions incl. educational institutions; 18-month phasing (≈14 May 2027); 72 h breach notice; 90-day response | S/V (snippets) | `06` §4, T5 |
| WCAG 2.2 (W3C) - 2.5.7 dragging alternatives, 2.5.8 target size (24 px), 2.4.11 focus not obscured | C - verify at w3.org/TR/WCAG22 | `06` §2 |

## Existing agent skills reviewed (vendored where licence allows; see `../../vendored/`)
| Repo | Licence | Used |
|---|---|---|
| product-on-purpose/pm-skills (commit 9b920db, 3 Nov 2026) | Apache-2.0 | 12 skills in product bundle; develop-adr + measure-instrumentation-spec in systems bundle |
| Jeffallan/claude-skills (commit 078a25c, 30 Oct 2026) | MIT | feature-forge (product); architecture-designer, api-designer, postgres-pro, websocket-engineer, sre-engineer, secure-code-guardian, fastapi-expert, database-optimizer (systems) |
| vgrss/acumen, nimbalyst/skills, alirezarezvani/claude-skills, tomas-u/claude-skills, travisjneuman/.claude | not reviewed in depth / licence not checked | not vendored; candidates if more breadth is wanted |

## Known weaknesses of this evidence base
- PhET findings come from US university students; transfer to Indian Class 9-12 learners is plausible but `[ASSUMPTION]` - the repo's kid tests (Gate B) are the right place to confirm.
- Mayer's redundancy principle has boundary conditions (learner pacing, text length, learner language proficiency); do not apply it as an absolute (see T1).
- Voice-UI guidance is practitioner-grade; no strong learning-outcome RCTs for voice tutors in this context were reviewed.
- DPDP analysis is from secondary summaries and is not legal advice.
