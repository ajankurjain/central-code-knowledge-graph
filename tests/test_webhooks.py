"""Webhook signature verification + payload parsing.

These tests don't touch Postgres / Celery — they exercise the pure
verify/parse functions in `ckg.services.webhooks`.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from ckg.services.webhooks import detect_provider, parse, verify


def test_detect_provider_from_headers():
    assert detect_provider({"X-GitHub-Event": "push"}) == "github"
    assert detect_provider({"X-Hub-Signature-256": "sha256=x"}) == "github"
    assert detect_provider({"X-Gitlab-Event": "Push Hook"}) == "gitlab"
    assert detect_provider({"X-Gitlab-Token": "t"}) == "gitlab"
    assert detect_provider({"X-Event-Key": "repo:push"}) == "bitbucket"
    assert detect_provider({"Content-Type": "application/json"}) is None


def test_verify_github_hmac_sha256():
    secret = "shhh"
    body = b'{"hello": "world"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify("github", {"X-Hub-Signature-256": sig}, body, secret, None) is True
    # tampered body → reject
    assert verify("github", {"X-Hub-Signature-256": sig}, body + b"x", secret, None) is False


def test_verify_github_rejects_bad_prefix():
    assert verify("github", {"X-Hub-Signature-256": "sha1=deadbeef"}, b"x", "s", None) is False


def test_verify_gitlab_token_compare():
    assert verify("gitlab", {"X-Gitlab-Token": "abc"}, b"{}", "abc", None) is True
    assert verify("gitlab", {"X-Gitlab-Token": "no"}, b"{}", "abc", None) is False


def test_verify_bitbucket_query_token():
    assert verify("bitbucket", {"X-Event-Key": "repo:push"}, b"{}", "abc", "abc") is True
    assert verify("bitbucket", {"X-Event-Key": "repo:push"}, b"{}", "abc", "no") is False


def test_parse_github_push():
    body = json.dumps({
        "ref": "refs/heads/main",
        "repository": {"full_name": "acme/foo"},
    }).encode()
    event = parse("github", {"X-GitHub-Event": "push"}, body)
    assert event is not None
    assert event.full_name == "acme/foo"
    assert event.ref == "refs/heads/main"


def test_parse_github_ignores_ping_and_other_events():
    body = b"{}"
    assert parse("github", {"X-GitHub-Event": "ping"}, body) is None
    assert parse("github", {"X-GitHub-Event": "issues"}, body) is None


def test_parse_gitlab_push():
    body = json.dumps({
        "ref": "refs/heads/main",
        "project": {"path_with_namespace": "g/p"},
    }).encode()
    event = parse("gitlab", {"X-Gitlab-Event": "Push Hook"}, body)
    assert event is not None
    assert event.full_name == "g/p"


def test_parse_bitbucket_push():
    body = json.dumps({
        "repository": {"full_name": "ws/repo"},
        "push": {"changes": [{"new": {"name": "main"}}]},
    }).encode()
    event = parse("bitbucket", {"X-Event-Key": "repo:push"}, body)
    assert event is not None
    assert event.full_name == "ws/repo"
    assert event.ref == "refs/heads/main"
