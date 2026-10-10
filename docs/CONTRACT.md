# MoneyTrail shared contract

Backend Python package `backend`. Frontend React+TS/Vite in `frontend`. API port 8000; organization ports sender 8101, processor 8102, recipient 8103.

Money is integer USD cents. Synthetic payment reference `PAY-104`. Scenarios `incorrect`, `valid`, `missing`. All timestamps ISO strings.

Evidence JSON: `{id, organization, kind, reference, title, content, amount_minor?, currency:'USD', timestamp, metadata:{...}}`. Kinds `debit`, `invoice`, `instruction`, `incoming`, `fee`, `settlement`, `agreement`, `amendment`, `credit`, `allocation`. Agreement metadata `{fee_minor,effective_date,issuer,authorized:true}`. Metadata fields are authoritative synthetic system fields; prose extraction still evaluated separately. Conflicting/missing fields escalate.

Case JSON: `{id,version,scenario,status,mode,question,sent_minor,received_minor,difference_minor,unsupported_minor,records:Evidence[],findings:Finding[],recommendation:Recommendation|null,events:Event[],graph:{nodes:Node[],edges:Edge[]},metrics:{...},approval:null|object}`.

Finding `{id,status:'verified'|'conflicting'|'unresolved',title,detail,evidence_ids:string[]}`. Recommendation `{action:'close'|'request_correction'|'request_evidence',amount_minor,summary,evidence_ids:string[]}`. Status `created|investigating|review|incomplete|approved|error`. Mode `deterministic` (explicitly labeled deterministic verification, not live AI), `live` (actual HF model), `replay` (explicit saved event playback).

Graph Node `{id,label,kind,organization,x,y,size,color,evidence_id?,amount_minor?,background?:boolean}`. Edge `{id,source,target,kind:'money'|'evidence'|'request',label?}`. Node IDs are stable evidence IDs or `org:sender`, `org:processor`, `org:recipient`. No invented edges.

Event `{seq,case_id,version,type,timestamp,message,data}`. Type `status|request|evidence|finding|recommendation|approval|error|model`. SSE event name `update`, data is Event. Event data on evidence `{record,nodes,edges}`, finding `{finding}`, recommendation `{recommendation,unsupported_minor}`, status `{status}`, model `{...}`. Client can fetch entire case after any event; dedup by version+seq. GET events supports `after` and Last-Event-ID (integer). No confidential chain of thought.

Endpoints:
- GET /health -> {status,model_configured,model,mode,...}
- GET /overview -> {graph,records,count} (sender-only 1200 history records)
- POST /cases body {scenario,question?,mode?:'deterministic'|'live'} -> Case; auto starts background investigation
- GET /cases/{id} -> Case
- GET /cases/{id}/events -> SSE; terminates on completed stream status, reconnect allowed
- POST /cases/{id}/evidence body {version,amendment:'permit_350'} -> Case, version++ re-investigation
- POST /cases/{id}/approve body {version,action,idempotency_key} -> {case,approval}; invalid version 409
- POST /cases/{id}/replay -> Case, new replay case using prior recorded events, never calls models
- POST /transcribe multipart audio -> {text}; unavailable returns clear 503

Organization services expose official SDK A2A JSON-RPC. Request DataPart payload `{operation:'retrieve'|'amend'|'correction',case_id,scenario,reference,kind?,version?,idempotency_key?,amount_minor?}`. Each auth token scopes case/reference via HMAC capability header issued by coordinator. Responses DataPart `{records:[Evidence]}` or correction receipt. Services read only own sqlite. Don't expose general database tools.

Data/verifier workstream owns `backend/data.py`, `backend/verify.py`, `scripts/evaluate.py`, related tests. Interface `generate(root:Path)` creates root/{sender,processor,recipient}/records.sqlite and separate root/evaluator/ground_truth.json. SQLite table records(id TEXT PRIMARY KEY, scenario TEXT, reference TEXT, payload TEXT). sender history scenario `history`; investigation records separate per scenario; IDs unique. `verify(records:list[dict]) -> {findings:list,recommendation:dict,unsupported_minor:int|null}`. No evaluator access from runtime.
