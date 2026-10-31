# EnergyFlex — AI Prompt History & Usage Disclosure

**Candidate project:** EnergyFlex\
**Recruitment process:** YottaFlex AI — Associate AI Forward Deployed Engineer, Round 2 (72-hour code challenge)\
**AI tool used:** Claude Code (Anthropic), an AI coding assistant working directly in the project folder: it wrote code, ran
commands and made Git commits when asked.\
**Purpose:** Show how the AI assistant was used to build the project, where it did the work, and what the candidate directed,
decided and checked.

------------------------------------------------------------------------

## 1. Transparency note

This document is compiled from the **saved Claude Code session logs** for this project: 2 sessions on 30–31 October 2026
with 25 prompts. The prompts are quoted **verbatim**, typos included, in [Appendix A](#appendix-a--verbatim-prompt-log).
Sections 2–5 summarise what each group of prompts asked for and what was produced. Commit hashes refer to
<https://github.com/saicharan67778/EnergyFlex>.

The assistant's output was treated as work to check, not as proof of correctness. Correctness is shown by the automated
checks in this repository (validation, reproducibility, checksums, tests), and anyone can re-run them.

------------------------------------------------------------------------

## 2. Prompt history by development stage

### 2.1 Building the solution from the challenge brief (prompts 1–2)

**Prompt 1:** the candidate pasted the full Round 2 problem statement, followed by *"plan this accordingly"*.\
**Prompt 2:** *"continue"*

The brief defined everything the solution had to cover:
- the 10 entities, with keys, cardinality, effective dates and lifecycles
- the ID conventions
- the data volume (20 meters, 90 days of 15-minute readings, 2,000 batches) and the fixed seed 20261022
- the 5 required edge cases and a separate ground-truth file
- the validation rules and the CSV/JSON/SQL exports
- reproducibility, the acceptance criteria and the four user roles

**What the AI did:** planned the solution against the brief and implemented it end to end:

| Area | What was built | Where |
|---|---|---|
| Data model & dictionary | 17 tables with primary and foreign keys, an effective-dated meter↔machine bridge, append-only lifecycle events | `energyflex/schema.py`, `docs/DATA_DICTIONARY.md`, `docs/ERD.md` |
| Synthetic generator | Fixed seed with a separate random stream per module; masters → weather → maintenance → batches → minute-level machine states → 15-min meters → labelled injections | `energyflex/generate/`, `energyflex/config.py` |
| Ground truth | Every injected anomaly and waste scenario written to `ground_truth.csv/json`, never read by the analytics | `generate/anomalies.py`, `generate/telemetry.py` |
| Validation | 283 checks: keys, foreign keys, enums, ID formats, date ordering, lifecycles, arithmetic, duplicates, reconciliation | `energyflex/validate.py` |
| Analytics | Quality gate; reconciliation; time-of-use cost (plant-local, DST-aware); kWh/unit intensity; idle, peak and off-shift waste; costed recommendations; evaluation against ground truth | `energyflex/analytics/` |
| Exports & reproducibility | CSV/JSON/SQL, a manifest with SHA-256 checksums, `repro-check` (regenerate twice and compare) | `energyflex/export.py`, `cli.py` |
| Rules & provenance docs | Generation, labelling and detection rules; lawful-use statement | `docs/RULES.md`, `docs/PROVENANCE.md` |
| Tests & dashboard | pytest suite; static dashboard with one view per role | `tests/`, `site/` |

Commits `420a73c` and `1b8e00d`.

**Candidate's role:** supplied the requirements, and asked for a plan covering every point before the build.

### 2.2 Publishing and ownership (prompts 3–10)

The candidate:
- asked for the project to be pushed to GitHub (`saicharan67778`) and hosted on Vercel
- signed in to Vercel themselves (`npx vercel login`)
- asked for every commit to use their own Git identity, with only their name in the GitHub contributor list
- moved the project to a clean repository, `EnergyFlex`
- asked for deployment under their own Vercel account

**What the AI did:** pushed the code and deployed the dashboard. It found the cause of the wrong author name: a machine-wide Git
identity and saved credentials for another user. It then set a repository-local identity and rewrote the existing commits'
authorship. Commits `e945b3f`, `98929c0` and `cddc7d1`.

### 2.3 Dashboard redesign (prompts 11–13)

The candidate asked for UI changes and chose the visual direction: first a Dribbble link, then a screenshot of a dark analytics
dashboard to use as reference.

**What the AI did:** restyled the dashboard in that direction while keeping the project's own data:
- dark theme, sidebar with one view per role
- ring-gauge KPI tiles and ranked bar lists
- stacked area chart, top-recommendations table, acceptance checklist

It checked the result at desktop and phone widths in a headless browser. Commit `a7143d3`.

### 2.4 Understanding the data generation (prompt 14)

The candidate asked how the datasets were created. The AI explained the configuration, the per-module random streams, the order
of the generator modules and how labelled problems are injected. The candidate wanted to be able to explain the design themselves.

### 2.5 Final checks, a packaging defect, and preventing it (prompts 15–19, 22)

1. The candidate asked for final checks, README updates and the submission ZIP.
2. A review then flagged *"Full-scale manifest lists files that are missing from the ZIP"*. The candidate passed this on and
   asked for a fix that would make the error impossible to repeat.

**What the AI did:**
- **Found two causes.**
  - The full-scale JSON and SQL exports are excluded from Git because of their size, so a ZIP built from Git missed them.
  - On Windows, Git and Python rewrote line endings, so file bytes no longer matched the manifest checksums.
- **Fixed both.**
  - `.gitattributes` keeps `data/` and `outputs/` byte-exact.
  - Every file writer now uses LF line endings on any OS.
  - Both datasets were regenerated. Only sizes and checksums changed, not content.
- **Added `python cli.py package`.** It refuses to run with uncommitted changes, adds the manifest files that Git excludes, and
  deletes the ZIP unless all 76 manifest checksums match.
- **Added regression tests**, bringing the total to 27.

Commits `dee09ff`, `54a85fa`, `1b1394c` and `bc44e74`.

### 2.6 Preparing the walkthrough (prompts 20–21)

The candidate asked to lock in the working version and to prepare to explain the architecture, anomaly detection, validation
and recommendations. The AI wrote a briefing with every figure taken from the actual outputs, including the two imperfect
detection scores. It was delivered as a separate PDF for the candidate's own preparation and isn't part of the repository.

### 2.7 Production 404 (prompt 24)

The candidate reported the live site returning *404 NOT_FOUND*. **Cause:** Vercel deploys from the repo root on every push, and
a root `vercel.json` that pointed it to `site/` had been deleted. The AI restored `vercel.json` and confirmed the live
deployment. It also made the KPI tiles fit on one row at laptop widths. Commits `de9ad2c` and `e64107d`.

------------------------------------------------------------------------

## 3. Where AI accelerated the work

1. **Requirement decomposition.** The brief became a single plan covering every required point.
2. **Implementation.** The generator, validation, analytics, exports, tests and dashboard were written by the assistant.
3. **Debugging.** Root causes were found for the wrong Git author, the missing ZIP files and checksum mismatches, and the
   production 404.
4. **Verification.** Tests, validation, reproducibility checks, ZIP checks and live-site checks were run after every change.
5. **Communication.** README, rules, ERD, data dictionary, briefing and this disclosure.

------------------------------------------------------------------------

## 4. Where AI assistance was substantial

**According to the session logs and the Git history, all committed source code and documentation in this repository were
written by the AI assistant, at the candidate's direction.** That covers every module in `energyflex/` (generator, validation,
export, analytics), `cli.py`, `tests/`, `site/` (dashboard), `docs/` and `README.md`. Every commit in the repository was made
during these sessions.

------------------------------------------------------------------------

## 5. What the candidate directed, decided and checked

From the session record, the candidate:

- **Set the requirements.** Supplied the full challenge brief and asked for a plan that covered every point.
- **Made the publishing decisions.** Chose GitHub and Vercel hosting, signed in to Vercel, required their own identity on all
  commits, and moved to a clean repository.
- **Chose the design direction** for the dashboard redesign by supplying the reference design.
- **Acted on review feedback.** Reported the missing-files issue, and asked for a fix that would stop it recurring rather than a
  one-off repair.
- **Reported the production 404** on the live site.
- **Asked how the data was generated** and requested a walkthrough briefing in order to explain the design independently.
- **Asked for an accurate disclosure** of AI use (this document).

Verification steps were run by the assistant and reported to the candidate. They're reproducible with the commands in the
README:

| Check | Result |
|---|---|
| Validation | 283 checks: 275 PASS, 8 EXPECTED_FAIL (injected and labelled), **0 FAIL** |
| Reproducibility | Seed 20261022, 38 files compared, equal row counts, no checksum mismatches |
| Tests | 27 passed, both in the project and from a fresh extract of the ZIP |
| Release ZIP | All 76 manifest files present with matching SHA-256 |

------------------------------------------------------------------------

## 6. Limitations and responsible use

-   The dataset is synthetic. Detection metrics measured against synthetic ground truth do not establish performance on real
    factory telemetry.
-   The dashboard uses generated historical data. It is not a live streaming or production OT integration.
-   Estimated savings are scenario-based estimates, and they depend on the assumptions and source records in the synthetic
    dataset.
-   AI-generated code can be incomplete or incorrect. That's why correctness is shown by checks that anyone can re-run,
    rather than asserted.
-   Any real deployment would need validation against real plant data, the site's meter hierarchy and tariff calendars,
    operational constraints and domain-expert feedback.

------------------------------------------------------------------------

## 7. Walkthrough points for the reviewer

The candidate is prepared to explain:

1.  Why the entities and relationships were modelled this way.
2.  How synthetic data is generated and why the fixed seed matters.
3.  How the five required injected data anomalies are represented and detected.
4.  How a reported anomaly or recommendation can be traced to source records.
5.  What the validation summary and reproducibility report prove, and what they do not.
6.  Why the reported detection metrics are limited to the synthetic dataset.
7.  How AI was used (this document) and how the final behaviour was verified.

------------------------------------------------------------------------

## Appendix A — Verbatim prompt log

Times are IST (UTC+5:30). Prompts are quoted exactly as typed.

| # | When | Prompt (verbatim) |
|---|---|---|
| 1 | 30 Oct 12:47 | *[Pasted the full YottaFlex.ai Round 2 problem statement: business context, objective, actors, workflow rules, entities, ID conventions, 10 generation steps, volume, edge cases, acceptance criteria, evaluation focus, lawful-use guidance]* "plan this accordingly" |
| 2 | 30 Oct 17:44 | "continue" |
| 3 | 30 Oct 17:50 | "https://github.com/saicharan67778/Project.git" |
| 4 | 30 Oct 17:50 | *[Ran in terminal]* `npx vercel login` |
| 5 | 30 Oct 18:19 | "i need to push from my username not Hitesh" — follow-up answer: "i need to push this from my username and y email" |
| 6 | 30 Oct 18:21 | "not nikhilmyneni , saicharan230904@gmail.com and git hub username saicharan67778" |
| 7 | 30 Oct 18:22 | *[Screenshot of GitHub Contributors]* "i just want my name to be there" |
| 8 | 30 Oct 18:24 | *[Screenshot]* "still same thing showing up" |
| 9 | 30 Oct 18:26 | "https://github.com/saicharan67778/EnergyFlex.gitpush to this repo correctly dont make error" |
| 10 | 30 Oct 18:32 | "can ypu delpoy it to vercel" |
| 11 | 31 Oct 14:19 | "wanted to make some changes in the UI" |
| 12 | 31 Oct 14:21 | "https://dribbble.com/shots/27851708-Energy-Trading-Web-App-Design-GridTrade look into this" |
| 13 | 31 Oct 14:26 | *[Screenshot of a reference dashboard design]* |
| 14 | 31 Oct 14:37 | "how id you create the datasets ?" |
| 15 | 31 Oct 14:42 | "ok final checks , complete any updates required to the readme files and create the final zip" |
| 16 | 31 Oct 14:53 | "CSV, JSON and SQL exports for full dataset	Needs correction	Full-scale manifest lists files that are missing from the ZIP" |
| 17 | 31 Oct 15:01 | "update the zip" |
| 18 | 31 Oct 15:03 | "create a new one if there are any changes made" |
| 19 | 31 Oct 15:03 | "so that error wont come again" |
| 20 | 31 Oct 15:17 | "this successful version and prepare to explain the architecture, anomaly detection, validation and business recommendations confidently." |
| 21 | 31 Oct 15:19 | "make this a separate pdf" |
| 22 | 31 Oct 15:22 | "create a new zip after updating , dont include this pdf" |
| 23 | 31 Oct 15:23 | "i need a prompt history on what i gave and what i meant it was to be created" |
| 24 | 31 Oct 15:28 | *[Pasted Vercel error page]* "This page doesn't exist … 404 NOT_FOUND" |
| 25 | 31 Oct 15:40 | *[Pasted a draft of this document]* "i need to push this into git and update the readme file and create new zip" |

**Disclosure:** This document gives an honest account of AI-assisted development, based on the saved session logs and the
project's Git history.
