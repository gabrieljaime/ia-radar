# Review: factual-anchor validation, model dedup, digest visibility

Date: 2026-08-17
Reviewed target: local commit `6d3d55c` ("actualziacion", 19 files) — the LLM
factual-anchoring feature, model-family dedup, and digest changes.
Resulting fix commit: `9cc95e3`.
Process: `/plan-ceo-review` (mode: SELECTIVE EXPANSION) followed by
`/plan-eng-review` (FULL_REVIEW), both with an independent outside-voice
pass (Codex was not installed, so a fresh Claude subagent stood in).

## What `6d3d55c` did

Five bundled changes, meant to stop the LLM from hallucinating or
substituting adjacent model names/versions when analyzing an article:

1. Added `exact_model_id` / `organization` / `source_last_modified_at` to
   the `Candidate` domain object, populated by the HuggingFace and
   Cohere-changelog collectors.
2. Added a "FACTUAL ANCHORS" prompt instruction requiring the LLM's
   returned `subject_name` to reproduce `exact_model_id` exactly, with a
   `validate_factual_anchors()` check and one retry on mismatch.
3. Added `base_model_identity()` — regex-based model-family dedup in
   addition to the existing fuzzy title-similarity dedup.
4. Added `humanize_action()` to translate the raw `suggested_action` enum
   into Spanish labels.
5. Changed `DigestService` to filter by `Article.published_at` falling
   inside the digest window, instead of analysis/first-seen time.

## CEO review — findings and decisions

Mode: **SELECTIVE EXPANSION** (hold the existing scope as baseline, surface
extra opportunities one at a time, no forced scope growth).

### From the in-house review (Step 0C-bis + section pass)

| # | Finding | File | Decision |
|---|---|---|---|
| 1 | `send_digest.py --run-id` returns empty: the run's own start/finish window is minutes long, but `Article.published_at` is the source's own (often days/weeks old) publish date — the new window filter excluded almost every article a run actually analyzed. | `app/digest/service.py` | Fixed: run-scoped digests use only `Event.analyzed_run_id == run.id`, no publish-date window. |
| 2 | On final factual-anchor rejection, only the retry-warning log carried the expected/returned model name; the final failure just recorded the generic exception type. | `app/application/radar_service.py` | Fixed: log expected/returned on final failure too. |
| 3 | `source_last_modified_at` was written by the collector but never read anywhere — a dead column. | `scripts/show_candidate.py` | Fixed: surfaced in the debug script's output. |
| 4 | `base_model_identity()` only recognized qwen/glm/deepseek — Cohere Command releases (already extracted with `exact_model_id`) got no family-dedup. | `app/pipeline/normalize.py` | Fixed: extended to Cohere Command. |
| 5 | `repository.py`'s `_matching_event` fell back to `base_model_identity(candidate.title)` when `exact_model_id` was unset — a comparison/roundup article title (e.g. "DeepSeek 3.1 vs Qwen 3.8") could match the family regex and false-merge into an unrelated event. | `app/db/repository.py` | Fixed: family-dedup only runs when `exact_model_id` is explicitly set. |

### From the outside voice (independent Claude subagent pass)

| # | Finding | Severity | Decision |
|---|---|---|---|
| 1 | The anchor was validated then discarded: `subject_name`/`subject_type` were never persisted, `event.title` stayed the raw candidate title. Combined with `temperature=0` making the retry deterministic (same rejected answer twice), and exact-string matching with no formatting tolerance, plus `mark_analysis_failed` setting `status="discarded"` with no path back to re-analysis for non-primary sources — real model releases could be **permanently and silently dropped**. | CRITICAL | Fixed: normalized comparison (casefold, strip org prefix, collapse separators, preserve `+`), persisted the verified name to a new `Event.subject_name` column, retry uses `temperature=0.3`. |
| 2 | `digest/service.py` dropped every event whose only article had `published_at IS NULL` (e.g. Cohere date-parse failures) — permanently, from every digest, not just the ones outside the time window. | High | Fixed: falls back to `Article.discovered_at` via `coalesce()` when `published_at` is null. |
| 3 | `humanize_action()` was missing labels for `suggest_teaching_use` and `suggest_course_update`, both enabled in `educator.yaml`/`course.yaml` — those digests mixed Spanish and raw English enum values. | Medium | Fixed: added both labels. |
| 4 | The Cohere extraction regex `R(?:\s+\d+B)?` matched "Command R" *inside* "Command R+", truncating the extracted anchor — then the strict validator rejected the LLM's correct "Command R+" answer as a contradiction. | High | Fixed: regex now captures "R+" as its own alternative. |
| 5 | `base_model_identity("Qwen3-235B-A22B")` and `base_model_identity("Qwen3-235B-A22B-Instruct")` returned the same identity — a base release and its instruct-tuned sibling (legitimately distinct, newsworthy) silently merged into one event. | High | Fixed: tuning qualifiers (Instruct/Chat/Base) now produce a distinct identity; quantization qualifiers (FP8/GGUF/etc.) still collapse together. |
| 6 | Dead code (`strip_artifact_variant()`, never called) and migration `0007`'s revision id didn't match the `000N` convention every other migration uses — a future migration writing `down_revision = "0007"` would silently break the chain. | Low | Fixed at the time — **later reverted**, see the Eng review section below. |

## Eng review — findings and decisions

Scope: the full working-tree diff of the CEO-review fixes (17 files).
Step 0 complexity check triggered (>8 files) — user chose to proceed as-is,
since it was 9 independently-scoped, already-approved bug fixes rather than
one overbuilt feature.

### From the in-house review

| # | Finding | Decision |
|---|---|---|
| 1 | `tests/test_llm_provider.py` had zero coverage of the new `retry` parameter — the entire justification for the anchor-retry fix (temperature must change) was unverified at the HTTP-request layer. | Fixed: added `test_provider_uses_nonzero_temperature_only_on_retry`, asserting the outgoing request body. |
| 2 | `app/digest/service.py` built the identical `func.coalesce(Article.published_at, Article.discovered_at)` expression in two places. | Fixed: extracted to `_effective_published_at()`. |

### From the outside voice (independent Claude subagent pass)

| # | Finding | Severity | Decision |
|---|---|---|---|
| 1 | **Migration revision-id rename would break the already-migrated local database.** The CEO review's "cleanup" renamed `0007`'s revision id from `"0007_source_modified"` to `"0007"` — but `docker compose exec postgres psql` confirmed the local dev DB's `alembic_version` was still `0007_source_modified`. The next `alembic upgrade head` would have failed with "Can't locate revision". | **CRITICAL** | Reverted: kept `"0007_source_modified"` as the real id; `0008`'s `down_revision` points at it. Verified `alembic upgrade head` applies cleanly against the running DB (confirmed at head `0008`). |
| 2 | `_COMMAND_FAMILY_PATTERN` (added during the CEO review to cover Cohere Command) reintroduced the exact bug just fixed for the Cohere extractor: `base_model_identity("Command and control for agents")` returned `"command-a"`. Also, `_TUNE_VARIANTS` included `"it"`, a common English word, causing `"Qwen3 8B it is great"` to false-match as a tuning variant. | **High** | Fixed: added the same `(?!\w)` boundary used in the Cohere regex; removed `"it"` from `_TUNE_VARIANTS` (kept `instruct`/`chat`/`base`). |
| 3 | `DigestEvent.recency` still read raw `article.published_at`, not the new `coalesce()` fallback — an event only visible because of the `discovered_at` fallback sorted as `-inf` (oldest possible) and always landed last, regardless of actual freshness. | Medium | Fixed: `recency` now falls back to `discovered_at` too. |
| 4 | The CEO review's dedup fix only restricted the **candidate** side to require `exact_model_id`; the **event** (match target) side still compared against raw `event.title`. A roundup event created first could still be a merge target for a later verified candidate. | Medium | Fixed: target side now prefers `event.subject_name` (the new verified-name column) over `event.title`. |
| 5 | `event.subject_name` is persisted for every analysis, including candidates with no `exact_model_id` — the column name implies "verified" but for most events it's just the LLM's own unverified naming. | Low | Documented: added a comment on the column clarifying it's anchor-verified only when the source candidate had `exact_model_id` set. |
| 6 | A profile-set mismatch gets zero retries while a factual-anchor mismatch gets one — an asymmetry. | Low | Reviewed and left as-is: profile-set violations are a structural schema failure a temperature bump won't fix, unlike a factual anchor mismatch (picking the right proper noun). Not the same failure class. |

## Final state

- 118 tests passing (0 failing, 3 skipped), `ruff check` clean.
- Migration chain verified against the real local Postgres database:
  `0001 → ... → 0007_source_modified → 0008`, currently at head.
- All fixes committed in `9cc95e3` on `main` (2 commits ahead of
  `origin/main`, not pushed).

## Key lessons captured

- **Never rename an Alembic revision id for convention/cosmetic reasons
  without checking whether any database — even a solo local dev DB — has
  already applied it.** Check with:
  `docker compose exec postgres psql -U <user> -d <db> -c "SELECT version_num FROM alembic_version;"`
  A rename that doesn't match the DB's applied version breaks the next
  upgrade with "Can't locate revision".
- **A trailing `\b` word boundary in a regex fails right after a
  non-word character** (like `+`). If an alternation has a branch ending
  in punctuation, `\b` after the group silently prefers a shorter,
  wrong match. Use `(?!\w)` instead when the match may legitimately end
  in punctuation.
- A fix applied to one regex (the Cohere extractor) does not
  automatically apply to a second regex solving the same class of
  problem (the family-dedup pattern) — each needs its own verification,
  even within the same review session.
