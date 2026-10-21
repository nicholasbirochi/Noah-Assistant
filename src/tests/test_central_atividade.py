"""Atividade da aba Central (central/atividade.py) com cofre falso em tmp_path
e Ollama falso: nada de rede nem do Cérebro real."""

import json
import os
from datetime import datetime
from urllib.error import URLError

from central import atividade

AGORA = datetime(2026, 10, 20, 12, 0).timestamp()


def _ollama(tags, ps):
    def ler(url):
        return {"models": [{"name": n} for n in (tags if url.endswith("/api/tags") else ps)]}
    return ler


def _sem_ollama(url):
    raise URLError("recusado")


def _cofre(tmp_path):
    raiz = tmp_path / "Cérebro"
    for pasta in ("00 - Regras para Agentes", "02 - Projetos", "06 - Logs de Tarefas", ".obsidian"):
        (raiz / pasta).mkdir(parents=True)
    (raiz / "00 - Regras para Agentes" / "Protocolo.md").write_text("x")
    (raiz / "02 - Projetos" / "Projeto - Noah.md").write_text("x")
    (raiz / "02 - Projetos" / "sub").mkdir()
    (raiz / "02 - Projetos" / "sub" / "Outra.md").write_text("x")
    (raiz / ".obsidian" / "oculta.md").write_text("x")
    log = raiz / "06 - Logs de Tarefas" / "Log - hoje.md"
    log.write_text("x")
    os.utime(log, (AGORA - 60, AGORA - 60))
    antiga = raiz / "00 - Regras para Agentes" / "Protocolo.md"
    os.utime(antiga, (AGORA - 30 * 86400, AGORA - 30 * 86400))
    (raiz / ".cerebro").mkdir()
    linhas = [
        {"data": "2026-10-20T11:00:00", "tipo": "mecanica", "provider": "ollama",
         "model": "qwen2.5-coder:7b", "elapsed_seconds": 6.6},
        {"data": "2026-10-18T09:00:00", "tipo": "analise", "provider": "nemotron", "model": "nvidia/x"},
    ]
    (raiz / ".cerebro" / "uso-auxiliares.jsonl").write_text(
        "\n".join(json.dumps(l) for l in linhas) + "\nlinha quebrada\n[1]\n")
    (raiz / ".cerebro" / "auxiliares.json").write_text(json.dumps(
        {"nemotron_habilitado": True, "copilot_habilitado": False, "chave": "nunca-sai"}))
    return raiz


def test_modelos_cruzam_ollama_rotas_e_uso(tmp_path):
    dados = atividade.ler_atividade(
        cerebro_dir=_cofre(tmp_path), agora=AGORA,
        ler=_ollama(["qwen2.5:7b", "qwen2.5-coder:7b"], ["qwen2.5-coder:7b"]))
    modelos = {m["id"]: m for m in dados["modelos"]}
    assert set(modelos) == {"qwen2.5:7b", "qwen2.5-coder:7b", "qwen2.5-coder:14b", "qwen3-coder:30b",
                            "nemotron", "copilot"}
    q7 = modelos["qwen2.5-coder:7b"]
    assert q7["carregado"] and q7["disponivel"] and q7["usos_24h"] == 1
    assert q7["rotas"] == ["mecanica", "codigo"]
    assert modelos["qwen2.5-coder:14b"]["disponivel"] is False  # na rota, mas não instalado
    assert modelos["qwen2.5:7b"]["rotas"] == []  # o do próprio Noah, fora das rotas
    assert modelos["nemotron"]["disponivel"] is True and modelos["nemotron"]["usos_24h"] == 0
    assert modelos["nemotron"]["ultimo_uso"] is not None
    assert modelos["copilot"]["disponivel"] is False
    assert "nunca-sai" not in json.dumps(dados)
    assert dados["ollama"] is True and dados["falhas"] == []


def test_cerebro_conta_por_pasta_sem_ocultas(tmp_path):
    dados = atividade.ler_atividade(cerebro_dir=_cofre(tmp_path), agora=AGORA, ler=_sem_ollama)
    pastas = {p["numero"]: p for p in dados["cerebro"]["pastas"]}
    assert set(pastas) == {"00", "02", "06"}
    assert pastas["02"]["notas"] == 2 and pastas["02"]["nome"] == "Projetos"
    notas = [e["texto"] for e in dados["eventos"] if e["tipo"] == "nota"]
    assert "06 · Log - hoje" in notas and not any("Protocolo" in n for n in notas)


def test_cerebro_manda_arvore_da_pasta_sem_conteudo(tmp_path):
    raiz = _cofre(tmp_path)
    (raiz / "02 - Projetos" / "vazia").mkdir()
    (raiz / "02 - Projetos" / ".oculta").mkdir()
    (raiz / "02 - Projetos" / ".oculta" / "x.md").write_text("x")
    (raiz / "02 - Projetos" / "imagem.png").write_text("x")
    dados = atividade.ler_atividade(cerebro_dir=raiz, agora=AGORA, ler=_sem_ollama)
    projetos = next(p for p in dados["cerebro"]["pastas"] if p["numero"] == "02")
    itens = {i["nome"]: i for i in projetos["itens"]}
    assert set(itens) == {"Projeto - Noah", "sub"}  # sem pasta vazia, oculta ou não-nota
    assert itens["Projeto - Noah"]["tipo"] == "nota"
    assert itens["sub"]["tipo"] == "pasta" and itens["sub"]["notas"] == 1
    assert itens["sub"]["itens"] == [{"nome": "Outra", "tipo": "nota",
                                      "atualizada_em": itens["sub"]["atualizada_em"]}]
    assert "x\"" not in json.dumps(dados)  # nada do conteúdo das notas


def test_sem_ollama_vira_falha_e_nao_inventa(tmp_path):
    dados = atividade.ler_atividade(cerebro_dir=_cofre(tmp_path), agora=AGORA, ler=_sem_ollama)
    assert dados["ollama"] is False and dados["falhas"] == ["Ollama"]
    modelos = {m["id"]: m for m in dados["modelos"]}
    assert modelos["qwen2.5-coder:7b"]["disponivel"] is None
    assert not any(m["carregado"] for m in dados["modelos"])


def test_feed_em_ordem_e_sem_quem_chamou(tmp_path):
    dados = atividade.ler_atividade(cerebro_dir=_cofre(tmp_path), agora=AGORA, ler=_sem_ollama)
    quando = [e["quando"] for e in dados["eventos"]]
    assert quando == sorted(quando, reverse=True)
    aux = [e for e in dados["eventos"] if e["tipo"] == "auxiliar"]
    assert [e["para"] for e in aux] == ["qwen2.5-coder:7b", "nemotron"]
    assert all(e["de"] == "agente" for e in aux)  # o registro não diz se foi Claude ou Codex
    assert aux[0]["texto"] == "tarefa mecanica para qwen2.5-coder:7b (7 s)"


def test_cofre_inexistente_vira_falha(tmp_path):
    dados = atividade.ler_atividade(cerebro_dir=tmp_path / "nao-existe", agora=AGORA, ler=_sem_ollama)
    assert "Cérebro" in dados["falhas"] and dados["cerebro"]["pastas"] == []
