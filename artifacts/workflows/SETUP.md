# Configure templates before enabling

The packaged workflows and agents start disabled. Import them through the
existing artifact UI, assign them to your project, complete the mappings below,
and run workflow readiness validation. These templates do not create secrets,
connections, verified models or an assumed WordPress integration.

| Template reference | Map to your actual project resource |
| --- | --- |
| Every `connection_binding_jsonb.connection_id: x_account` | exact enabled OAuth `x_account` project connection UUID |
| `x_article_writer` / `x_reply_writer` provider `openai` | installed LLM provider connection + explicitly verified model selected in the agent editor; switch provider if appropriate |
| `x_article_announcement` output | `announcement_text` mapped to `state.announcement_text` |
| `x_comment_reply` output | `reply_text` mapped to `state.reply_text` |
| X trigger `x_comment_received` | same exact selected connection UUID, workflow `x_review_comment` |

Configure the two agents' model/connection with the existing agent editor (no
model is auto-discovered by this bundle), then enable the agents/workflows.
Each model must honor the declared skill output schema. Publish workflow input
is the already published article, canonical URL, and project-scoped cover
artifact. A separate configured WordPress/HTTP retrieval step may populate them.
The media ID is wired into a one-element array on the publish step.

The reply skill receives `comment_text` and the parent post's quoted text in
`parent_post`, mapped from `state.parent_post.text`. Article body and excerpt
remain optional inputs of the announcement skill.

The comment workflow intentionally stops unless `reply_allowed` is true.
Before enabling the trigger, replace the `reply_policy` condition with your
actual policy and add a host-backed opt-out lookup before `check_opt_out` (or
populate `reply_allowed` and `opted_out` from an earlier configured policy
workflow). Missing policy data cannot authorize a send. Configure human approval
routing in `review` and recheck opt-out immediately before approving; rejected
approval stops successfully without sending. Keep `automated: false` for this
human-reviewed path.

For fully automatic sending, first obtain X's explicit written AI-bot approval,
record owner consent, enable all three connection attestations, replace human
approval with your approved policy/opt-out checks, and set `automated: true` on
the send step. Preserve `reply_to_post_id: state.inputs.comment_id` and the
same connection mapping. Enable one reply workflow per connection: this host
has per-workflow event dedup, not a cross-workflow business-key claim.

App bearer storage uses the existing authenticated host endpoint
`POST /api/providers/flowsteward.x/secrets` with JSON fields `project_id`,
`secret_key: app_bearer_token`, `secret_value` (entered privately), and
`active: true`. Supply an exact project; global secret fallback is disabled.
Use the host's secret administration UI or an authenticated API client. Do not
commit or save a request containing the real value in this bundle.

This candidate requires platform API `1.9.0`, including the final ADR 0072
callback profile. The authoring field shape is confirmed; release remains blocked
until the host implementation is integrated and verified. Product version `0.9.18`
is a separate version.

On the X connection, save `webhook_signing_secret` with the matching X app's
**OAuth2 client secret**. This is the key for
`X-Twitter-Webhooks-Signature-OAuth2` and CRC. The legacy OAuth1 consumer secret
belongs to the legacy signature header; this extension does not select it. The
app-only bearer token never signs webhooks. See the official
[introduction](https://docs.x.com/x-api/webhooks/introduction) and
[quickstart](https://docs.x.com/x-api/webhooks/quickstart).

Create the local callback using the authenticated endpoint
`POST /api/extensions/flowsteward.x/callbacks/events`:

```json
{"project_id":"<project UUID>","connection_id":"<X connection UUID>","enabled":true,"configure":false}
```

Keep the returned one-time callback URL/token privately. CRC becomes available
on that registration before X is contacted. Do not rotate/recreate it to retry.
The built-in callback configure/status endpoints do not supply this extension's
normal connection/project-state target. Use **ordinary action invocation**:
`POST /api/extensions/flowsteward.x/action/configure_webhook`, selecting the exact
connection in the target and supplying the URL in the action input:

```json
{"context":{"project_id":"<project UUID>"},"target":{"connection_id":"<X connection UUID>"},"input":{"callback_url":"<one-time callback URL>"}}
```

The same
ordinary surface invokes `get_webhook_status` and `remove_webhook` (these manager
operations stay hidden from workflow steps). For status, `input` may be `{}`
when the saved URL hash exists, or include the original `callback_url` to recover
missing state. Removal takes `input:{}`. Never send
connection config, tokens or an asserted account ID as target data.

Configure first lists the app's webhooks and finds the exact URL, then checks
account subscriptions before creating missing resources. This can rediscover IDs
after a lost response; it is not a durable host setup-intent protocol. Serialize
setup/removal manually: concurrent calls can race between list and create.
A process crash can lose a state update, and an in-flight remote request may
finish later. After a timeout or interruption, wait for it to settle and inspect
X's actual app registrations/subscriptions, then invoke `get_webhook_status`
with the original callback URL before considering another configure. Do not
retry blindly or automatically. Preserve any known owned IDs during cleanup.

Ordinary lifecycle actions return a processed record. Inspect the inner result,
not just `ok` or HTTP status:

| Result | Meaning |
| --- | --- |
| `configured:true`, `status:ready` | exact own CRC-valid webhook and account-wide subscription found |
| `configured:false`, `status:webhook_created` | webhook exists; subscription needs explicit configure |
| `configured:false`, `status:not_configured` | complete exact-URL list found no webhook; operator decides next step |
| `configured:false`, `status:unknown/setup_failed/remove_failed`, `reconciliation_required:true` | stop, inspect the safe error and remote state before retry |
| `status:removed` | saved resources were authoritatively removed or already absent |

A caught partial or ambiguous lifecycle result uses `ok:true` so the existing
host persists its declared connection-scoped `project_state_updates`; it never
claims remote success. Deterministic errors before any accepted/possible
mutation remain `ok:false`. There are no durable host intent receipts, quiet
window enforcement or `reconcile_absent` API flag in this contract.

Status rejects account switches, changed URL hashes, replacement saved IDs,
narrowed filters, nonempty provider errors, inconsistent counts, continuation
and saturated 1000-row subscription lists. Such responses do not prove absence
or authorize a new create. Removal clears a saved ID only after
`data.deleted:true` without errors or an exact resource 404. Partial removal
preserves remaining owned IDs.

Provider event dispatch deduplicates a stable project/connection/account/comment
source per workflow. Two different reply workflows can still send two replies.
Workflow enqueue failures may be logged while the callback is acknowledged;
monitor host trigger outcomes and reconcile failed admission operationally.
