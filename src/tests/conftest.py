"""Fixtures compartilhadas da suíte."""

import pytest


@pytest.fixture(autouse=True)
def _sinal_cerebro_em_pasta_temporaria(tmp_path, monkeypatch):
    """consultar() anota o horário de cada consulta para o sinal ao vivo do app
    Noah; nos testes isso vai para a pasta temporária, nunca para o estado real."""
    from central import sinal_cerebro

    monkeypatch.setattr(sinal_cerebro, "_arquivo_noah", lambda: tmp_path / "atividade_cerebro.jsonl")
