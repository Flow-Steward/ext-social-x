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
same connection mapping so the host's business-effect claim remains effective.

App bearer storage uses the existing authenticated host endpoint
`POST /api/providers/flowsteward.x/secrets` with JSON fields `project_id`,
`secret_key: app_bearer_token`, `secret_value` (entered privately), and
`active: true`. Supply an exact project; global secret fallback is disabled.
Use the host's secret administration UI or an authenticated API client. Do not
commit or save a request containing the real value in this bundle.

Activate the host callback through the existing authenticated endpoint
`POST /api/extensions/flowsteward.x/callbacks/events` with JSON:

```json
{"project_id":"<project UUID>","connection_id":"<X connection UUID>","enabled":true,"configure":true,"configure_action_id":"configure_webhook"}
```

Core creates the local registration, exposes CRC and supplies the canonical
callback URL before invoking setup. Treat the returned callback URL/token as
private capability data. For the returned registration ID, call
`POST /api/extensions/flowsteward.x/callbacks/<registration ID>/status` with
`{"action_id":"get_webhook_status"}`. The same authorized registration action
surface can invoke hidden `remove_webhook` for owned remote cleanup. Disable
local ingress/connection before removing remote resources.

Resume a partial setup on the **same registration ID** through its existing
status endpoint with `{"action_id":"configure_webhook"}`. Core recovers the
canonical callback URL from its encrypted capability. Do not create/rotate a
registration to retry: that would change the callback URL. Core fences a prior
unknown attempt and serializes setup/removal by the owned connection.

After an interrupted request, first invoke `get_webhook_status`. It lists the
app's webhooks using the official `GET /2/webhooks` endpoint and exact host URL
SHA256, and reads subscriptions for the verified user. An exact owned webhook
without a subscription is `resumable`; exact webhook+subscription is `configured`.
Malformed, incomplete, paginated or duplicate matches remain `unknown`. No
unrelated app webhook is adopted or removed. Remote IDs stay only in declared
connection-scoped project state.

A conclusive absent result after an ambiguous attempt requires the host quiet
window and explicit operator reconciliation. Inspect the X app's actual remote
resources first, then call the same status endpoint with
`{"action_id":"get_webhook_status","runtime":{"reconcile_absent":true}}`.
This flag belongs to Core and is removed before extension invocation. Missing
credentials, invalid local setup inputs, or a definitive first-request provider
rejection (such as 401/402/429) return `not_started`, allowing normal correction/
retry without a manual unknown-outcome acknowledgement. An earlier accepted or
possible remote change prevents this safe receipt; HTTP408, 5xx, network timeout
and malformed success stay unknown. A process
crash or any possible remote mutation keeps the durable host intent fenced.

Removal only clears a saved ID after authoritative `data.deleted: true` without
provider errors, or the documented exact resource 404. Partial deletion keeps
remaining owned IDs. Status rejects account switches, narrowed post qualifiers,
nonempty error envelopes, inconsistent counts, continuation tokens and saturated
1000-row subscription pages; these never prove absence or authorize a new create.
