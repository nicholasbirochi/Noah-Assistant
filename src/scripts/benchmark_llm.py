"""Benchmark F14 de latência/vazão dos modelos de código no Ollama local.

Mede, por modelo e por tentativa: TTFT (tempo até o primeiro token de texto,
no relógio de parede), tokens/s de geração (`eval_count / eval_duration`,
números do próprio Ollama), tokens/s de leitura do prompt, tempo de carga e
tempo total. Complementa `benchmark_coding_agent.py` (que mede acerto do
agente) -- aqui é só desempenho bruto do modelo, sem ferramentas.

Reprodutível: prompts fixos, `temperature=0`, `seed` fixo, `num_predict` e
`num_ctx` fixos; o JSON de saída grava a configuração inteira (modelos,
opções, hash dos prompts, chip, RAM) junto com as linhas, para comparar
rodadas e máquinas (o Mac de 24 GB hoje, o Mac mini de 64 GB depois).

Guarda de memória (o motivo deste script existir separado): em 24 GB o 14B
já foi abortado por crescer o swap e o 30B nunca carregou. Então, por modelo:
- nunca baixa nada: modelo ausente em `ollama list` vira `nao_instalado`;
- antes de carregar, compara o tamanho do modelo (com folga) com a memória
  disponível (`vm_stat`); se não couber, `pulado_memoria` sem carregar;
- durante a geração, lê `vm.swapusage`; se o swap crescer mais que
  `--swap-max-mb` desde o início do modelo, interrompe, descarrega o modelo
  (`keep_alive=0`) e marca `abortado_swap`.
Ao fim de cada modelo ele é descarregado, para o próximo começar limpo.

Uso:
    python src/scripts/benchmark_llm.py --plano          # só confere memória, não carrega
    python src/scripts/benchmark_llm.py [--modelos a,b] [--tentativas N] [--saida x.json]

Sem `--saida`, grava em data/llm_benchmarks/<timestamp>.json (fora do Git).
Só usa o Ollama local; nenhuma API paga.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SRC_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = SRC_ROOT / "data" / "llm_benchmarks"
DEFAULT_MODELS = ["qwen2.5-coder:7b", "qwen2.5-coder:14b", "qwen3-coder:30b"]
DEFAULT_TRIALS = 3
OPCOES = {"temperature": 0, "seed": 42, "num_predict": 192, "num_ctx": 4096}
PROMPTS = [
    ("funcao_curta", "Escreva uma função Python `eh_primo(n: int) -> bool` com docstring. Só o código."),
    ("explicar_erro", "Explique em até 5 linhas por que `for i in range(len(xs)): xs.pop(i)` falha em Python."),
    ("revisar_sql", "Reescreva com parâmetros (sem f-string) e explique o risco em uma linha:\n"
                    "cur.execute(f\"SELECT * FROM users WHERE name = '{nome}'\")"),
]
GB = 1024 ** 3
MB = 1024 ** 2


# ---------------------------------------------------------------- memória (macOS)

@dataclass
class Memoria:
    total: int
    disponivel: int
    swap_usado: int


def interpretar_vm_stat(texto: str) -> int:
    """Bytes que o sistema consegue liberar sem swap: livres + inativas +
    especulativas + purgáveis (o mesmo critério do Monitor de Atividade, aproximado)."""
    pagina = int(m.group(1)) if (m := re.search(r"page size of (\d+) bytes", texto)) else 4096
    paginas = 0
    for rotulo in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"):
        if m := re.search(rf"^{rotulo}:\s+(\d+)\.", texto, re.MULTILINE):
            paginas += int(m.group(1))
    return paginas * pagina


def interpretar_swapusage(texto: str) -> int:
    m = re.search(r"used = ([\d.]+)([KMG])", texto)
    if not m:
        return 0
    return int(float(m.group(1)) * {"K": 1024, "M": MB, "G": GB}[m.group(2)])


def _sysctl(*args: str) -> str:
    return subprocess.run(["sysctl", *args], capture_output=True, text=True, check=True).stdout


def ler_memoria() -> Memoria:
    vm = subprocess.run(["vm_stat"], capture_output=True, text=True, check=True).stdout
    return Memoria(
        total=int(_sysctl("-n", "hw.memsize").strip()),
        disponivel=interpretar_vm_stat(vm),
        swap_usado=interpretar_swapusage(_sysctl("vm.swapusage")),
    )


def ler_maquina() -> dict[str, str]:
    try:
        chip = _sysctl("-n", "machdep.cpu.brand_string").strip()
    except (OSError, subprocess.CalledProcessError):
        chip = platform.processor()
    return {"chip": chip, "sistema": platform.platform(), "python": platform.python_version()}


# ---------------------------------------------------------------- execução

@dataclass
class Guarda:
    margem_gb: float = 1.5      # sobra exigida além do modelo
    fator_modelo: float = 1.15  # KV cache/contexto em cima do tamanho em disco
    swap_max_mb: int = 512      # crescimento de swap tolerado por modelo

    def cabe(self, tamanho_modelo: int, memoria: Memoria) -> tuple[bool, int]:
        necessario = int(tamanho_modelo * self.fator_modelo + self.margem_gb * GB)
        return necessario <= memoria.disponivel, necessario


@dataclass
class Tentativa:
    modelo: str
    prompt: str
    tentativa: int
    ttft_s: float | None
    total_s: float
    carga_s: float
    tokens_prompt: int
    tokens_prompt_s: float | None
    tokens_gerados: int
    tokens_s: float | None
    swap_delta_mb: float


@dataclass
class ResultadoModelo:
    modelo: str
    status: str  # ok | nao_instalado | pulado_memoria | abortado_swap | erro
    detalhe: str = ""
    tamanho_gb: float | None = None
    tentativas: list[Tentativa] = field(default_factory=list)


class SwapExcedido(RuntimeError):
    pass


def _por_segundo(contagem: int | None, duracao_ns: int | None) -> float | None:
    if not contagem or not duracao_ns:
        return None
    return round(contagem / (duracao_ns / 1e9), 2)


def _medir(cliente, modelo: str, prompt: str, *, relogio: Callable[[], float],
           sonda: Callable[[], Memoria], swap_base: int, guarda: Guarda,
           intervalo_sonda_s: float = 1.0) -> dict[str, Any]:
    inicio = relogio()
    proxima_sonda = inicio + intervalo_sonda_s
    ttft = None
    final = None
    for parte in cliente.chat(model=modelo, messages=[{"role": "user", "content": prompt}],
                              stream=True, options=OPCOES, keep_alive="5m"):
        agora = relogio()
        if ttft is None and (parte.message.content or ""):
            ttft = agora - inicio
        if agora >= proxima_sonda:
            proxima_sonda = agora + intervalo_sonda_s
            delta = sonda().swap_usado - swap_base
            if delta > guarda.swap_max_mb * MB:
                raise SwapExcedido(f"swap cresceu {delta / MB:.0f} MB durante a geração")
        if parte.done:
            final = parte
    fim = relogio()
    if final is None:
        raise RuntimeError("o Ollama encerrou o stream sem a parte final (done)")
    return {
        "ttft_s": None if ttft is None else round(ttft, 3),
        "total_s": round(fim - inicio, 3),
        "carga_s": round((final.load_duration or 0) / 1e9, 3),
        "tokens_prompt": final.prompt_eval_count or 0,
        "tokens_prompt_s": _por_segundo(final.prompt_eval_count, final.prompt_eval_duration),
        "tokens_gerados": final.eval_count or 0,
        "tokens_s": _por_segundo(final.eval_count, final.eval_duration),
    }


def _descarregar(cliente, modelo: str) -> None:
    try:
        cliente.generate(model=modelo, prompt="", keep_alive=0)
    except Exception:  # noqa: BLE001 -- descarregar é limpeza; falhar aqui não invalida a medição
        pass


def tamanhos_instalados(cliente) -> dict[str, int]:
    return {m.model: int(m.size or 0) for m in cliente.list().models}


def benchmark_modelo(cliente, modelo: str, tentativas: int, *, instalados: dict[str, int],
                     guarda: Guarda, sonda: Callable[[], Memoria] = ler_memoria,
                     relogio: Callable[[], float] = time.monotonic,
                     log: Callable[[str], None] = print) -> ResultadoModelo:
    if modelo not in instalados:
        return ResultadoModelo(modelo, "nao_instalado", "ausente em `ollama list`; este script nunca baixa modelos")
    tamanho = instalados[modelo]
    resultado = ResultadoModelo(modelo, "ok", tamanho_gb=round(tamanho / GB, 2))
    memoria = sonda()
    cabe, necessario = guarda.cabe(tamanho, memoria)
    if not cabe:
        resultado.status = "pulado_memoria"
        resultado.detalhe = (f"precisa ~{necessario / GB:.1f} GB, disponível {memoria.disponivel / GB:.1f} GB "
                             f"(de {memoria.total / GB:.0f} GB); não carregado")
        return resultado
    swap_base = memoria.swap_usado
    try:
        log(f"  {modelo}: aquecendo (carga do modelo, não entra na medição)...")
        _medir(cliente, modelo, "ok", relogio=relogio, sonda=sonda, swap_base=swap_base, guarda=guarda)
        for n in range(1, tentativas + 1):
            for nome, prompt in PROMPTS:
                medida = _medir(cliente, modelo, prompt, relogio=relogio, sonda=sonda,
                                swap_base=swap_base, guarda=guarda)
                delta = (sonda().swap_usado - swap_base) / MB
                if delta > guarda.swap_max_mb:
                    raise SwapExcedido(f"swap cresceu {delta:.0f} MB")
                resultado.tentativas.append(Tentativa(modelo, nome, n, swap_delta_mb=round(delta, 1), **medida))
                log(f"  {modelo} [{n}/{tentativas}] {nome}: TTFT {medida['ttft_s']}s, "
                    f"{medida['tokens_s']} tok/s, {medida['tokens_gerados']} tokens")
    except SwapExcedido as exc:
        resultado.status, resultado.detalhe = "abortado_swap", str(exc)
    except Exception as exc:  # noqa: BLE001 -- uma falha do modelo é um resultado, não um bug a esconder
        resultado.status, resultado.detalhe = "erro", f"{type(exc).__name__}: {exc}"
    finally:
        _descarregar(cliente, modelo)
    return resultado


def resumir(resultados: list[ResultadoModelo]) -> list[dict[str, Any]]:
    def mediana(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.median(xs), 3) if xs else None
    linhas = []
    for r in resultados:
        t = r.tentativas
        linhas.append({
            "modelo": r.modelo, "status": r.status, "medicoes": len(t),
            "ttft_mediana_s": mediana(x.ttft_s for x in t),
            "tokens_s_mediana": mediana(x.tokens_s for x in t),
            "tokens_prompt_s_mediana": mediana(x.tokens_prompt_s for x in t),
            "total_mediana_s": mediana(x.total_s for x in t),
            "detalhe": r.detalhe,
        })
    return linhas


def configuracao(modelos: list[str], tentativas: int, guarda: Guarda, host: str) -> dict[str, Any]:
    textos = json.dumps(PROMPTS, ensure_ascii=False).encode()
    return {
        "modelos": modelos, "tentativas": tentativas, "opcoes": OPCOES, "host": host,
        "prompts": [nome for nome, _ in PROMPTS],
        "prompts_sha256": hashlib.sha256(textos).hexdigest()[:16],
        "guarda": asdict(guarda),
    }


def montar_relatorio(config: dict, maquina: dict, memoria: Memoria,
                     resultados: list[ResultadoModelo]) -> dict[str, Any]:
    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": config,
        "maquina": {**maquina, "ram_gb": round(memoria.total / GB, 1)},
        "resumo": resumir(resultados),
        "resultados": [asdict(r) for r in resultados],
    }


def imprimir_resumo(resumo: list[dict[str, Any]], log: Callable[[str], None] = print) -> None:
    log("\n=== Resumo (medianas) ===")
    for r in resumo:
        if r["status"] != "ok":
            log(f"{r['modelo']}: {r['status']} -- {r['detalhe']}")
            continue
        log(f"{r['modelo']}: TTFT {r['ttft_mediana_s']}s, {r['tokens_s_mediana']} tok/s, "
            f"prompt {r['tokens_prompt_s_mediana']} tok/s, total {r['total_mediana_s']}s "
            f"({r['medicoes']} medições)")


def main(argv: list[str] | None = None, *, cliente=None, sonda: Callable[[], Memoria] = ler_memoria) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--modelos", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--tentativas", type=int, default=DEFAULT_TRIALS)
    parser.add_argument("--saida", type=Path)
    parser.add_argument("--plano", action="store_true", help="só confere instalação e memória; não carrega modelo")
    parser.add_argument("--margem-gb", type=float, default=Guarda.margem_gb)
    parser.add_argument("--swap-max-mb", type=int, default=Guarda.swap_max_mb)
    args = parser.parse_args(argv)

    from config import OLLAMA_HOST

    if cliente is None:
        from ollama import Client
        cliente = Client(host=OLLAMA_HOST)
    guarda = Guarda(margem_gb=args.margem_gb, swap_max_mb=args.swap_max_mb)
    modelos = [m.strip() for m in args.modelos.split(",") if m.strip()]
    instalados = tamanhos_instalados(cliente)
    memoria = sonda()
    print(f"Memória: {memoria.disponivel / GB:.1f} GB disponível de {memoria.total / GB:.0f} GB; "
          f"swap em uso {memoria.swap_usado / GB:.1f} GB")

    if args.plano:
        for modelo in modelos:
            if modelo not in instalados:
                print(f"{modelo}: não instalado (não será baixado)")
                continue
            cabe, necessario = guarda.cabe(instalados[modelo], memoria)
            print(f"{modelo}: {instalados[modelo] / GB:.1f} GB, precisa ~{necessario / GB:.1f} GB -> "
                  f"{'roda' if cabe else 'pulado (memória)'}")
        return 0

    resultados = []
    for modelo in modelos:
        print(f"\n{modelo}")
        resultados.append(benchmark_modelo(cliente, modelo, args.tentativas, instalados=instalados,
                                           guarda=guarda, sonda=sonda))
    relatorio = montar_relatorio(configuracao(modelos, args.tentativas, guarda, OLLAMA_HOST),
                                 ler_maquina(), memoria, resultados)
    saida = args.saida or RESULTS_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    imprimir_resumo(relatorio["resumo"])
    print(f"\nRelatório salvo em {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
