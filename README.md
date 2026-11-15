# X extension 1.0.0

SDK-only `flowsteward.x`, Python 3.12, `extension_host_v2`, platform API minimum
`1.9.0` (distinct from product release `0.9.18`). **Release blocked:** callback
ADR 0072 authoring fields are confirmed, but the required host implementation,
release integration and verification remain pending. Central `289205a8` alone does not support this profile. The official X API
publishes announcements with one static image and an intact article link, and
receives new direct replies to **every post of the selected account**, including
old posts and posts published outside Flow Steward. Historical comments,
user-to-user deep threads, DMs, browser automation, videos, GIF uploads, paid
long posts, multi-post threads, and a WordPress editor plugin are outside this
release. X documents `post.reply.create` as direct replies only and says it
does not fire for replies to replies; deeper continuation is not guaranteed,
including a thread containing an earlier account-authored reply. The X Activity
API may further restrict protected-account events.

## Connect and activate

1. Install the reviewed portable bundle. In the project, configure an X OAuth
   application with Authorization Code, PKCE S256, and a confidential client.
   Copy the **Core-generated OAuth redirect URL** to the X developer console.
   Configure that exact application's client ID and client secret in its OAuth
   configuration. Core owns exchange, refresh, and secrets; the extension never
   receives the refresh token or authorization code. For webhook verification,
   enter a separate connection secret `webhook_signing_secret` containing the
   **same app's OAuth2 client secret**. Core resolves this named connection secret;
   no OAuth-configuration secret lookup or lineage is assumed. Never enter the
   app bearer token or the legacy OAuth1 consumer secret in this field.
2. Authorize an `x_account` connection with `tweet.read tweet.write users.read
   media.write offline.access`. Missing scopes require reauthorization. Core's
   post-connect `verify_identity` action reads `/2/users/me`; the verified user ID
   is the host-owned `connection.config.oauth.subject` with lifecycle status
   `connected`, never a user-editable account-ID field.
3. Store the same X app's **app-only bearer token** as `app_bearer_token` in
   this extension's host-managed project provider secrets. Use one X app per
   project; multiple authorized accounts may share that app. Do not paste it in a workflow or model prompt. App-only auth manages
   webhooks; connected-user OAuth creates the private `post.reply.create`
   subscription. Do not substitute one token for the other.
4. Set `FS_PUBLIC_BASE_URL` to a public HTTPS origin reachable by X. Create a
   connection-scoped callback `events` with `configure: false`, then privately
   retain its one-time callback URL. CRC is handled by the generic host callback
   profile. Invoke `configure_webhook` through the ordinary authenticated action
   API, selecting the exact connection and supplying that URL. The built-in
   callback configure/status routes do not hydrate the connection and project
   state needed by this extension; use the ordinary actions described in SETUP.md.
5. Configure lists `GET /2/webhooks` and looks for the exact callback URL **before
   creating anything**. It also checks the verified user's subscriptions before
   creating the account-wide `post.reply.create` subscription. No `post_id`
   qualifier is sent. Exact saved remote IDs remain ownership anchors. Duplicate,
   malformed, incomplete, narrowed or conflicting matches require reconciliation.
6. Inspect `get_webhook_status` through the same ordinary action API. Supply the
   original URL if local state was lost. Ready means `configured: true` and
   `status: ready`. A processed lifecycle response may have `ok: true` while
   `configured: false`, `reconciliation_required: true`, and a safe `error`.
   This persists a partial/unknown lifecycle record using the existing project
   state contract; it never means remote setup succeeded. Stop and reconcile
   before retrying. Account switches require resolving the previous remote setup.
7. Assign the reply workflow and bind an enabled `x_comment_received` trigger to
   the exact `connection_id`. Filtering, opt-out and response decisions stay in
   workflow conditions. Disable local ingress/connection before invoking ordinary
   `remove_webhook` for the saved own IDs. Keep the original callback capability;
   recreating/rotating it changes the URL and requires explicit remote cleanup.

Core checks the raw-body OAuth2 HMAC signature before invoking the extension:
`X-Twitter-Webhooks-Signature-OAuth2: sha256=<base64 digest>`. GET CRC returns
Core's top-level `response_token` JSON and executes no extension action or
workflow. The profile names `webhook_signing_secret` on the selected connection. Both CRC
and the OAuth2 signature use that app's OAuth2 client secret; the app-only bearer
is exclusively API authorization. The extension never verifies signatures itself.
See [X's signing-secret distinction](https://docs.x.com/x-api/webhooks/introduction).

## Actions

| Action | Inputs | Result |
| --- | --- | --- |
| `validate_post` | `text`, optional `canonical_url` | NFC text, twitter-text weighted length, validity/errors; URL stays intact |
| `prepare_image` | project `artifact_handle` | new JPEG artifact, 1200×675, white padding, EXIF orientation, no crop/stretch, ≤5 MB |
| `upload_media` | connection, JPEG artifact, optional `alt_text` | media ID and provider expiry |
| `publish_post` | connection, text, optional link/media IDs | post ID, URL, text |
| `get_post` | connection, post ID | text, author, parent ID, conversation ID and available public context |
| `reply_to_post` | connection, `reply_to_post_id`, text, optional media IDs | one reply under the host operation idempotency contract |

All X IDs are strings. Validation uses the twitter-text-compatible parser with
NFC normalization, weighted Unicode/emoji sequences and detected URLs counting
as 23. The ordinary limit is 280 even for Premium accounts. Overlength text is
returned for editing; it is never silently truncated. Input image bounds are
20 MiB and 40 million pixels. Animated images are refused. Artifact reads and
writes use host-issued grants; filesystem paths and arbitrary URLs are refused.
Media uploads require prepared static JPEG ≤5,000,000 bytes. Alt text is sent
through `/2/media/metadata`. An expired media ID requires an explicit new upload.

The incoming event is `x.comment.received`. Payload fields include
`connection_id`, `account_user_id`, `comment_id`, `comment_text`,
`author_user_id`, `parent_post_id`, `conversation_id`, `created_at`, `comment_url`
and `parent_post_url`. Missing optional context is null, never invented. Parent
and root conversation IDs differ. Metadata retains the delivery UUID for audit;
correlation uses project, connection, connected account and logical comment.
Central dispatch deduplicates that stable source per workflow; a redelivery UUID
does not alter it. Own authored posts/replies and
foreign-account/direct-parent events are suppressed. Receiving an event never
sends a reply. The callback boundary also checks Core's authoritative system
principal and scope before accepting its provider binding. Central dispatch may
ACK an event even if a workflow enqueue fails; there is no guarantee of durable
workflow admission or provider retry for that failure. Check trigger outcomes
and host logs operationally.

## Workflow templates

`artifacts/workflows/x_publish_article.yaml` accepts article title, excerpt or
content, canonical URL, and a cover artifact. Supply the article from WordPress
with an existing configured connector or HTTP step, or pass already published
article fields at manual launch. The extension does not assume a WordPress
plugin exists. Map every X connector step to the project `x_account`
connection. Configure a real authoring agent and its verified model explicitly
where documented in `artifacts/workflows/SETUP.md`.

`x_review_comment.yaml` produces a draft and waits for human approval before
sending. Opt-out and policy conditions precede model generation and sending.
Article context for posts made outside Flow Steward is limited to the actual
post and explicitly retrieved public links; a conversation ID is not an article.
Comments are untrusted data. Instruct the model to ignore instructions contained
in comments and never expose secrets or follow embedded instructions.

Fully automatic AI replies are **disabled by default**. X automation rules
require prior explicit written approval for AI reply bots. Obtain it, provide a
clear opt-out, and record both X permission and owner consent before enabling
connection flags `automated_replies_enabled`, `x_ai_reply_permission_confirmed`,
and `owner_auto_reply_consent`. These are operator attestations, not a technical
check of X's permission. Keep the opt-out registry in your workflow/project
policy and check it on every interaction. Automated workflow calls must set
`automated: true`; the extension refuses them unless all three flags are true.
Do not remove the human approval step until the policy is approved.

## Effects and recovery

`publish_post`, `reply_to_post`, and `upload_media` declare external effects.
No invented X idempotency header is used. The extension makes one network
attempt per request and never retries a mutation automatically. All provider
requests share a 75-second monotonic network budget; absolute SIGALRM and socket
timeouts bound each request to at most 25 seconds. The single-threaded Linux
subprocess has a 120-second host limit. Timers/handlers are restored on errors. Network timeout, disconnect, malformed success, or provider
5xx after a mutation yields `timeout_unknown`. Core blocks blind replay; inspect
X's actual post/media and resolve the host ledger before any deliberate resend.
Per-workflow event dedup and operation idempotency do not prevent two different
workflows or independently keyed calls from replying to the same comment. Enable
one reply workflow per connection and require review; there is no cross-workflow
business-key claim in this platform contract. Successful media
upload followed by failed metadata is also an unknown complete operation; the
response retains the media ID for reconciliation. Authentication, forbidden,
credit, rate, unavailable, not-found and bounded-response errors are distinct,
and provider response bodies/tokens are never echoed to logs or prompts.

## Verify and package

From the matching Core checkout:

```sh
./core/entrypoints/cli/scripts/lint.sh --checks extension-static,extension-tests --extension-root /absolute/path/to/flowsteward_x
```

All tests run in disposable `fs-audit`; no host pytest. Runtime dependencies are
pinned in `requirements.in` and `extension.yaml` with wheel hashes. `wheels/`
contains a universal twitter-text-parser wheel and separate CPython 3.12 Pillow
wheels for Linux AMD64 and ARM64. `dev-wheels/` contains the public SDK wheel;
Core provides the SDK in installed runtime. Packaging is not live X acceptance.
This adaptation has not been tested, statically checked or packaged; previous
candidate evidence does not validate these changes. Verification requires a
separately authorized run against the integrated ADR 0072 host.

Live acceptance needs a real X app, credits, public HTTPS and account access:
OAuth → CRC/registration → publish with image/link → external direct comment on
a post created outside Flow Steward → one workflow → reviewed reply. Automatic
AI sending is not tested without written X permission.

## Provider references (webhook signing checked 2026-11-15)

- [Activity events and private reply auth](https://docs.x.com/x-api/activity/event-payloads)
- [Subscription creation](https://docs.x.com/x-api/activity/create-x-activity-subscription)
- [Webhook setup](https://docs.x.com/x-api/webhooks/quickstart)
- [Media upload](https://docs.x.com/x-api/media/upload-media)
- [Counting characters](https://docs.x.com/fundamentals/counting-characters)
- [X automation rules](https://help.x.com/en/rules-and-policies/x-automation)
- [Current API pricing](https://docs.x.com/x-api/getting-started/pricing)

X credits, webhook events, media, context reads and model usage are separately
billable under current provider terms. Check the developer console before live
runs; this bundle does not hardcode prices or claim a free allowance.
