# The Shelf

Goodreads for essays. People log the long-form pieces they read, give a one-tap
verdict, file them on public shelves under their own name, and browse other
people's shelves.

The psychology is Letterboxd, not Pocket.

## Stack

- Django 5.x + SQLite (WAL mode)
- HTMX + Alpine.js
- Tailwind (CDN) with the design tokens from the brief
- Nothing else. No Celery, Redis, RSS, or vector store.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed
python manage.py runserver
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/).

Seed curators (password `seed-password-change-me`):

- `@tom`
- `@marginalia`
- `@jpike`
- `@holloway`

Strip seed accounts later with `python manage.py seed --flush-seed`. Essays stay.

## Tests

```bash
python manage.py test shelf
```

Covers URL normalisation, the ranking model, the log/rate/unshelve services and the
HTMX write paths. The suite includes a guard that no page ever renders the ranking
score, since that rule is easy to break by accident.

## Routes

| Path | Purpose |
|------|---------|
| `/` | Landing |
| `/e/<slug>/` | Essay page |
| `/@<handle>/` | Profile |
| `/@<handle>/<shelf>/` | Public shelf |
| `/discover/` | Newly logged + held up longest |
| `/add/` | Add an essay (auth) |
| `/signup/`, `/login/` | Auth |

## Design rules that matter

1. **Shelving is append-only.** Un-shelving sets `removed_at`. Never hard delete.
2. **Rating and Shelving are separate.** A rating does not imply a shelving.
3. **Never render the ranking score.** It orders lists; the page shows the record
   ("on shelves since 2008", "still going").
4. **Log first, rate optionally.** The primary button is always Log it.
