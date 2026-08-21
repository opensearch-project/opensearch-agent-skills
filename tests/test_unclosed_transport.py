"""The transport, which is the whole of the portability claim.

Every managed OpenSearch and every default self-managed install serves HTTPS
behind the security plugin. A client that cannot present credentials or trust a
private CA is portable only in the sense that its endpoint is a flag.

None of this needs a cluster. The parts that do are in
`eval/vendor_neutrality.py`, which runs the same audit against two real
deployment shapes and diffs the reports.
"""

import argparse
import http.client
import io
import ssl
import urllib.error

import pytest

from audit_window import (
    PASSWORD_ENV,
    USERNAME_ENV,
    Endpoint,
    _as_endpoint,
    _get,
    add_connection_args,
    endpoint_from_args,
)

SECRET = "correct-horse-battery-staple"


def _args(**overrides):
    ap = argparse.ArgumentParser()
    add_connection_args(ap)
    return ap.parse_args(_argv(**overrides))


def _argv(**overrides):
    argv = []
    for key, value in overrides.items():
        flag = "--" + key.replace("_", "-")
        if value is True:
            argv.append(flag)
        elif value is not None:
            argv += [flag, value]
    return argv


# -- the password must not be printable ------------------------------------

def test_repr_does_not_print_the_password():
    ep = Endpoint("https://c", username="admin", password=SECRET)
    assert SECRET not in repr(ep)
    assert "***" in repr(ep)


def test_describe_does_not_print_the_password():
    ep = Endpoint("https://c", username="admin", password=SECRET)
    assert SECRET not in ep.describe()


def test_str_is_the_bare_url_so_call_sites_need_no_change():
    ep = Endpoint("https://c:9200", username="admin", password=SECRET)
    assert f"{ep}/an/index" == "https://c:9200/an/index"
    assert SECRET not in f"{ep}"


# -- the auth header --------------------------------------------------------

def test_no_username_means_no_authorization_header():
    assert Endpoint("http://c").auth_header() is None


def test_a_username_without_a_password_sends_nothing_rather_than_half_a_credential():
    assert Endpoint("http://c", username="admin").auth_header() is None


def test_an_empty_password_is_still_a_password():
    # Distinct from absent. A cluster configured with a blank password is a bad
    # idea, but sending no header at all would report the wrong failure.
    assert Endpoint("http://c", username="admin", password="").auth_header() is not None


def test_the_header_is_basic_auth_of_user_colon_password():
    import base64
    ep = Endpoint("http://c", username="admin", password=SECRET)
    expected = base64.b64encode(f"admin:{SECRET}".encode()).decode()
    assert ep.auth_header() == f"Basic {expected}"


# -- TLS --------------------------------------------------------------------

def test_plaintext_endpoints_get_no_ssl_context():
    assert Endpoint("http://c").ssl_context() is None


def test_https_verifies_by_default():
    ctx = Endpoint("https://c").ssl_context()
    assert ctx.verify_mode is ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_insecure_disables_verification_and_says_so_in_the_report():
    ep = Endpoint("https://c", verify_tls=False)
    ctx = ep.ssl_context()
    assert ctx.verify_mode is ssl.CERT_NONE
    # The point of the flag is not that it works, it is that a reader can tell
    # it was used. A run that skipped verification and did not say so leaves no
    # way to know whether the cluster reached is the cluster named.
    assert "VERIFICATION DISABLED" in ep.describe()


def test_a_verified_run_names_what_it_trusted():
    assert "system trust store" in Endpoint("https://c").describe()
    assert "/etc/ca.pem" in Endpoint("https://c", ca_cert="/etc/ca.pem").describe()


def test_scheme_decides_tls_not_a_separate_flag():
    assert Endpoint("HTTPS://c").is_tls
    assert not Endpoint("http://c").is_tls


# -- argument handling ------------------------------------------------------

def test_password_is_not_a_command_line_argument():
    ap = argparse.ArgumentParser()
    add_connection_args(ap)
    with pytest.raises(SystemExit):
        # argv is readable by other processes; if this ever parses, the
        # credential has been put somewhere it can be read from `ps`.
        ap.parse_args(["--password", SECRET])


def test_username_without_the_password_env_refuses_rather_than_sending_none(monkeypatch):
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    with pytest.raises(SystemExit) as exc:
        endpoint_from_args(_args(username="admin"))
    assert PASSWORD_ENV in str(exc.value)


def test_credentials_can_come_entirely_from_the_environment(monkeypatch):
    monkeypatch.setenv(USERNAME_ENV, "admin")
    monkeypatch.setenv(PASSWORD_ENV, SECRET)
    ep = endpoint_from_args(_args())
    assert ep.auth_header() is not None


def test_insecure_flag_reaches_the_endpoint(monkeypatch):
    monkeypatch.delenv(USERNAME_ENV, raising=False)
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    assert endpoint_from_args(_args(endpoint="https://c", insecure=True)).verify_tls is False
    assert endpoint_from_args(_args(endpoint="https://c")).verify_tls is True


def test_a_plain_string_endpoint_still_works():
    ep = _as_endpoint("http://127.0.0.1:9250")
    assert isinstance(ep, Endpoint)
    assert ep.auth_header() is None
    assert _as_endpoint(ep) is ep


# -- failures are sentences, not tracebacks ---------------------------------

class _Response:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.parametrize("code", [401, 403])
def test_an_auth_failure_names_the_environment_variable_to_set(monkeypatch, code):
    def boom(*a, **k):
        raise urllib.error.HTTPError("u", code, "Unauthorized", {}, io.BytesIO(b"Unauthorized"))

    monkeypatch.setattr("audit_window.urllib.request.urlopen", boom)
    with pytest.raises(SystemExit) as exc:
        _get(Endpoint("https://c"), "/i/_mapping")
    assert PASSWORD_ENV in str(exc.value)
    assert "--username" in str(exc.value)


def test_other_http_errors_are_not_reported_as_missing_credentials(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, io.BytesIO(b"no such index"))

    monkeypatch.setattr("audit_window.urllib.request.urlopen", boom)
    with pytest.raises(SystemExit) as exc:
        _get(Endpoint("https://c"), "/i/_mapping")
    assert PASSWORD_ENV not in str(exc.value)
    assert "404" in str(exc.value)


def test_plaintext_against_a_tls_port_is_an_error_message_not_a_traceback(monkeypatch):
    def boom(*a, **k):
        raise http.client.RemoteDisconnected("Remote end closed connection without response")

    monkeypatch.setattr("audit_window.urllib.request.urlopen", boom)
    with pytest.raises(SystemExit) as exc:
        _get(Endpoint("http://c:9251"), "/i/_mapping")
    assert "serves https, not http" in str(exc.value)


def test_an_untrusted_certificate_says_what_to_do_about_it(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError(ssl.SSLCertVerificationError("unable to get local issuer"))

    monkeypatch.setattr("audit_window.urllib.request.urlopen", boom)
    with pytest.raises(SystemExit) as exc:
        _get(Endpoint("https://c"), "/i/_mapping")
    assert "--ca-cert" in str(exc.value)
    assert "--insecure" in str(exc.value)


def test_the_authorization_header_is_actually_attached(monkeypatch):
    seen = {}

    def capture(req, *a, **k):
        seen["auth"] = req.get_header("Authorization")
        seen["context"] = k.get("context")
        return _Response(b"{}")

    monkeypatch.setattr("audit_window.urllib.request.urlopen", capture)
    _get(Endpoint("https://c", username="admin", password=SECRET, verify_tls=False), "/i/_mapping")
    assert seen["auth"].startswith("Basic ")
    assert seen["context"].verify_mode is ssl.CERT_NONE


def test_assemble_uses_the_same_transport():
    # Two transports means a cluster that needs credentials has to be taught
    # twice, and the second one is the one nobody remembers.
    import assemble_traversal
    assert assemble_traversal._request is _get


def test_assemble_post_actually_delegates_rather_than_importing_and_ignoring(monkeypatch):
    # The import above can be present while `_post` quietly builds its own
    # request underneath it, which is exactly what the previous version did.
    import assemble_traversal
    seen = {}

    def fake(endpoint, path, body=None):
        seen["call"] = (str(endpoint), path, body)
        return {}

    monkeypatch.setattr(assemble_traversal, "_request", fake)
    assemble_traversal._post(Endpoint("http://c", username="u", password=SECRET),
                             "/i/_search", {"size": 0})
    assert seen["call"] == ("http://c", "/i/_search", {"size": 0})
