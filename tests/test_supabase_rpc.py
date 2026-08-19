"""Supabase RPC retrieval mapping (mocked HTTP; no cloud)."""

from unittest.mock import MagicMock, patch


def test_resolve_retrieval_aliases(embed_mod):
    assert embed_mod.resolve_retrieval_mode("rpc") == "supabase"
    assert embed_mod.resolve_retrieval_mode("local") == "local"
    assert embed_mod.resolve_retrieval_mode("auto") == "auto"


def test_search_supabase_maps_rpc_rows(embed_mod, vector_store):
    store = embed_mod.MerckVectorStore(
        store_dir=vector_store.store_dir, retrieval="supabase"
    )
    store.embedder = vector_store.embedder
    store.vectors = vector_store.vectors
    store.records = vector_store.records

    rpc_body = [
        {
            "id": "cbarq42_excitability",
            "content": "C-BARQ42 scoring: subscale excitability",
            "metadata": {"module": "B", "source": "cbarq"},
            "module": "B",
            "source": "cbarq",
            "similarity": 0.91,
        }
    ]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = rpc_body
    mock_resp.text = ""

    mock_client = MagicMock()
    mock_client.__enter__.return_value.post.return_value = mock_resp
    mock_client.__exit__.return_value = False

    with patch.dict(
        "os.environ",
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "test-service-role",
        },
        clear=False,
    ):
        with patch("httpx.Client", return_value=mock_client):
            hits = store.search("C-BARQ excitability scoring", top_k=3)

    assert store.last_backend == "supabase"
    assert len(hits) == 1
    assert hits[0]["chunk_id"] == "cbarq42_excitability"
    assert hits[0]["score"] == 0.91
    assert hits[0]["metadata"]["module"] == "B"
    posted = mock_client.__enter__.return_value.post.call_args
    assert posted[0][0].endswith("/rest/v1/rpc/match_knowledge_chunks")
    assert posted[1]["json"]["match_count"] == 3


def test_auto_falls_back_to_local_on_rpc_error(embed_mod, vector_store):
    store = embed_mod.MerckVectorStore(
        store_dir=vector_store.store_dir, retrieval="auto"
    )
    store.embedder = vector_store.embedder
    store.vectors = vector_store.vectors
    store.records = vector_store.records

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "boom"
    mock_client = MagicMock()
    mock_client.__enter__.return_value.post.return_value = mock_resp
    mock_client.__exit__.return_value = False

    with patch.dict(
        "os.environ",
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "test-service-role",
        },
        clear=False,
    ):
        with patch("httpx.Client", return_value=mock_client):
            hits = store.search("dog heart rate bpm", top_k=3)

    assert store.last_backend == "local"
    assert hits
    assert hits[0]["chunk_id"]
