"""Settings load from env without a real .env file present."""

from ckg.config import get_settings


def test_settings_load():
    s = get_settings()
    assert s.bootstrap_token == "test-bootstrap-token"
    assert s.embedding_dim == 384
    assert "python" in s.enabled_language_list


def test_postgres_dsn_built():
    s = get_settings()
    assert s.postgres_dsn.startswith("postgresql+psycopg://")
