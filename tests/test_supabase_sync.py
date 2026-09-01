"""Cloud/export drift detection and prune (mocked HTTP; no cloud)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

URL = "https://example.supabase.co"
KEY = "test-service-role"


def _client_returning(pages):
    """Mock httpx.Client whose .get pops successive JSON pages."""
    queue = list(pages)

    def _get(endpoint, headers=None, params=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = queue.pop(0) if queue else []
        resp.text = ""
        return resp

    client = MagicMock()
    client.__enter__.return_value.get.side_effect = _get
    client.__exit__.return_value = False
    return client


def test_fetch_cloud_ids_paginates(upsert_mod):
    page1 = [{"id": f"c_{i}"} for i in range(1000)]
    page2 = [{"id": "c_1000"}]
    client = _client_returning([page1, page2])
    with patch("httpx.Client", return_value=client):
        got = upsert_mod.fetch_cloud_ids(URL, KEY, ["C"])
    assert len(got["C"]) == 1001
    assert "c_1000" in got["C"]
    calls = client.__enter__.return_value.get.call_args_list
    assert calls[0][1]["params"]["offset"] == 0
    assert calls[1][1]["params"]["offset"] == 1000


def test_drift_reports_stale_and_missing(upsert_mod):
    client = _client_returning([[{"id": "keep"}, {"id": "stale"}]])
    with patch("httpx.Client", return_value=client):
        drift = upsert_mod._drift(URL, KEY, ["C"], {"C": {"keep", "fresh"}})
    assert drift["C"]["stale"] == {"stale"}
    assert drift["C"]["missing"] == {"fresh"}


def test_report_drift_exit_codes(upsert_mod):
    in_sync = _client_returning([[{"id": "a"}]])
    with patch("httpx.Client", return_value=in_sync):
        assert upsert_mod._report_drift(URL, KEY, ["C"], {"C": {"a"}}) == 0

    drifted = _client_returning([[{"id": "a"}, {"id": "b"}]])
    with patch("httpx.Client", return_value=drifted):
        assert upsert_mod._report_drift(URL, KEY, ["C"], {"C": {"a"}}) == 1


def test_prune_deletes_only_stale_ids(upsert_mod):
    cloud = [{"id": f"c_{i}"} for i in range(10)]
    local = {"C": {f"c_{i}" for i in range(9)}}  # c_9 is stale -> 10% of cloud
    deleted = []
    with patch("httpx.Client", return_value=_client_returning([cloud])):
        with patch.object(
            upsert_mod, "delete_ids", side_effect=lambda u, k, ids: deleted.extend(ids)
        ):
            upsert_mod._prune(URL, KEY, ["C"], local, batch_size=50, force=False)
    assert deleted == ["c_9"]


def test_prune_refuses_oversized_delete(upsert_mod):
    cloud = [{"id": f"c_{i}"} for i in range(10)]
    local = {"C": {"c_0"}}  # would delete 9/10 rows
    with patch("httpx.Client", return_value=_client_returning([cloud])):
        with patch.object(upsert_mod, "delete_ids") as deleter:
            with pytest.raises(SystemExit, match="20%"):
                upsert_mod._prune(URL, KEY, ["C"], local, batch_size=50, force=False)
            deleter.assert_not_called()


def test_prune_force_overrides_threshold(upsert_mod):
    cloud = [{"id": f"c_{i}"} for i in range(10)]
    local = {"C": {"c_0"}}
    deleted = []
    with patch("httpx.Client", return_value=_client_returning([cloud])):
        with patch.object(
            upsert_mod, "delete_ids", side_effect=lambda u, k, ids: deleted.extend(ids)
        ):
            upsert_mod._prune(URL, KEY, ["C"], local, batch_size=50, force=True)
    assert len(deleted) == 9


def test_retry_recovers_from_dropped_connection(upsert_mod):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("EOF occurred in violation of protocol")
        return "ok"

    with patch.object(upsert_mod.time, "sleep"):
        assert upsert_mod._with_retry(flaky, "probe") == "ok"
    assert len(calls) == 3


def test_retry_gives_up_with_context(upsert_mod):
    def always_fails():
        raise httpx.ConnectError("EOF occurred in violation of protocol")

    with patch.object(upsert_mod.time, "sleep"):
        with pytest.raises(RuntimeError, match="probe failed after 4 attempts"):
            upsert_mod._with_retry(always_fails, "probe")


def test_retry_does_not_mask_http_errors(upsert_mod):
    """A 4xx/5xx body is not a transport error; surface it immediately."""
    calls = []

    def bad_request():
        calls.append(1)
        raise ValueError("not a transport error")

    with pytest.raises(ValueError):
        upsert_mod._with_retry(bad_request, "probe")
    assert len(calls) == 1


def test_fetch_cloud_ids_survives_mid_pagination_drop(upsert_mod):
    page1 = [{"id": f"c_{i}"} for i in range(1000)]
    page2 = [{"id": "c_1000"}]
    queue = [page1, page2]
    failed_once = []

    def _get(endpoint, headers=None, params=None):
        if params["offset"] == 1000 and not failed_once:
            failed_once.append(1)
            raise httpx.ConnectError("EOF occurred in violation of protocol")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = queue.pop(0) if queue else []
        resp.text = ""
        return resp

    client = MagicMock()
    client.__enter__.return_value.get.side_effect = _get
    client.__exit__.return_value = False

    with patch("httpx.Client", return_value=client):
        with patch.object(upsert_mod.time, "sleep"):
            got = upsert_mod.fetch_cloud_ids(URL, KEY, ["C"])
    assert len(got["C"]) == 1001


def test_delete_ids_quotes_postgrest_filter(upsert_mod):
    client = MagicMock()
    resp = MagicMock()
    resp.status_code = 204
    resp.text = ""
    client.__enter__.return_value.delete.return_value = resp
    client.__exit__.return_value = False
    with patch("httpx.Client", return_value=client):
        upsert_mod.delete_ids(URL, KEY, ["a_1", "b_2"])
    params = client.__enter__.return_value.delete.call_args[1]["params"]
    assert params["id"] == 'in.("a_1","b_2")'
