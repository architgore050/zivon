# Exam-content notices — exact copy

Approved user-facing copy for exam-style surfaces, plus the placeholder contract
and the removal path. Copy here is **normative**: the publish gate rejects a
rendered notice that differs from these strings or leaves a `{{…}}` token
unresolved.

Languages: **English and Hindi only** for CBSE-style surfaces (FEATURE-MAP #3).
No Hinglish on these notices. Voice: plain, short, no legalese, no apology.

| Notice | Used on | Mode |
|---|---|---|
| `N-01` | Any page or series of generated exam-pattern questions | `blueprint_only` and `attributed_verbatim` |
| `N-02` | Under each verbatim question or marking-scheme item | `attributed_verbatim` only |
| `N-03` | Series intro / top of a past-year series | `attributed_verbatim` only |
| `N-04` | Under a verbatim marking-scheme answer | `attributed_verbatim` only |
| `N-05` | Takedown / rights-request page, linked from every exam surface | both |

## Placeholder contract

<!-- placeholder-contract:start -->

| Placeholder | Resolved from | Format | Required |
|---|---|---|---|
| `{{contact_email}}` | runtime config `ZIVON_COMPLIANCE_EMAIL`; must be a monitored mailbox | `compliance@example.com` | always for `N-03`, `N-05` |
| `{{source_board}}` | constant | `CBSE` | `N-02` |
| `{{class_num}}` | `item.source_ref.class_num` | `10` or `12` | `N-01`, `N-02` |
| `{{subject}}` | `item.source_ref.subject` | `Physics` or `Science (Physics section)` | `N-01`, `N-02` |
| `{{subject_code}}` | `item.source_ref.subject_code` | `042` | `N-02` |
| `{{paper_year}}` | `item.source_ref.year` | `2024` | `N-02`, `N-04` |
| `{{paper_type}}` | `item.source_ref.paper_type` mapped to a label | `main exam`, `compartment exam`, `sample paper` | `N-02`, `N-04` |
| `{{paper_ref}}` | composed from `set_code` and `question_no` | `Set 55/1/1, Question 23` (board paper) / `Question 12` (sample paper, marking scheme) | `N-02` |
| `{{source_url}}` | `item.source_ref.source_url` | `https://www.cbse.gov.in/...` | `N-02` |
| `{{series_name}}` | series display name | `Past-year questions (CBSE)` | `N-03` |

<!-- placeholder-contract:end -->

Resolution rules: `paper_type` is the type of the *paper* the item came from and
maps `main → "main exam"`, `compartment → "compartment exam"`, `sample →
"sample paper"`. A marking-scheme item keeps its paper's type and is identified
by `source_type: verbatim_cbse_ms`, not by a `paper_type`. `paper_ref` drops the
`Set …` clause when `set_code` is null. Never render a raw enum, a slug, or an
empty clause.

## N-01 — generated exam-pattern notice

**EN**

```text
These practice questions are written by Zivon in the style of the CBSE Class {{class_num}} {{subject}} paper. They are not CBSE questions. Zivon is not affiliated with or endorsed by CBSE.
```

**HI**

```text
ये अभ्यास प्रश्न ज़ीवोन द्वारा CBSE कक्षा {{class_num}} {{subject}} के पेपर की शैली में लिखे गए हैं। ये CBSE के प्रश्न नहीं हैं। ज़ीवोन CBSE से संबद्ध नहीं है और CBSE इसका अनुमोदन नहीं करता।
```

## N-02 — verbatim item source line

**EN**

```text
Source: {{source_board}} Class {{class_num}} {{subject}} ({{subject_code}}), {{paper_year}} {{paper_type}} paper, {{paper_ref}}. Reproduced unchanged from the paper published by CBSE at {{source_url}}. Zivon is not affiliated with or endorsed by CBSE.
```

**HI**

```text
स्रोत: {{source_board}} कक्षा {{class_num}} {{subject}} ({{subject_code}}), {{paper_year}} {{paper_type}} पेपर, {{paper_ref}}। CBSE द्वारा {{source_url}} पर प्रकाशित पेपर से बिना किसी बदलाव के प्रस्तुत। ज़ीवोन CBSE से संबद्ध नहीं है और CBSE इसका अनुमोदन नहीं करता।
```

## N-03 — verbatim series intro

**EN**

```text
{{series_name}} uses questions from question papers published by CBSE. Every question shows its source. Zivon is an independent practice platform: this is not an official CBSE paper, and Zivon is not affiliated with or endorsed by CBSE. If you believe an item should not be here, write to {{contact_email}} and we will review it.
```

**HI**

```text
{{series_name}} में CBSE द्वारा प्रकाशित प्रश्न-पत्रों के प्रश्न हैं। हर प्रश्न के साथ उसका स्रोत दिया गया है। ज़ीवोन एक स्वतंत्र अभ्यास मंच है: यह CBSE का आधिकारिक पेपर नहीं है, और ज़ीवोन CBSE से संबद्ध नहीं है या उससे अनुमोदित नहीं है। यदि आपको लगता है कि कोई प्रश्न यहाँ नहीं होना चाहिए, तो {{contact_email}} पर लिखें; हम उसकी समीक्षा करेंगे।
```

## N-04 — verbatim marking-scheme attribution

**EN**

```text
The answer shown is reproduced from the CBSE marking scheme for the {{paper_year}} {{paper_type}} paper. The explanation and any extra working are Zivon's own and are not part of the official marking scheme.
```

**HI**

```text
दिखाया गया उत्तर CBSE की {{paper_year}} {{paper_type}} पेपर की मार्किंग स्कीम से लिया गया है। व्याख्या और अतिरिक्त हल ज़ीवोन के अपने हैं और आधिकारिक मार्किंग स्कीम का हिस्सा नहीं हैं।
```

## N-05 — takedown / rights request

**EN**

```text
If you are a rights holder and believe content on Zivon infringes your rights, write to {{contact_email}} with the page URL, the question or item, and your relationship to the work. We will acknowledge within 2 working days and hide or remove the item while we review it.
```

**HI**

```text
यदि आप किसी कृति के अधिकार धारक हैं और आपको लगता है कि ज़ीवोन पर सामग्री आपके अधिकारों का उल्लंघन करती है, तो {{contact_email}} पर पृष्ठ का URL, प्रश्न और कृति से अपना संबंध लिखकर भेजें। हम 2 कार्य-दिवसों में पुष्टि देंगे और समीक्षा के दौरान उस प्रश्न को हटा देंगे या छिपा देंगे।
```

## Wording rules

| Surface | Allowed | Forbidden |
|---|---|---|
| Generated series | "exam-pattern practice", "built to the CBSE Class {{class_num}} {{subject}} paper pattern" | "PYQ", "previous year question", "past paper" |
| Verbatim series | "Past-year questions (CBSE)", "CBSE question paper, {{paper_year}}, {{paper_ref}}" | "official", "exact CBSE paper", "actual board paper", "CBSE-approved", "in partnership with CBSE" |
| Branding anywhere | "Zivon" as the product name; "CBSE" in a factual sentence | CBSE logo, CBSE in the Zivon logo/domain/app name, any implied endorsement |

## Removal path

Public copy: `N-05`. Linked from the footer of every exam surface and from the
series intro, and reachable without JavaScript.

Internal steps (P3 owns the implementation; the register is in
[`decision-log.md`](decision-log.md#takedown-register)):

1. Log the request (date, channel, item ids/URLs, requester relationship).
2. Acknowledge within **2 business days**.
3. Hide the item(s) the **same day** — no waiting for the review to finish.
4. Decide within **5 business days**: remove permanently, or restore with a
   written reason.
5. If removed: purge the question bank, every series manifest, the CDN/cache,
   and the sitemap entry if the page is now empty.
6. Record the outcome in the takedown register.

Takedown is a **mitigation, not a statutory safe harbour**: India has no
DMCA-style notice-and-takedown immunity for a publisher (`CQ-08`). Do not
describe it as one in public copy.

## Rendering rules

- Server-rendered/static HTML; visible with JavaScript disabled.
- Never inside a collapsed accordion, tooltip, or modal. Place `N-01`/`N-03` at
  the end of the series intro and again at the page footer; place `N-02`/`N-04`
  directly under the item they describe.
- Present in the print view and in any text export of the page.
- One `N-01` or `N-03` per page; `N-02`/`N-04` are per item.
- English and Hindi only. Do not machine-translate these strings; the Hindi copy
  above is the approved text.
- An unresolved `{{…}}` token is a **publish error**, not a blank.
- Record the notice version in the publish manifest so an audit can tell which
  copy shipped.
