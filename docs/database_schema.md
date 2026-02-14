# Database Schema

This document summarizes the Postgres tables created/managed by:

- `puppyping/db.py` (`ensure_schema`)
- `puppyping/pupswipe/repository.py` (`ensure_app_schema`)

The current schema is pet-centric (`pet_*`), with migration logic to rename/upgrade legacy `dog_*` tables.

## Core Scraper Tables

### `pet_profiles`

Historical snapshots of scraped pet profiles.

Key columns:

- `pet_id`
- `species`
- profile fields (`url`, `name`, `breed`, `gender`, `age_raw`, `age_months`, `weight_lbs`, `location`, `status`, `ratings`, `description`, `media`)
- `scraped_at_utc`

Key constraints/indexes:

- unique on (`pet_id`, `species`, `scraped_at_utc`)
- index on `scraped_at_utc DESC`
- index on `pet_id`
- index on `species`

### `cached_links`

Per-source fetched links and active state.

Key columns:

- `id` (hash key)
- `source`
- `link`
- `fetched_at_utc`
- `is_active`
- `last_active_utc`

Key constraints/indexes:

- primary key on `id`
- unique index on `link`
- index on (`source`, `is_active`)
- index on `fetched_at_utc DESC`

### `pet_status`

Current active/inactive status by provider+link.

Key columns:

- `id` (hash key)
- `source`
- `link`
- `species`
- `is_active`
- `last_active_utc`

Key constraints/indexes:

- primary key on `id`
- unique index on (`source`, `link`)
- index on (`source`, `is_active`)
- index on `species`

### `email_subscribers`

Email subscription list for alert recipients.

Key columns:

- `email`
- `source`
- `created_at_utc`

Key constraints/indexes:

- unique index on `LOWER(email)`
- index on `created_at_utc DESC`

### `emailed_pet_profiles`

Tracks which pet profiles have been emailed to each recipient.

Key columns:

- `recipient_email`
- `pet_id`
- `species`
- `first_sent_at_utc`
- `last_sent_at_utc`
- `send_count`

Key constraints/indexes:

- unique on (`recipient_email`, `pet_id`, `species`)
- index on (`recipient_email`, `last_sent_at_utc DESC`)

## PupSwipe Tables

### `users`

PupSwipe accounts.

Key columns:

- `email` (unique)
- `password_hash`
- `created_at_utc`
- `last_seen_at_utc`

### `pet_swipes`

Swipe interaction events.

Key columns:

- `pet_id`
- `species`
- `swipe` (`left` or `right`)
- `source`
- `created_at_utc`
- optional user/client metadata (`user_id`, `user_key`, `user_ip`, `user_agent`, `accept_language`, `screen_info`)

Key constraints/indexes:

- check constraint on `swipe` values
- optional FK `user_id -> users.id` (`ON DELETE SET NULL`)
- index on `created_at_utc DESC`
- index on `pet_id`
- index on `species`
- index on `user_id`
- index on `user_key`

### `pet_likes`

Per-user liked pets.

Key columns:

- `user_id`
- `pet_id`
- `species`
- `source`
- `created_at_utc`

Key constraints/indexes:

- FK `user_id -> users.id` (`ON DELETE CASCADE`)
- unique on (`user_id`, `pet_id`, `species`)
- index on (`user_id`, `created_at_utc DESC`)
- index on `pet_id`
- index on `species`

### `password_reset_tokens`

Hashed one-time reset tokens.

Key columns:

- `user_id`
- `token_hash`
- `created_at_utc`
- `expires_at_utc`
- `used_at_utc`

Key constraints/indexes:

- unique on `token_hash`
- FK `user_id -> users.id` (`ON DELETE CASCADE`)
- index on (`user_id`, `created_at_utc DESC`)
- index on `expires_at_utc DESC`

## Relationships

Enforced with FKs:

- `pet_swipes.user_id -> users.id`
- `pet_likes.user_id -> users.id`
- `password_reset_tokens.user_id -> users.id`

Logical joins used by queries:

- `pet_profiles.url` <-> `pet_status.link`
- `pet_profiles` <-> `pet_swipes` via (`pet_id`, `species`)
- `pet_profiles` <-> `pet_likes` via (`pet_id`, `species`)

## Notes

- Migration blocks in schema setup can rename legacy `dog_*` tables to `pet_*`.
- API payloads and rendering still include some `dog_id` compatibility fields in server code for transition safety.
