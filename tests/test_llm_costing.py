from job_hunter_agent import llm_gate


def test_cost_per_million(monkeypatch):
    monkeypatch.setattr(llm_gate, "load_global_settings", lambda: {"llm_settings": {"pricing_metadata": {"unit": "per_1m_tokens"}}})
    cost = llm_gate._calculate_llm_cost_usd(1000000, 1000000, {"input": 0.40, "output": 1.60})
    assert round(cost, 6) == 2.0


def test_cost_per_thousand(monkeypatch):
    monkeypatch.setattr(llm_gate, "load_global_settings", lambda: {"llm_settings": {"pricing_metadata": {"unit": "per_1k_tokens"}}})
    cost = llm_gate._calculate_llm_cost_usd(1000, 1000, {"input": 0.0004, "output": 0.0016})
    assert round(cost, 6) == 0.002
