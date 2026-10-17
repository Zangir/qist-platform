# STATUS

Updated: 2026-10-12 · Iterations 1–11

## Iteration 11 — invited members, claim flow, Hugging Face backend, 2026-10-17

Decisions D-71…D-74.

- **Claimable accounts.** The admin imports the member spreadsheet (Invitations tab): preview, then create hidden unclaimed accounts and download personal links once. Each person opens their link, reviews the prepared profile, sets a password, accepts the terms and chooses whether to be listed (not pre-ticked). Decline deletes the record and remembers the address (hashed).
- **The 468 imported researchers are no longer public** (kept locally in `data/private/`). The public directory, map and home counts therefore show the 29 curated members until people claim their profiles.
- **Backend for Hugging Face:** `deploy/huggingface/` (Dockerfile, build script, guide). The app refuses to start without persistent storage.
- **Tests:** 34 backend tests, 41 browser checks for the claim flow (also run against the assembled Space folder in a clean environment).

## Iteration 10 — one Opportunities page, member profiles, positions, new home, 2026-10-16

Build `2026-10-16a`. Decisions D-65…D-70.

- **One page instead of two.** My feed and Opportunities are merged (D-65): curated calls with checked eligibility and its reasons (D-66), daily grants and vacancies, positions posted by members, members' papers. The worldwide articles feed is switched off.
- **Members post positions** from their labs (title, lab, who it is for, description, required link, deadline). Backend: publishes at once; static: goes to a curator.
- **Profile builder:** ORCID (checksum, public API), CV (PDF/DOCX/paste, rules not a model), photo, fields, keywords, links, papers by DOI/ORCID/manual; edit, download my data, delete account. Directory and map show photos.
- **Members database** in the admin panel with CSV export and moderation. Backend gained profile, positions, papers, CV-text and admin endpoints; the default admin password is gone.
- **Home:** new hero with the globe picture, a search box, four pillars, a large numbers band, the fit check moved under "Closing next".
- **Tests:** 67 Python, 118 + 99 + 43 browser checks.
- **Not done / needs you:** the API is not deployed (`render.yaml` is ready), so on the live site profiles and positions are still requests to the team; Kazakh and Russian strings are unreviewed (B-35); the hero picture carries five people's photographs from the design brief.

## Iteration 9 — My feed: daily grants, vacancies and articles, 2026-10-12

Build `2026-10-12a`. Decisions D-59…D-64.

- **Three worldwide feeds**, built once a day by `pipeline/` (GitHub Actions `feeds.yml`) into `data/feeds/`.
  Articles: arXiv, bioRxiv, medRxiv and ~45 leading journals via Crossref. Vacancies: jobs.ac.uk (by discipline
  and the PhD section), Nature Careers, Inside Higher Ed. Grants: UKRI, NSF, Grants.gov, fundsforngos.
- **Not yet verified live:** the EU Funding & Tenders portal (Horizon Europe, ERC, MSCA). The parser follows the
  documented response shape and passes tests on a hand-written fixture, but `ec.europa.eu` hosts reset every
  connection from the environment this was built in. `data/feeds/meta.json` records per source whether it worked;
  the first scheduled run settles it. Grants.gov was reachable on a later attempt and its parser matched the live shape.
- **Deterministic parsing.** Fields come from `data/taxonomy.json` (one vocabulary for Python and the browser) plus
  the source's own category (arXiv, bioRxiv, jobs.ac.uk discipline); stage from the title; country from a gazetteer;
  non-research roles (deans, managers, clinicians) are dropped.
- **Matching per reader** (`assets/js/feed.js`, `feed.html`): fields, keywords, career stage, countries for
  vacancies. Wrong-stage vacancies are hidden, not demoted. Each card says why it matched; no percentages (D-62).
  Daily: "new since your last visit", today's picks, save / not interested. Profile in the browser, and on the
  account when signed in (`/api/me/feed-profile`). A short "Today for you" card on `profile.html`.
- **Tests:** `pipeline/tests` (parsers on captured live fixtures, rules, retention, failure isolation, a quality
  gate on the published feeds), `backend/tests`, and two browser suites (`e2e_feed.py`, `e2e_feed_backend.py`).
- **Known gaps:** no e-mail digest yet (the page is the daily view); Kazakh/Russian strings for the feed are not
  reviewed by a native speaker (B-35); EURAXESS and Academic Positions block automated requests and are not included.

## Iteration 8 — design and UX, 2026-09-28

Build `2026-09-28f`. Decisions D-48…D-58.

- **Visual system.** Dark theme: near-black ground, warm white type, one saffron accent. Onest
  throughout. Each page opens with its key number filled with a photograph of the region.
  Every text/background pair is 4.5:1 or better; the old white-on-gold buttons were 3.2:1.
- **Home.** The hero is the count itself — 13/17 open calls that fit — cut out of a photograph
  of the steppe; it recounts when the reader changes career stage or country. Below it, a
  departures board of the six calls closing next, with the reader's verdict on each. The globe section shows members by field; hovering a field lights
  its members.
- **Opportunities.** Profile as a sticky sentence, type filter with counts, sort by deadline
  (was file order), a four-month deadline timeline, condition chips on every call, deadline
  bar under each date. `/` focuses search.
- **Researchers.** Rows instead of cards, 24 per page, ranked search, filters in the URL,
  profile dialog in three languages with "Show on map" and a link to correct or remove it.
- **For organizations.** Network search moved first; forms in a two-column layout.
- **Fixes found on the way.** Mirrored globe (D-54). Newsletter sign-up that never left the
  browser (D-57). 492/497 mismatch (D-56). Invisible ghost buttons on light backgrounds,
  including Edit/Remove on the curator screen. Kazakh dates printed as "M09 30" in Chrome.
- **Photos** in `assets/img/` are generated illustrations, labelled in the footer (D-53).
- **Not reviewed by a native speaker:** every new Kazakh and Russian string (B-35 still open).

Tested in headless Chromium: 9 pages × 3 languages × 390 and 1440px with no JS errors, no
raw i18n keys and no horizontal scroll; directory, home, opportunities, timeline and motion
checks all pass.

## Works

**Opportunities** — `opportunities.html`
20 structured opportunities, 17 of them open, with filters, search, expiry handling and
URL-shareable state.
Every card carries an eligibility verdict for the visitor's country and career stage, with
a link to the source the verdict came from. No match percentages: none are calibrated yet.

**Three languages** — қазақша · русский · English
The whole interface is translated: menus, buttons, forms, headings and every sentence the match
engine generates. 285 keys in three dictionaries, in `assets/js/i18n.js`, loaded before `app.js`
so no page shows English and then swaps under the reader. The switcher sits in the header; the
choice goes into the URL and is remembered, and a new visitor gets their browser's language with
English as the fallback.

**The conditions a funder publishes are not translated.** An opportunity's title, summary and
eligibility note stay in the funder's own words, with a line next to them saying why: a
machine-translated eligibility rule is exactly the harm this product exists to prevent. A curator
can add `title_kk` or `summary_ru` by hand and those are used when present (D-42).

Country names come from the browser's own CLDR data, with 69 names written out by hand — the nine
priority countries and every EU member and Horizon Europe associated country — because Kazakh
region names are missing from some browsers' ICU, and a verdict that says "Қазақстан" in one
browser and "Kazakhstan" in another is a bug the reader sees (D-44).

The Kazakh and Russian text was written for this release and **has not been reviewed by a native
speaker in the scientific register** — B-35. `curate.html` and `admin.html` stay in English on
purpose: they are curator screens, not visitor screens.

**Match analysis** — `QIST.matchOpportunity()`
Every opportunity card now carries a score, a sentence and the rows the score was counted from.
The number is **requirements met out of requirements this call actually states** — counted, not
predicted, and every line is checkable against the funder's page. A requirement the call does not
state (no deadline, open to all fields) is not counted, so a three-condition call is scored out of
three. Country, career stage and an open deadline are blocking: fail one and the verdict says you
cannot apply, whatever the percentage looks like. The card says in plain words that this is **not**
a chance of winning — we have no response data, so a weighted prediction would be a guess dressed
as a number (D-07, D-33). A language model can sit on top of this breakdown once the backend
exists; it will not replace the count.

The separate "Academic matching" page is gone from the footer: matching is a property of the
search, not a section of the site (D-37).

**Eligibility engine** — `QIST.checkCountry()`
All 250 ISO countries, four Horizon Europe statuses (EU member / associated / funded /
self-funded). Verdicts are read from `data/eligibility.json`, never computed by a model.
A funder that publishes its own country list now overrides the programme table, carrying
its own source link: Faculty for the Future takes Uzbekistan, Kyrgyzstan, Tajikistan and
Turkmenistan but **not** Kazakhstan; the TWAS developing-countries list has no Georgia or
Armenia. Both were checked against the funders' own documents on 2026-09-18.

**Curator screen** — `curate.html`
Adding an opportunity no longer means editing JSON by hand. The screen validates against the
same rules the site uses — an external call cannot be saved without a link to the funder's
page, a country list cannot be saved without the source it came from, duplicate ids and
unknown country codes are caught before saving — then hands back the finished
`data/opportunities.json` to commit. It needs no backend. Linked from `admin.html`.

**Navigation** — Home · Opportunities · Researchers · For organizations · About QIST
Map and globe are views inside Researchers, not sections. Matching is not in public
navigation: it is personal and belongs behind sign-in. "For organizations" is the only
audience item on the site, and it is a deliberate exception (D-27).

**Discussions** — two channels, not five
Jobs, Research Grants and Collaboration Requests were removed: every post in them was already a
structured entry in Opportunities, with an eligibility verdict and a source link. Two places for
one call is one too many. Nothing was deleted — the ten migrated posts keep their records and
carry `superseded_by` pointing at the entry that replaced them, and an old `?c=jobs` link now
opens a live channel and says where that one went instead of throwing (D-45, D-46).

**For organizations** — `organizations.html`
One page, two readings: a switch at the top — **company first** — rewrites the page and tags every
submission with `audience`, so the data decides later whether to split it.

Researchers appear here **anonymously**: research field, seniority band, country. Name, title,
organisation, city and public link are not rendered and are not in the DOM, and searching by name
returns nothing. An open named list would hand over the only asset QIST has — an organisation reads
it once, finds those people elsewhere and never comes back (D-34). A name reaches an organisation
only after that member agrees to a specific introduction.
Three things a visitor can actually do:

1. **Post a need** — an R&D problem, a vacancy, a consortium partner or a single expert
   question. It reaches a curator, who publishes it in Opportunities with the organisation
   named. Nothing appears on the site automatically.
2. **See what expertise is in the network** — a real search across all 497 records by field,
   country and topic, returning anonymous capability cards. "Request an introduction" opens
   inline and states, before anything is sent, that the name and contact reach the organisation
   only if that researcher agrees.
3. **Book 30 minutes** — a discovery call. The page says plainly there is nothing to buy.

A block at the bottom lists what does not exist yet — no organisation accounts, no verified
badges, no paid product — and its counters are computed from the data at load time, so they
cannot rot into a lie.

**Create profile** — `login.html`
The header button says "Create profile" and now does it: without a backend it collects a real
request through Formspree and a curator creates the profile by hand. It does not ask for a
password, because there is nowhere to keep one.

**Home page** — `index.html`
Rebuilt. "What you can do here" repeated the navigation, "Latest opportunities" was a weaker copy
of the real page without verdicts, and "Featured researchers" paraded six names chosen by an
unexplained flag — which contradicted the rule that organizations see no names at all. In their
place: a live eligibility check on three open calls that reacts to the country and stage you pick,
two clearly separated doors (researcher / organization), and the depth of the network by research
field with no names. The three calls are chosen to exercise different edges of the check, because
the three closing soonest all happened to be open to any nationality and the demonstration
demonstrated nothing (D-39).

**Data provenance — corrected**
The site used to say the directory was "compiled from public sources: university pages, Google
Scholar and open researcher profiles". That was **wrong**, and wrong in an expensive direction: it
described collection without consent where consent exists. Everyone in the directory is a QIST
member who joined the association themselves and supplied these details. Fixed on `about.html`,
`organizations.html`, the README and here (D-35). B-34 is to reconcile the 497 records against the
membership register and record a joining date, so the claim can be backed up.

**Honesty fixes**
- Hard-coded admin credentials removed from the public JS *and* from the sign-in page text.
- Sign-in, registration and the admin console disable themselves without a backend,
  instead of writing fake accounts into the visitor's own browser.
- Home page counters: `497 / 42 / 902 / 13` → `492 / 41 / 32 / 7`.
- `geo_precision` on every directory record: 338 hold a country centroid, and that is now
  visible on the map, in the directory and on the globe rather than shown as a real address.
- 5 probable duplicate records flagged, not deleted.

**Language** — the whole interface and all opportunity data are in English.
Researchers' own names are left exactly as recorded.

## Limits — know these before launch

1. **`INTEREST_ENDPOINT`, `SIGNUP_ENDPOINT`, `CONTACT_EMAIL` are empty.** Until they are set,
   no response and no email address is collected at all. Formspree setup: README.
   Tally does not work for this — see D-17.
2. **`CONTACT_EMAIL` is the most urgent of the three**: 492 people are published with no
   working way to ask for removal.
3. **Eligibility lists were extracted by automated reading of the EC PDF.** One earlier read
   of the same document was wrong about three countries. Have a human spot-check the nine
   priority countries and record it in `eligibility.json` → `verification.reviewed_by` (B-18).
4. **17 active opportunities, not 100.** Still the product's real bottleneck, not the code.
   Ten calls were added on 2026-09-19, each read from the funder's own page: ERC Starting and
   Consolidator 2027, MSCA Doctoral Networks 2026, COST Open Call 2026, Erasmus+ Capacity
   Building, Faculty for the Future, Humboldt Research Fellowship, TWAS–FAPESP, NATO SPS and
   IIE-SRF. Several strong candidates were checked and **left out** because they had already
   closed (MSCA Postdoctoral Fellowships and COFUND, MSCA Staff Exchanges, Digital GreenTalents,
   TÜBİTAK 2216, L'Oréal-UNESCO For Women in Science) or because none of the nine countries
   qualify (TWAS-SISSA-Lincei is for least developed countries only). That filtering is the
   slow part of curation, and it is what the curator screen exists to keep honest.
5. **Backend is written but not deployed.** Opportunities are edited in a JSON file and reach
   the site by commit.
6. **Cities for 338 records are not recovered** — no geocoder reachable from the dev sandbox.
7. **10 directory records have no country and no organisation** and cannot be matched (B-19).

## Verified

224 automated checks in headless Chromium across `test.mjs` (22), `test2.mjs` (18),
`test3.mjs` (19), `test4.mjs` (16), `test5.mjs` (30), `test6.mjs` (38), `test7.mjs` (40) and
`test8.mjs` (41). Covering: eligibility verdicts across two programmes and nine countries,
filters, empty and error states, expired entries, button behaviour with no endpoint
configured, absence of the admin password anywhere in the build, honest counters, coordinate
precision labels, the full 250-country selector, English-only interface text, and no
horizontal scroll at 390px. No JavaScript errors.

`test5.mjs` additionally runs every record in the data file through the site's own validator,
checks that the funder country lists produce the right verdict with the right source link, and
drives the curator screen end to end — empty form blocked, duplicate id caught, unknown country
code caught, country list without a source rejected, record saved, draft surviving a reload,
reset back to the committed file. It found three real defects on its first run: two records
carrying `country: "OTHER"` instead of an ISO code, and 529px of horizontal scroll on the new
screen at phone width. All three are fixed.

`test6.mjs` covers the organizations page against a local receiver, because formspree.io is
unreachable from the sandbox: it checks that all four submission kinds (`org_need`,
`org_introduction`, `org_conversation`, `profile_request`) actually leave the browser with the
right body and the `Accept: application/json` header Formspree needs, that a malformed email
sends nothing at all, and that no researcher contact detail is in any payload. It also proves the
anonymity by comparing the rendered DOM against the source data — no name, organisation, city or
link of any shown researcher appears anywhere in the markup, and a search for a real name returns
nothing.

`test7.mjs` runs 80 score calculations across four reader profiles and asserts that the numerator,
the denominator and the percentage agree, that a requirement the call does not state never enters
the denominator, and that a blocking failure overrides a high percentage. It also checks the brand
lockup by computed style rather than by eye, the footer links against the header, and that the
corrected provenance wording is actually on the pages.

`test8.mjs` loads all eight public pages in all three languages and fails on a raw key left
visible, a missing `<html lang>`, a missing dictionary entry, a mismatched `{placeholder}` between
languages, or any JavaScript error. It also proves the funder's own title is untouched on the
Kazakh version, that the retired channels are gone while none of the 13 posts were deleted, and
that no page scrolls sideways at 390px in Kazakh. It found three real defects on its first run: a
crash on old `?c=jobs` links, 137px of horizontal scroll from the new header, and a key that a
regeneration had dropped.

`L is not defined` on map.html appears only in the sandbox, where unpkg.com is blocked.
Leaflet loads on the live site — checked 2026-09-14. **The country-marker logic on the map
is therefore not covered by automated tests; please look at it after deploying.**

## Deploy — read this first

A release is **one set of files that must go up together**. The 2026-09-18 incident: the three
HTML files reached the server but `assets/js/app.js`, `data/eligibility.json` and
`data/opportunities.json` did not. The page called a helper that was not there, threw, and
rendered blank with no explanation.

Two things changed because of it:

- `opportunities.html` now checks its dependencies and, if they are stale, says which file is
  out of date instead of showing an empty page.
- When you upload a release, upload **every file in the zip**, including the `assets/` and
  `data/` folders. Dragging only the changed HTML is what caused this.

## Live check, 2026-09-18

Verified directly against `aika369.github.io/qist-platform/opportunities.html`:
build `2026-09-18d` served, 7 cards, 250 countries in two groups, 35 research fields,
no deploy-guard message. The site works. The earlier "page is newer than the files"
message came from a browser cache holding the previous `app.js`.

## What is blocked on the backend

Three things asked for in the last review cannot be built on GitHub Pages, because there is nowhere
to keep files or passwords:

- **Organization sign-up and sign-in** with a stored profile (B-31).
- **Researcher profile editing, avatar upload, CV upload** and building a profile from the CV
  (B-30). CV parsing is server-side by necessity: a model key cannot live in the browser.
- **A language model on top of the match breakdown** (B-32).

Everything else from that review is done. The backend (B-29) is now the single blocker for the
rest, and it needs decisions only you can make: hosting account, who pays for it, which domain.

## Next

1. **Confirm the response path works.** Click **Interested** on the live site and check that the
   submission appears in the Formspree dashboard. That is the first real metric this product has
   ever produced, and nothing else on this list matters until it works.
2. **Curate weekly, not once.** Open `curate.html`, add what you find, download the file, commit.
   Twenty records is a demo; a hundred with live deadlines is a product. Three entries are already
   expired — B-21 is the habit of checking them, not a feature.
3. **Answer the new inbox.** The organizations page promises a reply within two working days.
   Decide who reads `org_need`, `org_introduction`, `org_conversation` and `profile_request`,
   and how fast (B-25). An unanswered promise is noticed on the first submission.
5. **Ten to fifteen conversations with universities** (B-26). That is what this page exists for,
   and what the paid product has to be built on.
6. **B-18 is still open.** The nine countries' Horizon Europe statuses have not been checked by a
   human against the EC PDF. One automated read of that document was already wrong about three of
   them.
