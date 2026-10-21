"""Benchmark F14 (scripts/benchmark_llm.py) com Ollama e memória simulados:
nenhum teste carrega modelo, chama `sysctl` ou baixa nada."""

import json
from types import SimpleNamespace

import pytest

from scripts import benchmark_llm as b

GB = b.GB
MB = b.MB


def _parte(content="", done=False, **final):
    return SimpleNamespace(message=SimpleNamespace(content=content), done=done, **final)


class ClienteFalso:
    """Imita `ollama.Client`: `list()`, `chat(stream=True)` e `generate(keep_alive=0)`."""

    def __init__(self, modelos: dict[str, int], relogio=None):
        self.modelos = modelos
        self.relogio = relogio
        self.chats: list[dict] = []
        self.descarregados: list[str] = []
        self.pulls = 0

    def list(self):
        return SimpleNamespace(models=[SimpleNamespace(model=m, size=s) for m, s in self.modelos.items()])

    def pull(self, *a, **k):  # nunca deve ser chamado
        self.pulls += 1

    def chat(self, **kwargs):
        self.chats.append(kwargs)
        yield _parte("")                       # parte vazia: não conta como primeiro token
        if self.relogio:
            self.relogio.avancar(0.25)
        yield _parte("def ")
        if self.relogio:
            self.relogio.avancar(1.75)
        yield _parte("x", done=True, load_duration=2_000_000_000, prompt_eval_count=40,
                     prompt_eval_duration=200_000_000, eval_count=30, eval_duration=1_500_000_000)

    def generate(self, *, model, prompt, keep_alive):
        assert keep_alive == 0
        self.descarregados.append(model)


class Relogio:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def avancar(self, s):
        self.t += s


def _sonda(disponivel_gb=20.0, swaps_mb=(1000,)):
    """Sonda de memória; o swap segue a sequência dada e depois fica no último valor."""
    seq = list(swaps_mb)

    def ler():
        swap = seq.pop(0) if len(seq) > 1 else seq[0]
        return b.Memoria(total=24 * GB, disponivel=int(disponivel_gb * GB), swap_usado=int(swap * MB))
    return ler


def test_interpretar_vm_stat_soma_paginas_liberaveis():
    texto = (
        "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
        "Pages free:                               10000.\n"
        "Pages active:                            500000.\n"
        "Pages inactive:                           20000.\n"
        "Pages speculative:                         3000.\n"
        "Pages throttled:                              0.\n"
        "Pages wired down:                        200000.\n"
        "Pages purgeable:                           1000.\n"
    )
    assert b.interpretar_vm_stat(texto) == (10000 + 20000 + 3000 + 1000) * 16384


@pytest.mark.parametrize("texto,esperado", [
    ("total = 4096.00M  used = 2669.50M  free = 1426.50M  (encrypted)", int(2669.5 * MB)),
    ("total = 0.00M  used = 0.00M  free = 0.00M", 0),
    ("total = 8.00G  used = 1.50G  free = 6.50G", int(1.5 * GB)),
    ("algo inesperado", 0),
])
def test_interpretar_swapusage(texto, esperado):
    assert b.interpretar_swapusage(texto) == esperado


def test_mede_ttft_e_tokens_por_segundo_pelos_numeros_do_ollama():
    relogio = Relogio()
    cliente = ClienteFalso({"m:7b": 5 * GB}, relogio)
    r = b.benchmark_modelo(cliente, "m:7b", 1, instalados=b.tamanhos_instalados(cliente),
                           guarda=b.Guarda(), sonda=_sonda(), relogio=relogio, log=lambda _: None)
    assert r.status == "ok"
    assert len(r.tentativas) == len(b.PROMPTS)
    t = r.tentativas[0]
    assert t.ttft_s == 0.25            # a parte vazia inicial não conta
    assert t.total_s == 2.0
    assert t.tokens_s == 20.0          # 30 tokens / 1,5 s
    assert t.tokens_prompt_s == 200.0  # 40 tokens / 0,2 s
    assert t.carga_s == 2.0
    assert t.swap_delta_mb == 0.0
    # aquecimento + uma chamada por prompt, sempre com as opções fixas e em stream
    assert len(cliente.chats) == 1 + len(b.PROMPTS)
    assert all(c["options"] == b.OPCOES and c["stream"] is True for c in cliente.chats)
    assert cliente.descarregados == ["m:7b"]


def test_modelo_ausente_vira_nao_instalado_e_nunca_baixa():
    cliente = ClienteFalso({})
    r = b.benchmark_modelo(cliente, "qwen3-coder:30b", 1, instalados={}, guarda=b.Guarda(),
                           sonda=_sonda(), log=lambda _: None)
    assert r.status == "nao_instalado"
    assert cliente.pulls == 0 and cliente.chats == []


def test_modelo_que_nao_cabe_na_memoria_nem_e_carregado():
    cliente = ClienteFalso({"qwen3-coder:30b": 18 * GB})
    r = b.benchmark_modelo(cliente, "qwen3-coder:30b", 1, instalados=b.tamanhos_instalados(cliente),
                           guarda=b.Guarda(), sonda=_sonda(disponivel_gb=12), log=lambda _: None)
    assert r.status == "pulado_memoria"
    assert "não carregado" in r.detalhe
    assert cliente.chats == [] and cliente.descarregados == []


def test_guarda_cabe_considera_folga_e_margem():
    g = b.Guarda(margem_gb=1.5, fator_modelo=1.15)
    mem = b.Memoria(total=24 * GB, disponivel=10 * GB, swap_usado=0)
    assert g.cabe(int(7.39 * GB), mem)[0] is True   # 7,39*1,15+1,5 = 9,999
    assert g.cabe(8 * GB, mem)[0] is False


def test_swap_crescendo_aborta_e_descarrega_o_modelo():
    relogio = Relogio()
    cliente = ClienteFalso({"m:14b": 9 * GB}, relogio)
    # base 1000 MB; a primeira sonda durante o stream já vê +800 MB
    r = b.benchmark_modelo(cliente, "m:14b", 3, instalados=b.tamanhos_instalados(cliente),
                           guarda=b.Guarda(swap_max_mb=512), sonda=_sonda(swaps_mb=(1000, 1800)),
                           relogio=relogio, log=lambda _: None)
    assert r.status == "abortado_swap"
    assert "800 MB" in r.detalhe
    assert r.tentativas == []
    assert cliente.descarregados == ["m:14b"]


def test_erro_do_modelo_vira_resultado_e_ainda_descarrega():
    class Quebrado(ClienteFalso):
        def chat(self, **kwargs):
            raise ConnectionError("ollama fora do ar")

    cliente = Quebrado({"m:7b": 5 * GB})
    r = b.benchmark_modelo(cliente, "m:7b", 1, instalados=b.tamanhos_instalados(cliente),
                           guarda=b.Guarda(), sonda=_sonda(), log=lambda _: None)
    assert r.status == "erro" and "ollama fora do ar" in r.detalhe
    assert cliente.descarregados == ["m:7b"]


def test_resumir_usa_medianas_e_ignora_none():
    T = b.Tentativa
    r = b.ResultadoModelo("m", "ok", tentativas=[
        T("m", "p", 1, 0.2, 2.0, 0.0, 10, 100.0, 30, 10.0, 0.0),
        T("m", "p", 2, 0.4, 4.0, 0.0, 10, None, 30, 30.0, 0.0),
        T("m", "p", 3, None, 3.0, 0.0, 10, 300.0, 30, 20.0, 0.0),
    ])
    (linha,) = b.resumir([r, b.ResultadoModelo("x", "nao_instalado", "ausente")])[:1]
    assert linha["ttft_mediana_s"] == 0.3
    assert linha["tokens_s_mediana"] == 20.0
    assert linha["tokens_prompt_s_mediana"] == 200.0
    assert linha["total_mediana_s"] == 3.0
    assert linha["medicoes"] == 3


def test_relatorio_e_reprodutivel_com_relogio_fixo(tmp_path, monkeypatch):
    def rodar(nome):
        relogio = Relogio()
        cliente = ClienteFalso({"m:7b": 5 * GB, "m:30b": 18 * GB}, relogio)
        monkeypatch.setattr(b.time, "monotonic", relogio)
        monkeypatch.setattr(b, "ler_maquina", lambda: {"chip": "Apple M5", "sistema": "x", "python": "3.12"})
        saida = tmp_path / nome
        b.main(["--modelos", "m:7b,m:30b,m:ausente", "--tentativas", "2", "--saida", str(saida)],
               cliente=cliente, sonda=_sonda(disponivel_gb=12))
        dados = json.loads(saida.read_text(encoding="utf-8"))
        dados.pop("gerado_em")
        return dados

    a, c = rodar("a.json"), rodar("b.json")
    assert a == c
    assert [r["status"] for r in a["resumo"]] == ["ok", "pulado_memoria", "nao_instalado"]
    assert a["config"]["opcoes"] == b.OPCOES
    assert a["config"]["prompts_sha256"]
    assert a["maquina"]["ram_gb"] == 24.0
    assert len(a["resultados"][0]["tentativas"]) == 2 * len(b.PROMPTS)


def test_plano_nao_carrega_nenhum_modelo(capsys):
    cliente = ClienteFalso({"m:7b": 5 * GB, "m:30b": 18 * GB})
    assert b.main(["--plano", "--modelos", "m:7b,m:30b,m:ausente"], cliente=cliente,
                  sonda=_sonda(disponivel_gb=12)) == 0
    saida = capsys.readouterr().out
    assert "m:7b: 5.0 GB, precisa ~7.2 GB -> roda" in saida
    assert "m:30b: 18.0 GB, precisa ~22.2 GB -> pulado (memória)" in saida
    assert "m:ausente: não instalado" in saida
    assert cliente.chats == [] and cliente.descarregados == []
