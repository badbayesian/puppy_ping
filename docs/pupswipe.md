# PupSwipe

PupSwipe is a server-rendered UI + HTTP API for browsing adoptable pets, storing swipes, and managing account-based likes.

## Routes

API:

- `GET /api/puppies`
  - Common query params: `limit`, `max_age`
  - Also supported: `species`, `breed`, `name`, `provider`
- `POST /api/swipes`
  - Stores swipe events (`left` or `right`)
- `GET /api/health`
  - DB connectivity check

Web:

- `GET /` renders the swipe UI
- `GET /signin` renders sign-in page
- `GET /likes` shows likes for the signed-in user
- `GET /reset-password` signed-in password change flow
- `GET /forgot-password` request reset email
- `GET /forgot-password/reset?token=...` token-based reset form

## Auth and Password Reset

- First successful sign-in with email+password creates the account.
- Subsequent sign-ins authenticate against the saved hash.
- Session is maintained with a signed HTTP-only cookie.
- Forgot-password uses one-time hashed tokens with expiry.
- Reset email links are generated with `PUPSWIPE_PUBLIC_URL` (or forwarded host/proto fallback).

## Filtering

- Current UI filter is max age (months), auto-submitted on change.
- Default max age is `8` months.
- `max_age` is preserved in redirects/forms when active.

## Environment Variables

PupSwipe-specific:

- `PUPSWIPE_SESSION_SECRET`
- `PUPSWIPE_PUBLIC_URL`
- `PUPSWIPE_SOURCES`
- `PUPSWIPE_PORT`
- `PUPSWIPE_BIND_IP`
- `PUPSWIPE_DEV_PORT`
- `PUPSWIPE_DEV_BIND_IP`

Email reset flow:

- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_USER`
- `EMAIL_PASS`
- `EMAIL_FROM`
