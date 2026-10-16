# QIST Platform

**ScienceBridge AI** — an initiative of **QIST, the Qazaq International Science and Technology Association** ([qista.org](https://qista.org)).

MVP phase 1 covers nine countries — Kazakhstan, Uzbekistan, Kyrgyzstan, Tajikistan, Turkmenistan, Azerbaijan, Georgia, Armenia and Mongolia — plus researchers from those countries working anywhere in the world. Later phases are intended to be worldwide. The nine are what the eligibility data, the curated opportunities and the directory actually cover today, so the nine are what the site claims.

**Live site:** https://zangir.github.io/qist-platform/

## Features

- 🗺️ **Researcher map** — interactive world map (Leaflet + clustering) of community members, filterable by name, topic and country
- 🔎 **People directory** — search by research topic, career stage, country of work and years of experience
- 📢 **Channels** — on-platform boards: Jobs & Vacancies, Research Grants, Conferences & Events, Collaboration Requests, General Discussion
- 🤝 **Academic matching** — enter your interests and goal (co-author / mentor / mentee) and get ranked collaborator suggestions with match scores
- 📮 **QIST newsletter** — digest issues published on-site with email subscription
- 🔐 **Accounts** — participant registration/login plus an admin panel (manage researchers, moderate posts, view subscribers and collaboration requests)

## Architecture

Two modes, one data contract:

1. **Static mode (GitHub Pages, default)** — the frontend runs entirely from `data/*.json`; user-created records (accounts, posts, subscriptions, collaboration requests, admin edits) are kept in the browser's `localStorage`. Zero infrastructure, ideal for the first version.
2. **API mode (Python backend)** — the FastAPI app in [`backend/`](backend/) serves the same endpoints with a real SQLite database, hashed passwords and JWT auth. Point the frontend at it with `localStorage.setItem('qist_api_url', 'https://your-api')` and everything becomes shared and persistent. See [backend/README.md](backend/README.md).

## Demo accounts (static mode)


## Local development

Static site: any web server from the repo root, e.g. `python3 -m http.server 8080`.

Backend: see [backend/README.md](backend/README.md).

## Data

`data/people.json` holds **QIST members who joined the association themselves** and supplied their own details. It is not scraped from university pages or Google Scholar, and nothing in the code or the interface may say that it is. To add, correct or remove an entry, open an issue or PR — or use the admin panel.

Two rules follow from that and are enforced in the interface:

- Email addresses are never published in the directory and never sent to an organisation.
- On `organizations.html`, researchers appear **anonymously** — research field, seniority band, country. Names, titles, organisations and public links are not rendered and are not in the DOM. A name reaches an organisation only after that member agrees to a specific introduction (DECISIONS.md D-34).

---

## Opportunities и право участия (итерация 1, 18.09.2026)

Раздел `opportunities.html` показывает структурированные возможности и для каждой —
вердикт о праве участия для выбранной пользователем страны.

### Как добавить возможность

**Обычный путь — экран куратора `curate.html`.** Откройте его на сайте (ссылка есть в
`admin.html`), заполните форму, нажмите «Add to the working list», затем «Download
opportunities.json» — и положите скачанный файл вместо `data/opportunities.json` в
репозитории. Экран проверяет запись по тем же правилам, что использует сам сайт, и не даёт
сохранить неполную: без ссылки на страницу фонда, с занятым `id`, с несуществующим кодом
страны или со страновым списком без источника. Бэкенд для этого не нужен, ничего никуда не
отправляется, черновик хранится в вашем браузере до коммита.

Формат файла (если правите руками):

```json
{
  "id": "o-2026-11-widera",
  "type": "grant",
  "status": "published",
  "title": "...",
  "organization": "...",
  "country": "KZ",
  "summary": "...",
  "fields": ["Materials Science"],
  "career_stage": "phd_plus",
  "eligibility": { "programme": "horizon_europe", "note": "" },
  "funding_status": "confirmed",
  "deadline": "2026-11-12",
  "source_url": "https://..."
}
```

- `type`: `grant` · `consortium_role` · `academic_job` · `industry_job` · `coauthor` · `rnd_challenge` · `expert_request` · `conference`
- `career_stage`: `any` · `phd_student` · `phd_plus` · `postdoc_plus` · `pi_only`
- `funding_status`: `confirmed` · `not_confirmed` · `cofunding_required`
- `origin`: `external` (конкурс с чужой страницы) · `community` (пост участника QIST)
- `eligibility.programme`: `horizon_europe` · `kz_national` · `open`
- `all_fields: true` — конкурс открыт для всех дисциплин; тогда `fields` оставляют пустым,
  запись находится по любому фильтру области и показывает одну строку вместо 35 тегов

**Правило источника:** для `origin: "external"` поле `source_url` обязательно. Конкурс без
ссылки на первоисточник не публикуется — иначе читателю нечем проверить условия и дедлайн.
Пост, написанный внутри QIST, страницы фонда не имеет и выдумывать её не обязан.

**Свой список стран у фонда.** Когда фонд публикует собственный перечень стран и он
расходится с таблицей программы, перечень кладут на саму возможность — вместе со ссылкой
на документ, откуда он взят:

```json
"eligibility": {
  "programme": "open",
  "countries_excluded": ["KZ", "AZ", "GE", "AM", "MN"],
  "countries_source_url": "https://www.fftf.slb.com/docs/Summary_Eligibility_Criteria.pdf",
  "countries_source_name": "Schlumberger Foundation — eligibility criteria",
  "countries_source_date": "2026-09-18"
}
```

Есть и `countries_allowed` — «только эти страны». Исключающий список проверяется первым.
Без `countries_source_url` запись не сохраняется: вердикт без ссылки — это догадка.

### Разбор соответствия — `QIST.matchOpportunity(opp, profile, elig)`

Возвращает `{ met, total, pct, tone, verdict, criteria, blocked }`.

- `met / total` — сколько требований конкурса выполнено из тех, которые конкурс **ставит**.
  Требования, которых нет (пустой `deadline`, `all_fields: true`), в знаменатель не попадают.
- `criteria[]` — по строке на требование: `{ key, label, blocking, ok, unknown, detail, source }`.
  `blocking: true` у страны, стадии и дедлайна; `unknown` — когда о читателе нет данных
  (не указал свою область), такая строка не считается ни в числителе, ни в знаменателе.
- `blocked` — есть ли проваленное блокирующее требование. Если да, `verdict` говорит об этом
  первой фразой: процент рядом со словами «вы не проходите» — это то, как теряют неделю.
- Это **не вероятность победы**, и в карточке так и написано. См. DECISIONS.md D-07 и D-33.

### Откуда берётся вердикт

Из `data/eligibility.json`. Для Horizon Europe статусы девяти стран взяты из
[List of Participating Countries in Horizon Europe](https://ec.europa.eu/info/funding-tenders/opportunities/docs/2021-2027/common/guidance/list-3rd-country-participation_horizon-euratom_en.pdf),
Европейская комиссия, v4.0 от 31.07.2026.

Вердикт **никогда не вычисляется моделью**. При обновлении списка ЕС правьте
`source_version` и `source_date` вместе со статусами — они показываются пользователю.

### Wiring up responses — three fields in `assets/js/app.js`

```js
INTEREST_ENDPOINT: '',   // where "Interested" on an opportunity goes
SIGNUP_ENDPOINT:   '',   // where pilot sign-ups from the home page go
CONTACT_EMAIL:     '',   // address behind "remove my profile" on about.html
```

While a field is empty the matching control **disables itself and says so**. Nothing is
written to `localStorage`: we do not collect data into a place we cannot read it from.

#### Use Formspree, not Tally

Checked on 2026-09-18: **Tally will not work here.** Its API only creates and manages forms
and requires a secret bearer token, so a static page cannot submit a response without
exposing that key. There is no public client-side submission endpoint.

Services that do accept a cross-origin JSON `POST` from a static page:

| Service | Endpoint shape | Free tier |
|---|---|---|
| **Formspree** | `https://formspree.io/f/{id}` | 50 submissions/month |
| Web3Forms | `https://api.web3forms.com/submit` | unlimited, needs `access_key` in the body |
| Basin, Getform, Formcarry | similar | varies |

Setting up Formspree, start to finish:

1. Create a form at formspree.io and copy its endpoint, e.g. `https://formspree.io/f/xyzabcd`.
2. Paste it into both `INTEREST_ENDPOINT` and `SIGNUP_ENDPOINT` (one form can receive both;
   each payload carries a `kind` field — `opportunity_interest` or `pilot_signup`).
3. Set `CONTACT_EMAIL` to the address that should receive data-removal requests.
4. Commit. Nothing else changes.

`QIST.submitForm()` already sends `Accept: application/json` — without that header Formspree
answers with an HTML redirect instead of JSON and the success check fails.

`mailto:address` also works as an endpoint value: it opens the user's mail client with the
payload prefilled. No account needed anywhere, but it needs the visitor to press send.

### Country eligibility data

`data/eligibility.json` holds all 250 ISO countries with a Horizon Europe status each:

- `eu_member` — EU Member State (27)
- `associated` — Associated Country (23), same rights as EU Member States
- `funded` — third country automatically eligible for EU funding (116)
- `self_funded` — participation possible, normally at own cost (84)

Source: European Commission, *List of Participating Countries in Horizon Europe*, v4.0 of
2026-07-31. The lists were extracted by automated reading of that PDF on 2026-09-18 —
`eligibility.json` records this in its `verification` block. **Spot-check the nine priority
countries against the source before a public launch**, and record who did it in
`verification.reviewed_by`.

## For organizations (итерация 5, 19.09.2026)

`organizations.html` — единственная аудиторная страница сайта. Переключатель наверху
(`?as=university` / `?as=company`) меняет тексты и проставляет поле `audience` в заявке;
отдельных страниц для университетов и индустрии нет намеренно (DECISIONS.md D-28).

Три действия, все через `QIST.submitOrgRequest(kind, subject, payload)` → `QIST.SIGNUP_ENDPOINT`:

| `kind` | Откуда | Что внутри |
|---|---|---|
| `org_need` | форма «Post a need» | тип, заголовок, описание, область, стадия, страна, статус финансирования, дедлайн, организация, контакт |
| `org_introduction` | карточка исследователя | `researcher_id`, `researcher_name`, `researcher_org`, `from_email` |
| `org_conversation` | форма «Book 30 minutes» | организация, контакт, страна, цель разговора |
| `profile_request` | кнопка «Create profile» в шапке (`login.html`) | имя, почта, должность, организация, страна, темы, публичная ссылка |

**Контакты исследователей не передаются.** Запрос знакомства уходит в QIST, QIST спрашивает
человека. В теле запроса нет и не может быть его почты — её нет в `data/people.json`.

**Пароли не собираются нигде.** Пока бэкенд не развёрнут, `login.html` показывает форму заявки
без поля пароля: хранить его негде (D-29).

## Языки (итерация 7, 19.09.2026)

Три языка: `kk`, `ru`, `en`. Словари — `assets/js/i18n.js`, грузится **до** `app.js`.

```html
<h2 data-i18n="opp.h2"></h2>                          <!-- textContent -->
<p  data-i18n-html="about.data.p1"></p>               <!-- innerHTML, только наша разметка -->
<input data-i18n-attr="placeholder:opp.search.ph">    <!-- атрибуты, через ; несколько -->
```

В JS — `QIST.t('key', { n: 5 })`. Подстановки в фигурных скобках: `{n}`, `{country}`, `{email}`.

**Как добавить строку:** впишите ключ во все три словаря в `assets/js/i18n.js`. Ключ, который
есть в `en`, но отсутствует в `kk` или `ru`, откатывается к английскому и пишет предупреждение
в консоль — а `test8.mjs` на этом падает.

**Что не переводится:** условия конкурсов. `title`, `summary` и `eligibility.note` остаются
словами фонда; куратор может добавить `title_kk`, `summary_kk`, `title_ru`, `summary_ru` — тогда
используются они. Имена исследователей не транслитерируются. См. DECISIONS.md D-42.

**Названия стран:** `QIST.countryName(code, elig)` — сначала `countries_kk` из
`data/eligibility.json`, затем `Intl.DisplayNames` браузера, затем английское название.

## Структура разделов

| Раздел | Файл | Что внутри |
|---|---|---|
| Home | `index.html` | Оффер, глобус, подписка |
| Opportunities | `opportunities.html` | Все возможности, любого типа и от любого отправителя |
| Researchers | `directory.html` + `map.html` | Один набор людей, три вида: список, карта, глобус |
| About QIST | `about.html` | Происхождение данных, приватность, удаление профиля |

Не в меню намеренно: `matching.html` (персонально — переедет в «My matches» за входом),
`channels.html` (обсуждения сообщества, ссылка из about), `newsletter.html` (архив, ссылка из about).

## Документы проекта

`PRD.md` — требования · `ROADMAP.md` — этапы · `DECISIONS.md` — решения и причины ·
`BACKLOG.md` — задачи с приоритетами · `STATUS.md` — что работает и что ограничено.

---

## Opportunities, профили участников, позиции и статьи (2026-10-16)

**Одна страница `opportunities.html`** вместо двух. Вкладки: Гранты · Вакансии · Коллаборации · Статьи участников · Сохранённое.
Под профиль читателя (стадия, страна, до 6 областей, ключевые слова, страны для вакансий) ранжируются:
ежедневные гранты и вакансии из `data/feeds/`, конкурсы, которые вручную ведёт куратор (`data/opportunities.json`, `curate.html`),
позиции участников (`/api/positions`) и их статьи (`/api/papers` + `data/papers.json`). У конкурсов куратора есть проверенное право
участия с объяснением («Details»: страна, стадия, срок, область, источник); у остальных грантов — «не проверено». Поиск словами и «Clear».
`feed.html` перенаправляет сюда.

**Профиль участника** — `join.html` (создание) и `profile.html` (правка): быстрый старт через ORCID iD (публичный API ORCID, в браузере)
или резюме (PDF/DOCX через `/api/cv/extract`, либо вставкой текста), фото (сжимается до 256 px в браузере), должность, организация, страна,
области, ключевые слова, ссылки, статьи (по DOI через Crossref, из ORCID или вручную), согласие на показ в каталоге. Без бэкенда форма
отправляет заявку куратору (Formspree); с бэкендом создаёт аккаунт. Участник может скачать свои данные и удалить аккаунт.

**Позиции из лабораторий** — `post-position.html`: название, лаборатория, страна, для кого, описание, обязательная ссылка, срок. С аккаунтом
публикуется сразу и видна во вкладке «Вакансии»; без сервера уходит куратору. Снять позицию может автор (профиль) или админ.

**База участников** — `admin.html` → «Members database» (поиск, экспорт CSV) и «Positions & papers» (модерация). Данные хранит бэкенд
(`backend/`, развёртывание: `render.yaml`, `backend/Dockerfile`); до его запуска `QIST.API_DEFAULT` в `app.js` пуст и сайт работает как статический.

**Главная** — новый первый экран (`assets/img/hero-globe.jpg`, поиск «Find researchers», 4 тезиса), крупная полоса цифр из данных
(исследователи, организации, темы, страны) и «Closing next» с проверкой «I'm a … based in …».

### Ежедневные ленты грантов и вакансий

`pipeline/` (Python, `requests` + `beautifulsoup4`), ежедневно `.github/workflows/feeds.yml`, пишет `data/feeds/{grants,jobs}.json` + `meta.json`
(по каждому источнику: сколько записей, ошибка, время). Лента статей из мира (arXiv, bioRxiv, medRxiv, Crossref) отключена (D-65), код остался:
`python -m pipeline.run --kinds grants,jobs,articles`.

| Лента | Источники |
|---|---|
| Вакансии | jobs.ac.uk (по дисциплинам и раздел PhD), Nature Careers, Inside Higher Ed Careers |
| Гранты | UKRI, NSF, Grants.gov (США), EU Funding & Tenders (Horizon Europe, ERC, MSCA), fundsforngos |

Источник, который упал, не роняет остальные: записи вчерашнего дня остаются, а страница пишет внизу, какие источники сегодня недоступны.
Разбор — детерминированный (`pipeline/taxonomy.py`, `pipeline/geo.py`, словарь `data/taxonomy.json`); подбор — `assets/js/feed.js`.

**Запуск и тесты** (из корня репозитория)

```bash
backend/.venv/bin/pip install -r pipeline/requirements.txt -r backend/requirements.txt
backend/.venv/bin/python -m pipeline.run                         # сбор лент (~4 мин)
backend/.venv/bin/python -m pytest pipeline/tests backend/tests -q
python3 -m http.server 8099 &                                    # затем браузерные проверки (Playwright):
backend/.venv/bin/python pipeline/tests/e2e_opportunities.py http://localhost:8099
backend/.venv/bin/python pipeline/tests/e2e_members.py http://localhost:8099
backend/.venv/bin/python pipeline/tests/e2e_members_backend.py http://localhost:8099   # сам поднимает API на :8100
```
