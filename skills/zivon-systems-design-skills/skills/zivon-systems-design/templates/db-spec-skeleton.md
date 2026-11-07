# Database specification - Zivon
1. Scope, engine ADR, phase plan
2. Entity list with INF/ENT? traceability
3. ER diagram (Mermaid)
4. Per-table spec: purpose · columns (name,type,null,default,source,PII class,retention) · keys · constraints · indexes · partitioning · volume · SoR/tier · deletion path
5. Access-pattern table (query, frequency, latency, index)
6. Retention and deletion matrix
7. Migration plan (expand/contract, rollback, CI)
8. Seed/reference data
9. Traceability CSV (column ↔ INF ↔ NEED)
10. Open questions and assumptions
