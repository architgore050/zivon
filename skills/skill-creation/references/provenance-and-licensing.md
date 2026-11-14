# Provenance and licensing

Skills are creative works with authors and licenses. Discovery makes them look
like free utilities; they are not. This file says what to record, what you may
copy, and what to do when the license is missing.

Not legal advice. For commercial or high-stakes use, have a human review the
actual license text.

## 1. Record provenance before you read the body

For every candidate, capture:

| Field | Why | Example |
|---|---|---|
| Source URL | The page you actually opened | `https://github.com/anthropics/skills/tree/main/skills/skill-creator` |
| Author/org | Attribution and trust | `Anthropic` |
| License | Reuse permission | `See LICENSE.txt in skill folder` |
| Commit SHA or tag | Reproducibility | `main@7bcbef3` or `v1.2.0` |
| Retrieval date | Sources change | `2026-11-14` |
| Version | Upstream version if stated | `metadata.version: 1.0` |
| Content hash | What you installed | `skills-lock.json` SHA-256 |
| Registry entry | Where you found it | `skills.sh/anthropics/skills/pdf` |
| Install count/stars | Weak popularity signal | `229K installs` |

The skills.sh CLI writes the hash for you:

```json
{
  "version": 2,
  "skills": {
    "skill-creator": {
      "source": "anthropics/skills",
      "sourceType": "github",
      "skillPath": "skills/skill-creator/SKILL.md",
      "computedHash": "2d7f889e..."
    }
  }
}
```

Keep that file with the project. It answers "what exactly are we running?" when
the upstream repo changes or disappears.

## 2. Reading, copying, adapting: three different acts

| Act | What it means | License needed? |
|---|---|---|
| **Reading** | You opened it, learned the method, wrote your own expression | No, but cite the inspiration |
| **Copying** | You copied files or substantial text into your repo | Yes, compatible license + notices |
| **Adapting** | You changed/added to the original and distribute the result | Yes, derivative rules apply (attribution, share-alike, notice) |

"Rewrote it in my own words" is not automatically clean: if the structure,
examples, and wording track the original closely, it may still be a derivative.
When in doubt, write from the *method* (ideas) and cite the source, not from the
*expression* (sentences, code, examples).

## 3. License quick reference

| License | Copy | Adapt + distribute | Obligations | Notes |
|---|---|---|---|---|
| MIT | Yes | Yes | Keep copyright + permission notice | Most permissive common |
| BSD-2/3 | Yes | Yes | Keep notice; 3-clause adds no-endorsement | Fine |
| Apache-2.0 | Yes | Yes | Keep NOTICE, license, state changes; patent grant | Good for code |
| CC0 / public domain | Yes | Yes | None | Verify the dedication is valid in your jurisdiction |
| CC-BY-4.0 | Yes | Yes | Attribution, link, indicate changes | Fine for docs |
| CC-BY-SA-4.0 | Yes | Yes | Attribution + **share-alike** on derivatives | Infectious for your bundle |
| GPL-2/3 | Yes | Yes | Source disclosure + same license | Usually incompatible with proprietary distribution |
| AGPL | Yes | Yes | Network-use source disclosure | Strongest copyleft |
| No license | **No** | **No** | None granted | Default copyright: all rights reserved |
| `NOASSERTION` | Maybe | Maybe | Inspect per-folder licenses | GitHub could not classify; do not assume |
| "All rights reserved" | No | No | Contact the author | Common on docs sites |

Rules of thumb:

- **Code** (scripts): MIT/Apache/BSD are safe; GPL/AGPL only if your project is
  compatible.
- **Prose** (references, templates): CC0/CC-BY are safe; CC-BY-SA forces your
  derivative to the same license.
- **Mixed repos**: a repo-level license may not cover vendored folders. Check
  the folder and any `NOTICE`/`THIRD_PARTY_NOTICES`.
- **No license**: you may read for ideas, link to it, and describe it. You may
  not copy files or substantial text. Ask the author if you need more.

## 4. What to do when no license is stated

1. **Look harder**: `LICENSE`, `LICENSE.txt`, `COPYING`, `NOTICE`,
   `THIRD_PARTY_NOTICES`, the README's license section, the package metadata
   (npm/PyPI), the marketplace page.
2. **Check the repo owner's other repos**: a consistent license elsewhere is a
   signal, not a grant.
3. **Check per-folder licenses**: some skill suites license each skill
   separately (OpenAI's repo does exactly this).
4. **If still absent**: treat it as all rights reserved. Do not copy. You can:
   - write your own skill from the method and cite the source,
   - link to the original instead of vendoring,
   - contact the author for permission (record the reply).
5. **Record the decision** in the audit: "no license found on 2026-11-14;
   treated as all rights reserved; wrote original skill; cited method."

Never add a license to someone else's work. Never remove their notice. Never
assume "public on GitHub" means "free to use".

## 5. Attribution template

Put this in the skill's README (or a `NOTICE`/`THIRD_PARTY_NOTICES.md` at the
bundle root):

```markdown
## Provenance

- Derived from: <name> by <author>, <source URL>
- Source revision: <commit SHA or tag>, retrieved <YYYY-MM-DD>
- Source license: <SPDX id or "see LICENSE.txt">
- Changes: <one line per substantive change: renamed, trimmed, retargeted,
  replaced examples, ported to OpenCode>
- Original notice: <copyright line, if the license requires retention>
```

For a verbatim copy, say "copied verbatim" and keep the original license file
next to it. For an adaptation, say "adapted" and list the changes — Apache-2.0
and CC-BY both require indicating changes.

## 6. Registry-specific traps

| Trap | What to check |
|---|---|
| skills.sh install counts | Telemetry, not endorsement; the directory says it cannot guarantee safety or quality |
| Claude plugin marketplaces | A catalog entry is a pointer; the plugin's own license governs |
| npm/PyPI packages | The package license may differ from the repo; check `license` metadata and bundled `LICENSE` |
| Awesome lists | The list's license does not cover the linked projects |
| GitHub `NOASSERTION` | Mixed or custom terms; inspect per-folder |
| Vendored trees | Upstream licenses and notices must be preserved; do not reformat vendored code (it breaks provenance and re-sync) |
| Model-generated skills | Copyright status of AI output is unsettled; the human author's contribution and the source material's license still matter |
| Marketplace "official" badge | Means first-party publishing, not a legal review |

## 7. Licensing your own skill

- Add `license:` to frontmatter (short form, e.g. `MIT`) and a `LICENSE` file in
  the folder when you distribute it.
- If you vendor third-party material, keep a `NOTICE`/`THIRD_PARTY_NOTICES.md`
  and the upstream license text.
- If you adapt, state the changes. This is both a license obligation (Apache,
  CC-BY) and a maintenance aid.
- Do not use a license that conflicts with the host project's distribution model
  (e.g. AGPL code inside a proprietary bundle).

## 8. Provenance is also a security control

Knowing the exact commit you installed lets you:

- diff an update before taking it,
- roll back a compromised version,
- report a malicious skill to the registry with evidence,
- prove what your agent was running when an incident occurred.

That is why the lockfile hash and the retrieval date belong in the audit, not
just in your memory.
