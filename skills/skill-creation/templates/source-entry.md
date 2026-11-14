# Source entry — `<source name>`

Copy this block for one catalog row. Keep the fields stable so the Markdown
table and the CSV stay in sync.

```yaml
id: SRC-000
source: ""
url: ""
type: official | registry | marketplace | awesome | community | package | docs
good_for: ""
access_method_tested: ""        # API | CLI | CURL | FETCH | PW | PW-MCP | SEARCH | GH | listed only
auth_rate_limits: ""
license_provenance: ""
last_checked: "YYYY-MM-DD"
quality_signal: ""              # numbers, stars, installs, version, update date
caveats: ""
```

## What makes a row acceptable

- **URL** resolves on the date recorded. If it redirects, record the final URL.
- **Access** names the exact method and the observed status ("API 200",
  "CURL 403", "PW 200, 1 KB shell"). "Works" alone is not evidence.
- **License** is the source's license, not the license of content it links to.
- **Quality signal** is a number or a dated fact, not an adjective. "Popular"
  is not a signal; "194,238 stars, pushed 2026-11-06" is.
- **Caveats** includes the failure mode, the block, or the reason not to trust
  it. A row without a caveat is suspicious.

## CSV row

The same data as one CSV line:

```csv
SRC-000,source name,https://example.com,registry,what it is good for,API 200,no auth,CC-BY-4.0,2026-11-14,quality signal,caveat
```

Quote fields containing commas. The catalog CSV uses eleven columns:
`source_id,source,url,type,good_for,access_method_tested,auth_rate_limits,license_provenance,last_checked,quality_signal,caveats`.
