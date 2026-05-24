# Open Questions

## Car Finder MVP - 2026-05-21 (REVISED iter 2)

### BLOCKING — RESOLVED 2026-05-22

- [x] **Budget range** → **$5k-$12k** (target under $12k). Note: shifts ideal vehicle profile down — Toyota/Honda/Mazda SUVs at this budget will mostly be 2010-2015 with 80k-130k miles. RAV4/CX-5/CR-V/Forester all reachable. Tightens cohort sizes for median-of-cohort price scoring.
- [x] **AWD requirement** → **Weight, low priority**. `drivetrain` weight reduced 0.05 → 0.02. AWD still gets +2 over FWD but barely moves total score.
- [x] **Manual transmission** → **Exclude entirely**. CL fetcher uses `auto_transmission=1` (server-side filter). Scorer drops any manual that slips through.
- [x] **Parking situation** → **Dedicated street spot**. `parking_footprint` weight reduced 0.10 → 0.06 (own spot mitigates size hassle). `insurance_risk` raised 0.05 → 0.08 (street parking = catalytic converter / theft exposure, especially for Prius / older Civic / pre-2022 Kia/Hyundai).

### CONFIRM-LATER (non-blocking, can adjust after MVP ships)

- [ ] **Hybrid preference** — Top-scoring vehicles include hybrids (RAV4 Hybrid, CR-V Hybrid). Any preference or aversion? Default: no preference, hybrids scored on their merits.
- [ ] **Buy vs. keep renting break-even** — At ~$200-280/weekend via Enterprise+CSR, ownership only wins if usage is 2+ weekends/month. Should the tool include a TCO comparison? Default: buy decision assumed, no TCO module in MVP.
- [ ] **Color preference** — Not currently in the rubric. Any strong preferences or aversions? Default: not scored.

### From Architect/Critic review (iter 2)

- [ ] **CarMax feasibility** — M0.5 spike will determine if CarMax is usable at all. Outcome determines whether M2 ships a CarMax fetcher, alternative dealer source, or CL-only MVP. BLOCKING for M2 scope decision.
- [ ] **Alternative dealer source selection** — If CarMax spike fails, which alternative (Cars.com, CarGurus, Autotrader) to sub-spike? Decision deferred to M0.5 outcome.
