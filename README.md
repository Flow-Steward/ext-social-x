# X extension 1.0.0

SDK-only `flowsteward.x`, Python 3.12, `extension_host_v2`. The official X API
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
   receives the client secret, refresh token, or authorization code.
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
4. Set `FS_PUBLIC_BASE_URL` to a public HTTPS origin reachable by X. Prepare a
   connection-scoped callback registration for callback `events` in Core, then
   run its hidden `configure_webhook` action through the callback setup API/UI.
   Core makes GET CRC available **before** contacting X and durably records a
   setup intent before any remote mutation. Setup actions require the host-owned
   callback target and cannot be called through ordinary workflow/action APIs. The action registers
   `/2/webhooks`, requires its `valid` CRC result, then creates
   `/2/activity/subscriptions` with `event_type: post.reply.create`,
   `filter: {user_id: <verified subject>}`, and the new webhook ID. It sends no
   `post_id` qualifier. Status/resume uses official `GET /2/webhooks`, selects
   only the exact owned ID/callback hash, and never assumes GET-by-ID exists. It never adopts or deletes another registration.
5. Check hidden `get_webhook_status`. Only a validated own webhook with a saved
   own subscription is ready. A changed OAuth account or callback capability
   requires reconciling/removing the previous remote setup first. Remote IDs and status are returned as declared,
   connection-scoped `project_state_updates`; no private database exists.
6. Assign the reply workflow to the project and create an enabled
   `x_comment_received` trigger selecting the exact `connection_id`. Content,
   author, topic, language, opt-out and response decisions belong in workflow
   conditions. Disabling the connection or ingress immediately stops local
   dispatch. Use `remove_webhook` for the saved own subscription/webhook IDs;
   remote failures remain visible and can be retried after checking status.
   Resume through the same registration ID; see SETUP.md for durable unknown
   fencing, exact remote reconciliation and the host-only absence confirmation.

Core checks the raw-body OAuth2 HMAC signature before invoking the extension:
`X-Twitter-Webhooks-Signature-OAuth2: sha256=<base64 digest>`. GET CRC returns
Core's top-level `response_token` JSON and executes no extension action or
workflow. Credentials from incompatible applications cannot complete CRC.

## Actions

| Action | Inputs | Result |
| --- | --- | --- |
| `validate_post` | `text`, optional `canonical_url` | NFC text, twitter-text weighted length, validity/errors; URL stays intact |
| `prepare_image` | project `artifact_handle` | new JPEG artifact, 1200×675, white padding, EXIF orientation, no crop/stretch, ≤5 MB |
| `upload_media` | connection, JPEG artifact, optional `alt_text` | media ID and provider expiry |
| `publish_post` | connection, text, optional link/media IDs | post ID, URL, text |
| `get_post` | connection, post ID | text, author, parent ID, conversation ID and available public context |
| `reply_to_post` | connection, `reply_to_post_id`, text, optional media IDs | one reply, with host business-effect protection per inbound comment |

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
correlation uses the connected account plus logical comment, so redelivery with
a new UUID does not produce another workflow. Own authored posts/replies and
foreign-account/direct-parent events are suppressed. Receiving an event never
sends a reply. Core durably admits workflow execution before ACK.

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
A reply's business key is `reply_to_post_id`, so parallel workflows cannot send
two replies to the same interaction in the same connection. Successful media
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
See the task report for actual validation, packaging and architecture evidence.

Live acceptance needs a real X app, credits, public HTTPS and account access:
OAuth → CRC/registration → publish with image/link → external direct comment on
a post created outside Flow Steward → one workflow → reviewed reply. Automatic
AI sending is not tested without written X permission.

## Provider references (checked 2026-11-14)

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
