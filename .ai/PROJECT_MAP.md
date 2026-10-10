# Noah: mapa do projeto

Mapa de navegacao, conferido contra os arquivos locais em 2026-10-10.
Verifique o codigo antes de confiar em um detalhe.

## Entradas e fluxo

- `src/cli.py`: CLI, conversa em texto/voz, indexacao, adaptadores e agente local.
- `src/menubar.py`: `NoahMenuBarApp`, controle da escuta e janela nativa.
- `src/scripts/noah_app_main.py`: entrada de Noah.app.
- `src/assistant/conversation.py`: ciclo de conversa e interrupcao.
- `src/assistant/llm_client.py`: contexto e ferramentas da conversa.
- `src/assistant/providers.py`: contrato `LocalLLMProvider`; implementacao
  atual `OllamaProvider`. MLX e outros providers ainda sao objetivos.
- `src/assistant/coding_agent.py`: loop com limite de iteracoes, consulta de
  arquivos/git e execucao de pytest; ainda sem editar codigo.
- `src/assistant/tools.py`: ferramentas oferecidas ao assistente.
- `src/voice/`: microfone, wake word, STT e TTS; XTTS usa worker separado.
- `src/visualizer/`: HUD via HTTP/SSE local e WKWebView.
- `src/indexing/` e `src/resume/`: documentos de curriculo, propostas e revisao;
  nao equivalem a integracao com a memoria de projetos do Obsidian.
- `src/sites/`, `src/job_search.py` e `src/job_portal/`: vagas e candidaturas.

## Configuracao e dados

- Python, `requirements.txt`, `.venv`, pytest, Ollama, Playwright e PyObjC.
- `src/config.py` carrega `.env`. Somente `NOAH_*` para opcoes do assistente.
- `src/data/` contem estado local; nao abrir dados pessoais para analisar codigo.
- Sessoes, perfil confidencial e voz ficam fora do OneDrive em `LOCAL_STATE_DIR`.
  Nesta maquina, o estado foi migrado para Application Support/Noah.
- Ativacao padrao: duas palmas. Ativacao falada exige detector Noah local;
  nenhum modelo e baixado automaticamente.
- Lock `noah.pid`, voz `noah_reference.wav`, portal `noah_portal_*`.

## Validacao

```bash
.venv/bin/python -m pytest src/tests -q -p no:cacheprovider --tb=short
.venv/bin/python src/cli.py --help
```

Testes HTTP precisam poder abrir sockets em 127.0.0.1. A suite usa dados
temporarios/mocks; voz, modelos e sites reais exigem validacao separada.
`src/scripts/benchmark_coding_agent.py` mede consultas factuais; ainda nao
mede implementacao e correcao de bugs de ponta a ponta.

## Plano e proxima entrega

`NOAH_Apple_Private_AI_Cluster_MASTER_v3.zip` e a copia atualizada do plano.
O plano de origem foi preservado fora do projeto. Planos nao sao evidencia
de implementacao.
Proxima entrega proposta: conectar o agente local ao segundo cerebro em
`/Users/nicholasbirochi/Documents/Cérebro`, com leitura delimitada, registro
verificavel e testes usando provider falso.

## Instalacao local

- Pasta real: `54 - Noah`; venv e bundle usam esse caminho.
- Remoto: `https://github.com/nicholasbirochi/Noah-Assistant.git`.
- App: `/Applications/Noah.app`; LaunchAgent abre o bundle via LaunchServices.
- Backups: Application Support/Noah/Backups/before-noah-only, fora do Git.
