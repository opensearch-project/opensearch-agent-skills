#!/usr/bin/env python3
"""Fetch the facts a premise audit needs, then run Gate 1 over them.

Retrieval is kept out of `premise_audit.py` on purpose: judgment must be
testable without a cluster, and a probe must not be able to quietly widen its
own evidence by issuing another query while deciding.

Portability note: no inline Painless scripting is used anywhere. Managed
OpenSearch deployments frequently disable it, and the skill has to work across
distributions. Ingest lag is measured by sampling documents and differencing
the two clocks locally -- slower, but it runs everywhere.

The second portability fact is the security plugin. Every managed OpenSearch
and every default self-managed install serves HTTPS and answers 401 without
credentials, so a client that speaks only plaintext HTTP works on exactly one
deployment shape: a demo container with security switched off. `Endpoint`
carries the connection settings so that the ten call sites below never have to
know about them.

Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import ssl
import statistics
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

sys.path.insert(0, __file__.rsplit("audit_window.py", 1)[0])
from premise_audit import Observation, Provenance, audit  # noqa: E402

DEFAULT_ENDPOINT = "http://127.0.0.1:9250"
SAMPLE_SIZE = 200

#: Read from the environment rather than argv. A password passed as a command
#: line argument is visible to every other process on the host for the lifetime
#: of the run, and lands in shell history besides.
PASSWORD_ENV = "OPENSEARCH_PASSWORD"
USERNAME_ENV = "OPENSEARCH_USERNAME"


@dataclass(frozen=True)
class Endpoint:
    """A cluster URL and what is needed to talk to it.

    Stringifies to the bare URL so that every `f"{endpoint}{path}"` below keeps
    working unchanged, which is why the auth support did not have to be threaded
    through ten function signatures.
    """

    url: str
    username: Optional[str] = None
    password: Optional[str] = None
    ca_cert: Optional[str] = None
    verify_tls: bool = True

    def __str__(self) -> str:
        return self.url

    def __repr__(self) -> str:
        # The default dataclass repr prints every field, and this one holds a
        # password. Anything that formats an object for a log or a traceback
        # reaches for __repr__, so the redaction has to live here rather than at
        # the call sites that would have to remember.
        return (f"Endpoint(url={self.url!r}, username={self.username!r}, "
                f"password={'***' if self.password else None}, "
                f"ca_cert={self.ca_cert!r}, verify_tls={self.verify_tls})")

    @property
    def is_tls(self) -> bool:
        return self.url.lower().startswith("https://")

    def describe(self) -> str:
        """One line for the report. A run that skipped certificate verification
        has to say so: the reader cannot otherwise tell whether the cluster it
        reached is the cluster it named."""
        auth = f"basic auth as `{self.username}`" if self.username else "no credentials"
        if not self.is_tls:
            return f"{self.url}, plaintext, {auth}"
        if not self.verify_tls:
            return f"{self.url}, TLS with VERIFICATION DISABLED, {auth}"
        trust = f"CA bundle {self.ca_cert}" if self.ca_cert else "system trust store"
        return f"{self.url}, TLS verified against {trust}, {auth}"

    def ssl_context(self):
        if not self.is_tls:
            return None
        if not self.verify_tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        return ssl.create_default_context(cafile=self.ca_cert)

    def auth_header(self) -> Optional[str]:
        if not self.username or self.password is None:
            return None
        token = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("ascii")
        return f"Basic {token}"


def _as_endpoint(endpoint) -> Endpoint:
    """Accept a plain string so tests and callers that never needed auth stay simple."""
    return endpoint if isinstance(endpoint, Endpoint) else Endpoint(str(endpoint))


def _get(endpoint, path, body=None):
    ep = _as_endpoint(endpoint)
    url = f"{ep}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    auth = ep.auth_header()
    if auth:
        req.add_header("Authorization", auth)
    try:
        with urllib.request.urlopen(req, timeout=30, context=ep.ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")[:300]
        if exc.code in (401, 403):
            raise SystemExit(
                f"OpenSearch returned {exc.code} for {path}: the cluster requires credentials. "
                f"Pass --username and set ${PASSWORD_ENV}. Detail: {detail}")
        raise SystemExit(f"OpenSearch returned {exc.code} for {path}: {detail}")
    except urllib.error.URLError as exc:
        hint = ""
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            hint = (" -- the certificate is not signed by anything in the trust store. Pass "
                    "--ca-cert with the cluster's CA, or --insecure to skip verification "
                    "(which this tool then prints in every report).")
        raise SystemExit(f"Cannot reach OpenSearch at {ep}: {exc.reason}{hint}")
    except http.client.HTTPException as exc:
        # A plaintext request to a TLS port dies here rather than in URLError,
        # and an uncaught traceback is a worse answer than a sentence.
        raise SystemExit(
            f"Cannot reach OpenSearch at {ep}: {type(exc).__name__}: {exc}. "
            "A cluster with the security plugin enabled serves https, not http.")


def _range(field, gte, lt):
    return {"range": {field: {"gte": gte, "lt": lt}}}


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _parse_iso(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def discover_fields(endpoint, index, metric):
    """Which concrete indices does this pattern resolve to, and what are the clocks?"""
    mapping = _get(endpoint, f"/{index}/_mapping")
    resolved = sorted(mapping.keys())
    metric_types, date_fields = {}, set()
    for name, spec in mapping.items():
        props = spec.get("mappings", {}).get("properties", {})
        metric_types[name] = props.get(metric, {}).get("type")
        date_fields |= {f for f, p in props.items() if p.get("type") == "date"}
    return resolved, metric_types, sorted(date_fields)


#: Two estimators of the same percentile, both core to every OpenSearch
#: distribution, neither an extra dependency and neither an extra round trip --
#: they are sub-aggregations of the same request. Which one a dashboard uses is
#: a choice that is almost never written down, and at incident-window sample
#: sizes it changes the number.
PRIMARY_ESTIMATOR = "tdigest"
ALT_ESTIMATOR = "hdr"
HDR_SIGNIFICANT_DIGITS = 3


def _percentile_aggs(metric, percents=(99,)):
    return {
        PRIMARY_ESTIMATOR: {"percentiles": {"field": metric, "percents": list(percents)}},
        ALT_ESTIMATOR: {"percentiles": {"field": metric, "percents": list(percents),
                                        "hdr": {"number_of_significant_value_digits": HDR_SIGNIFICANT_DIGITS}}},
    }


def _read(agg_block, estimator):
    vals = agg_block[estimator]["values"]
    return list(vals.values())[0]


def index_max_timestamp(endpoint, index, time_field):
    """The newest event the index actually holds. `None` when it holds none.

    This is the clock the scan window hangs from. See `resolve_scan_window`.
    """
    body = {"size": 0, "aggs": {"newest": {"max": {"field": time_field}}}}
    res = _get(endpoint, f"/{index}/_search", body)
    epoch_ms = res["aggregations"]["newest"]["value"]
    if epoch_ms is None:
        return None
    return datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)


def _floor_to_bucket(dt, bucket_minutes):
    """`fixed_interval` buckets are aligned to the epoch, not to the query range."""
    interval = bucket_minutes * 60
    epoch = dt.timestamp()
    return datetime.fromtimestamp(epoch - (epoch % interval), tz=timezone.utc)


def _ceil_to_bucket(dt, bucket_minutes):
    floored = _floor_to_bucket(dt, bucket_minutes)
    return floored if floored == dt else floored + timedelta(minutes=bucket_minutes)


def resolve_scan_window(endpoint, index, time_field, bucket_minutes, lookback_hours, as_of=None):
    """Fix the scan range to a clock that can be named, and to whole buckets.

    Two defects live in the obvious version of this, `now - lookback .. now`,
    and the evaluation hit both.

    **The wall clock is not a property of the data.** Run the same command
    against the same static index twice, ten minutes apart, and the range moves
    with the typing. Different buckets are compared, and the verdict can change
    with nothing about the system having changed. A tool whose whole position is
    that a premise must be auditable cannot leave its own premise -- *which
    window* -- selected by an input nobody records.

    **An unaligned edge slices a bucket in half.** `now` almost never lands on a
    bucket boundary, so the oldest bucket in range is returned holding whatever
    fraction of its documents happened to fall to the right of the cut. Read
    whole it may be n=200 with a p99 *below* baseline; read sliced it is n=40,
    and `sample_size_collapse` refutes the observation on volume the query
    removed. The collapse is manufactured by the reader.

    So: anchor on `--as-of` when the caller names a moment, otherwise on the
    newest document in the index; then snap both edges outward to bucket
    boundaries, so every bucket returned is queried whole. What remains partial
    is partial in the data, which is a fact about the system and is allowed to
    be judged as one.

    Returns `(gte, lt, anchor, anchor_source)` -- three datetimes and a string
    naming the clock, which travels into the report.
    """
    if as_of:
        anchor = _parse_iso(as_of)
        source = "--as-of, supplied by the caller"
    else:
        anchor = index_max_timestamp(endpoint, index, time_field)
        if anchor is None:
            raise SystemExit(f"{index} holds no `{time_field}` values, so there is no window to scan.")
        source = f"newest `{time_field}` in {index}"
    lt = _ceil_to_bucket(anchor, bucket_minutes)
    gte = _floor_to_bucket(lt - timedelta(hours=lookback_hours), bucket_minutes)
    return gte, lt, anchor, source


def bucket_stats(endpoint, index, time_field, metric, bucket_minutes, gte, lt):
    body = {
        "size": 0,
        "query": _range(time_field, _iso(gte), _iso(lt)),
        "aggs": {
            "per_bucket": {
                "date_histogram": {"field": time_field, "fixed_interval": f"{bucket_minutes}m", "min_doc_count": 1},
                "aggs": _percentile_aggs(metric),
            }
        },
    }
    res = _get(endpoint, f"/{index}/_search", body)
    out = []
    for b in res["aggregations"]["per_bucket"]["buckets"]:
        p99 = _read(b, PRIMARY_ESTIMATOR)
        if p99 is None:
            continue
        alt = _read(b, ALT_ESTIMATOR)
        out.append({"start": b["key_as_string"], "n": b["doc_count"], "p99": round(p99, 2),
                    "p99_alt": round(alt, 2) if alt is not None else None})
    return out


def value_as_reported(endpoint, index, time_field, metric, second_clock, gte, lt, reported_at):
    """The same statistic, over the documents that had landed when the claim was made.

    `observation_moment` refutes an observation whose window had not finished
    when it was judged, and the refutation is right: the auditor and the
    reporter are not looking at the same documents. What it does *not* say is
    whether the reporter's number was wrong -- and that is exactly the sentence
    a narration reaches for next.

    Left to improvise, it improvises. In the agent A/B two runs of the same
    skill rebuilt the same 46-document slice and read different statistics off
    it: p99 came back 77% above the settled value and the run called the report
    untrustworthy; p50 came back equal to it and the run called the report fine.
    Both numbers were real. Nothing in the skill said which one answers the
    question, so which framing appeared depended on which percentile got typed.

    So it is computed instead of left open, and computed as the only reading
    that answers the claim: **the same statistic the claim is about**, over the
    documents an ingest clock says existed at the claimed moment.

    What this is, precisely -- and it is not what it is tempting to call it:
    the set of documents whose *ingest* clock is before `reported_at`. That is
    not "what the alert saw". A refresh interval, the alert's own query lag, and
    a shard that had not caught up all sit between the two. It is the closest
    reconstruction the index can support, and it is labelled as that in the
    report rather than as the reporter's screen.

    Returns `(value, n)`, or `(None, None)` when the index has no second clock
    to ask -- absent, not zero.
    """
    if not second_clock or not reported_at:
        return None, None
    body = {
        "size": 0,
        "query": {"bool": {"filter": [
            _range(time_field, gte, lt),
            {"range": {second_clock: {"lt": reported_at}}},
        ]}},
        "aggs": _percentile_aggs(metric),
    }
    res = _get(endpoint, f"/{index}/_search", body)
    n = res["hits"]["total"]["value"]
    if not n:
        return None, 0
    value = _read(res["aggregations"], PRIMARY_ESTIMATOR)
    return (round(value, 2) if value is not None else None), n


def composition(endpoint, index, time_field, dim, gte, lt):
    body = {
        "size": 0,
        "query": _range(time_field, gte, lt),
        "aggs": {"c": {"terms": {"field": dim, "size": 50}}},
    }
    res = _get(endpoint, f"/{index}/_search", body)
    buckets = res["aggregations"]["c"]["buckets"]
    total = sum(b["doc_count"] for b in buckets)
    if not total:
        return None
    return {b["key"]: b["doc_count"] / total for b in buckets}


def ingest_lag_p50(endpoint, index, time_field, second_clock, gte, lt):
    body = {
        "size": SAMPLE_SIZE,
        "query": _range(time_field, gte, lt),
        "_source": [time_field, second_clock],
    }
    res = _get(endpoint, f"/{index}/_search", body)
    lags = []
    for hit in res["hits"]["hits"]:
        src = hit["_source"]
        if time_field not in src or second_clock not in src:
            continue
        t0 = datetime.fromisoformat(src[time_field].replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(src[second_clock].replace("Z", "+00:00"))
        lags.append((t1 - t0).total_seconds())
    return statistics.median(lags) if lags else None


def build_observation(endpoint, index, metric, time_field, dim, bucket_minutes, lookback_hours,
                      focus_window=None, reported_at=None, as_of=None):
    resolved, metric_types, date_fields = discover_fields(endpoint, index, metric)
    gte, lt, anchor, anchor_source = resolve_scan_window(
        endpoint, index, time_field, bucket_minutes, lookback_hours, as_of)
    buckets = bucket_stats(endpoint, index, time_field, metric, bucket_minutes, gte, lt)
    if len(buckets) < 2:
        raise SystemExit(
            f"Not enough data in {index} between {_iso(gte)} and {_iso(lt)} to compare anything "
            f"({lookback_hours}h ending at {_iso(anchor)}, anchored on {anchor_source})."
        )

    if focus_window:
        # Someone named this window. The audit examines what they claimed.
        target = _parse_iso(focus_window)
        focus = next((b for b in buckets if _parse_iso(b["start"]) == target), None)
        if focus is None:
            raise SystemExit(
                f"No {bucket_minutes}m bucket starts at {focus_window} in the last {lookback_hours}h.\n"
                f"Available bucket starts: {buckets[0]['start']} .. {buckets[-1]['start']}"
            )
        provenance = Provenance.EXTERNAL_REPORT
    else:
        # No window was reported, so this tool picks the worst one -- and says
        # so. Every dataset has a maximum; selecting it and then confirming it
        # is not an artifact would be drawing the target around the arrows.
        focus = max(buckets, key=lambda b: b["p99"])
        provenance = Provenance.SELF_SELECTED

    others = [b for b in buckets if b is not focus]
    baseline_p99 = statistics.median(b["p99"] for b in others)
    baseline_n = int(statistics.median(b["n"] for b in others))

    # The second estimator's baseline is taken the same way as the first, over
    # the same buckets. Mixing methods across focus and baseline would put the
    # divergence between them rather than between the rulers.
    alt_focus = focus.get("p99_alt")
    alt_others = [b["p99_alt"] for b in others if b.get("p99_alt") is not None]
    alt_baseline = statistics.median(alt_others) if alt_others else None
    if alt_focus is None or alt_baseline is None:
        alt_focus = alt_baseline = None

    f_start = focus["start"]
    f_end = _iso(datetime.fromisoformat(f_start.replace("Z", "+00:00")) + timedelta(minutes=bucket_minutes))
    b_start = others[0]["start"]
    b_end = _iso(datetime.fromisoformat(others[-1]["start"].replace("Z", "+00:00")) + timedelta(minutes=bucket_minutes))

    second_clock = next((f for f in date_fields if f != time_field), None)
    as_reported, as_reported_n = value_as_reported(
        endpoint, index, time_field, metric, second_clock, f_start, f_end, reported_at)

    return Observation(
        metric=metric,
        focus_value=focus["p99"],
        baseline_value=baseline_p99,
        focus_value_alt=alt_focus,
        baseline_value_alt=alt_baseline,
        estimator=PRIMARY_ESTIMATOR,
        estimator_alt=ALT_ESTIMATOR if alt_focus is not None else None,
        provenance=provenance,
        window_start=f_start,
        window_end=f_end,
        reported_at=reported_at,
        focus_count=focus["n"],
        baseline_typical_count=baseline_n,
        focus_composition=composition(endpoint, index, time_field, dim, f_start, f_end) if dim else None,
        baseline_composition=composition(endpoint, index, time_field, dim, b_start, b_end) if dim else None,
        second_clock_field=second_clock,
        focus_ingest_lag_p50_s=ingest_lag_p50(endpoint, index, time_field, second_clock, f_start, f_end) if second_clock else None,
        baseline_ingest_lag_p50_s=ingest_lag_p50(endpoint, index, time_field, second_clock, b_start, b_end) if second_clock else None,
        resolved_indices=resolved,
        metric_field_types=metric_types,
        scan_window_start=_iso(gte),
        scan_window_end=_iso(lt),
        scan_anchor=_iso(anchor),
        scan_anchor_source=anchor_source,
        focus_value_as_reported=as_reported,
        focus_count_as_reported=as_reported_n,
    ), focus


def add_connection_args(ap: argparse.ArgumentParser) -> None:
    """Connection flags, shared so every entry point speaks to a cluster the same way."""
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--username", default=None,
                    help=f"Basic-auth user. The password is read from ${PASSWORD_ENV}, never from "
                         "argv, because argv is visible to other processes. Both may also be "
                         f"supplied as ${USERNAME_ENV}/${PASSWORD_ENV}.")
    ap.add_argument("--ca-cert", default=None,
                    help="PEM bundle to verify the cluster's certificate against.")
    ap.add_argument("--insecure", action="store_true",
                    help="Skip TLS certificate verification. Every report from such a run says so.")


def endpoint_from_args(args) -> Endpoint:
    username = getattr(args, "username", None) or os.environ.get(USERNAME_ENV)
    password = os.environ.get(PASSWORD_ENV)
    if username and password is None:
        raise SystemExit(
            f"--username was given but ${PASSWORD_ENV} is not set. The password is deliberately "
            "not a command line argument: argv is readable by other processes on the host.")
    return Endpoint(
        url=args.endpoint,
        username=username,
        password=password,
        ca_cert=getattr(args, "ca_cert", None),
        verify_tls=not getattr(args, "insecure", False),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Gate 1 (premise audit) over an OpenSearch index.")
    ap.add_argument("--index", required=True)
    ap.add_argument("--metric", default="latency_ms")
    ap.add_argument("--time-field", default="@timestamp")
    ap.add_argument("--dimension", default="endpoint", help="Categorical field for the population check")
    ap.add_argument("--bucket-minutes", type=int, default=10)
    ap.add_argument("--lookback-hours", type=int, default=6)
    ap.add_argument("--focus-window", default=None,
                    help="ISO start of the window someone reported, e.g. 2026-08-01T14:20:00Z. "
                         "Without it this tool selects the worst bucket itself and can never "
                         "return SUBSTANTIATED.")
    ap.add_argument("--reported-at", default=None,
                    help="ISO moment the observation was made. An external report without one "
                         "cannot be verified as a report at all.")
    ap.add_argument("--as-of", default=None,
                    help="ISO moment the lookback ends. Without it the window is anchored on the "
                         "newest document in the index -- never on the wall clock, so the same "
                         "command over the same data returns the same window whenever it is run.")
    add_connection_args(ap)
    args = ap.parse_args()

    endpoint = endpoint_from_args(args)
    obs, focus = build_observation(endpoint, args.index, args.metric, args.time_field,
                                   args.dimension, args.bucket_minutes, args.lookback_hours,
                                   args.focus_window, args.reported_at, args.as_of)
    report = audit(obs)
    print(f"INDEX: {args.index}    FOCUS WINDOW: {focus['start']} (+{args.bucket_minutes}m)    "
          f"PROVENANCE: {obs.provenance.value}")
    print(f"TRANSPORT: {endpoint.describe()}")
    print(report.to_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
