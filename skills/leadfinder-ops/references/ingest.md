# Ingest Reference — Wiring Lead Sources to the Index

How to map common small-business lead sources into the `leads` schema.

## Web forms (Contact-form-7, WPForms, HubSpot forms, Jobber)

Webhook → lambda/worker → bulk index. Map:

| Form field | Schema field |
|---|---|
| name | `customer_name` |
| email or phone | `contact` |
| message / description | `message` |
| form id | `source` (`web_form`) |
| timestamp | `received_at` (ISO-8601 with timezone) |

## Missed calls (VoIP: RingCentral, Grasshopper, Ooma)

VoIP platforms fire a webhook on missed call. Leave `message` empty and set
`source: "missed_call"`. Optionally attach the voicemail transcript:

```json
{
  "lead_id": "mc_20260814_1832",
  "received_at": "2026-08-14T18:32:00-07:00",
  "source": "missed_call",
  "customer_name": "(619) 555-0142",
  "contact": "+16195550142",
  "message": "voicemail transcript: 'hi my ac is out, call me back'",
  "category": "urgent",
  "responded_at": null,
  "next_action": "call_back"
}
```

## Email inboxes (Gmail API watch, IMAP IDLE)

For each inbound message to sales@/info@ that is not a reply from us:

| Email | Schema |
|---|---|
| From | `contact` + parsed name → `customer_name` |
| Subject + body | `message` |
| Date | `received_at` |
| thread has our reply? | set `responded_at` to reply timestamp |

## Classification at ingest (optional)

Route through any classifier to populate `category`:
`quote_request | scheduling | complaint | urgent | spam | other`.
A keyword fallback (see below) is fine to start:

```python
URGENT = ["no ac", "gas smell", "carbon monoxide", "leak", "fire", "smoke",
          "95 degrees", "freezing", "infant", "elderly", "baby", "emergency"]
SPAM = ["viagra", "casino", "crypto", "click here", "free money", "seo services"]
```

Classify BEFORE indexing so recovery queries can filter by `category` at query
time. Mis-classifications are fixed with a partial update (`POST /leads/_update/<id>`),
never by re-ingesting.

## Embeddings at ingest (optional, enables semantic search)

1. Compute `message_embedding` with any 384-dim sentence model
   (all-MiniLM-L6-v2 via sentence-transformers, or a hosted embedding API).
2. Include it in the index request. The hnsw graph updates automatically.
3. Store which model produced it in a `embedding_model` metadata field if you
   ever switch models (vectors must be rebuilt per model).
