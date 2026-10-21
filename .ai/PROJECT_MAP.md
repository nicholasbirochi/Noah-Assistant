# Noah: mapa do projeto

Mapa de navegacao, conferido contra os arquivos locais em 2026-10-10.
Verifique o codigo antes de confiar em um detalhe.

## Entradas e fluxo

- `src/cli.py`: CLI, conversa em texto/voz, indexacao, adaptadores e agente local.
- `src/menubar.py`: `NoahMenuBarApp`, controle da escuta e janela nativa.
- `src/scripts/noah_app_main.py`: entrada de Noah.app.
- `src/assistant/conversation.py`: ciclo de conversa e interrupcao.
- `src/assistant/llm_client.py`: contexto e ferramentas da conversa; recupera
  tool-call vinda como JSON no texto (so ferramentas de leitura) e forca uma
  consulta real ao Cerebro em pedido explicito ou em pergunta implicita sobre
  fatos/decisoes/capacidades do Noah (cumprimentos nao disparam). A escolha
  espontanea da ferramenta pelo modelo segue nao confiavel.
  Resposta que afirma acao/consulta ("adicionei", "preparei", "consultei",
  rotulo "[CONSULTA AO CEREBRO") sem ferramenta executada no turno recebe
  um aviso de sistema e mais uma iteracao; se repetir, o usuario ouve que
  nada foi feito. A acao nunca e executada no lugar do modelo.
- `src/assistant/providers.py`: contrato `LocalLLMProvider`; implementacao
  atual `OllamaProvider`. MLX e outros providers ainda sao objetivos. Abriga
  `recover_tool_call_from_content`, reusada pelo agente de coding e pela conversa.
- `src/assistant/coding_agent.py`: loop com limite de iteracoes, consulta de
  arquivos/git e execucao de pytest; ainda sem editar codigo.
- `src/assistant/tools.py`: ferramentas oferecidas ao assistente.
- `src/finance.py`: leitura (so leitura) da planilha de patrimonio em
  `config.PATRIMONIO_PATH`. `src/finance_pluggy.py`: saldos por banco ao vivo do
  Meu Pluggy, opt-in (`NOAH_FINANCE_SOURCE=pluggy`), lista fechada de 3 chamadas
  de leitura, credenciais no Keychain, planilha como reserva.
- `src/assistant/cerebro.py`: ponte para o segundo cerebro (Cerebro) pela CLI
  existente (`.cerebro/cerebro.py`): consulta (`buscar --trechos`, escopo no
  projeto identificado) e registro gravado so com autorizacao humana real.
- `src/voice/`: microfone, wake word, STT e TTS; XTTS usa worker separado.
- `src/visualizer/`: HUD via HTTP/SSE local e WKWebView.
- `src/central/`: app Noah com abas Pendencias (Claude Code, Codex e presenca do
  Noah) e Presenca (`GET /central/api/presenca`, so leitura, desligada por padrao)
  em servidor proprio na 8769, so leitura dos transcripts locais e resposta por
  retomada sem edicao; `sinal_cerebro.py` conta consultas ao Cerebro e delegacoes
  aos auxiliares nos ultimos 10 min (`GET /central/api/cerebro`), com o codigo
  das pastas do cofre tocadas (`partes`, nunca termos ou trechos); decisao em
  `docs/ADR-0002`.
- `apple/`: app Noah nativo (SwiftUI, iPhone e Mac) sobre a mesma central; tela
  inicial so com tarefas (geradas pelo Noah marcadas), detalhe ao tocar, painel
  "Ao vivo", avisos com acao e aba Fluxo (mapa animado: ligacoes com a central
  e consultas ao Cerebro ao vivo, tracejadas so sem sinal; Cerebro em pedacos
  com as 8 pastas e bonequinhos por agente em `apple/App/Bonecos.swift`); logica testavel em
  `apple/Packages/NoahCore` (`swift test`); decisao em `docs/ADR-0003`.
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
Entrega feita (2026-10-11, commitada em 2026-10-18): o assistente consulta e
registra no segundo cerebro em `/Users/nicholasbirochi/Documents/Cérebro`
pela CLI existente (`.cerebro/cerebro.py`), com leitura delimitada e gravacao
so por autorizacao humana -- `src/assistant/cerebro.py`, `consult_cerebro`/
`prepare_cerebro_note` e `src/cli.py cerebro-registrar`. Tool-call devolvida
como JSON no texto e recuperada (so para ferramentas de leitura) e um pedido
explicito de consulta forca uma consulta real antes da resposta
(`llm_client.py`, `providers.recover_tool_call_from_content`). Testada com
provider falso em `src/tests/test_cerebro.py` e comprovada de ponta a ponta
com o modelo instalado `qwen2.5-coder:7b` (consulta executada e resposta
fundamentada; o modelo de conversa padrao `qwen2.5:7b` ainda nao esta
instalado). Proxima entrega proposta: provider MLX (F4).

## Instalacao local

- Pasta real: `54 - Noah`; venv e bundle usam esse caminho.
- Remoto: `https://github.com/nicholasbirochi/Noah-Assistant.git`.
- App: `/Applications/Noah.app`; LaunchAgent abre o bundle via LaunchServices.
- Backups: Application Support/Noah/Backups/before-noah-only, fora do Git.
