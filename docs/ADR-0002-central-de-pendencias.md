# ADR-0002 — Central de pendências (Claude Code, Codex e Noah) e app Noah

- **Status:** aceito (primeira versão em `src/central/`)
- **Data:** 2026-10-19

## Contexto

Com várias conversas abertas ao mesmo tempo, no Claude Code e no Codex, fica difícil
saber quais delas terminaram e estão esperando uma resposta. A ideia veio do card de
presença do ADR-0001, inspirado no Grok Bot. Ela tem três requisitos:

- uma lista bonita só do que espera o usuário, no Mac e no iPhone;
- responder dali mesmo;
- o Noah entrar como mais uma fonte.

As duas ferramentas já gravam tudo em disco:

- **Claude Code:** `~/.claude/projects/<pasta>/<sessão>.jsonl`;
- **Codex:** `~/.codex/sessions/AAAA/MM/DD/rollout-*.jsonl`, com os títulos em
  `~/.codex/session_index.jsonl`.

Há também duas CLIs locais que retomam uma conversa pelo id: `claude --resume` e
`codex exec resume`.

## Decisão

1. **Leitura só local, só leitura.** `central/fontes.py` lê o fim dos transcripts
   recentes. O padrão é 3 dias, com no máximo 40 itens. Nada é copiado nem enviado para
   fora. Para identificar o que está pendente, a regra é escrita em código, sem modelo:
   - **Claude:** a última mensagem é do assistente, tem texto, não tem `tool_use` em
     aberto e terminou o turno (`stop_reason` `end_turn`, `stop_sequence` ou
     `max_tokens`).
   - **Codex:** o último evento de turno é `task_complete`, com `last_agent_message`.
     O Codex Desktop grava `source` `vscode` e entra normalmente.

   Ficam de fora:
   - trechos de subagente (`isSidechain`);
   - sessões automáticas, ou seja, `claude -p` (`entrypoint` `sdk-cli`), `codex exec`
     (`source` `exec`) e subagentes do Codex;
   - a pasta `archived_sessions` (conversas arquivadas no Codex). O banco SQLite do
     Codex não é lido: os rollouts e o `session_index.jsonl` bastam.
2. **Responder sem editar.** `central/resposta.py` retoma a própria conversa em segundo
   plano, passando a mensagem pelo stdin. Assim, um texto que comece com `-` nunca vira
   flag. O comando é montado como lista, sem shell.
   - **Claude:** `claude -p --resume <id> --permission-mode plan --tools Read,Grep,Glob
     --strict-mcp-config --output-format text`. Ele lê o projeto, mas não edita, não roda comandos e não
     carrega servidores MCP.
   - **Codex:** `codex exec resume -c sandbox_mode="read-only" -c
     approval_policy="never" --skip-git-repo-check <id> -` (o `-` final lê a mensagem
     do stdin). Comandos só rodam dentro do sandbox somente leitura do
     próprio Codex, que bloqueia qualquer escrita. O binário preferido é o que vem
     dentro do app ChatGPT/Codex. No teste, o `codex` 0.147 do PATH recusou o modelo
     configurado no app, e o 0.163 do app respondeu. `NOAH_CODEX_BIN` passa por cima
     dessa escolha.

   Para mudar arquivos, o caminho continua sendo abrir a conversa no app. Só aceitamos
   ids que a própria central listou, então a página não consegue retomar uma sessão
   arbitrária. Há uma resposta por conversa por vez e no máximo duas ao mesmo tempo, com
   um teto de 15 minutos.
3. **Servidor próprio, mesmas travas da API local.** `central/servidor.py` usa só a
   biblioteca padrão e escuta na porta **8769**. As travas são as mesmas do
   `src/api_local.py`:
   - por padrão, só no 127.0.0.1;
   - fora do loopback, só com token, sempre `Authorization: Bearer`;
   - `Host` conferido, e `Origin` de outro endereço recusado com 403;
   - POST só com `application/json`, sem CORS e com corpo de até 64 KB.

   A página e o manifesto abrem sem token porque não contêm dado nenhum. Já a lista e a
   resposta sempre exigem o token, quando ele existe. A central ficou fora da 8768 porque
   aquele servidor ainda está sendo construído por outra frente de trabalho. A junção fica
   para quando os dois estiverem estáveis.
4. **Noah como fonte.** Os itens da presença (ADR-0001) entram na mesma lista, mas só
   para leitura. Eles aparecem só com `NOAH_PRESENCE_ENABLED=true`, como no HUD.
5. **Dispensar é local e por versão.** "Dispensar" guarda a versão atual do item (o
   horário da última resposta) e o esconde até chegar uma resposta nova naquela
   conversa. A marca fica em `LOCAL_STATE_DIR/central/dispensadas.json`, fora do
   repositório e fora da nuvem.
6. **App Noah: duas abas num só app.** A página virou o app "Noah" (título, manifesto e
   ícone), com as abas **Pendências** e **Presença**. A aba Presença lê
   `GET /central/api/presenca`, que devolve `{ligada, variavel, itens, falhas,
   gerado_em}`:
   - a rota é só leitura, exige o token como `pendencias` e passa pelas mesmas travas de
     `Host` e `Origin`;
   - `itens` vem de `build_presence_items()`, no formato fonte → por quê → ação;
   - desligada (`is_enabled()` falso), a rota nem lê as fontes e a aba explica como ligar,
     sem números;
   - uma fonte ilegível já é pulada pela presença; se a leitura toda falhar, sai
     `falhas: ["Presença"]` e a lista fica vazia.

   As duas abas se atualizam juntas, e a falha de uma não apaga a outra. O ícone da tela
   de início vem em PNG (180 e 512 px), gerado do `icone.svg` com o `qlmanage`/`sips` do
   macOS, porque o iOS não aceita SVG ali.
7. **Sinal do Cérebro para a aba Fluxo do app nativo.** `GET /central/api/cerebro`
   (`central/sinal_cerebro.py`) devolve `{janela_s, cerebro: {claude, codex, noah},
   auxiliares: {claude, codex}, falhas, gerado_em}`, com consultas, registros e
   delegações dos últimos 600 s:
   - só leitura, com o mesmo token e as mesmas travas de `Host` e `Origin`;
   - conta só chamadas de ferramenta: `tool_use` do Claude Code (conversas e subagentes)
     e `function_call`, `custom_tool_call` e `local_shell_call` do Codex. Um texto que só
     cita `cerebro.py` não conta;
   - `cerebro.py buscar|contexto` é consulta, `gravar` é registro e cada `auxiliares.py`
     é uma delegação;
   - o Noah anota só o horário de cada consulta (nunca os termos) em
     `LOCAL_STATE_DIR/central/atividade_cerebro.jsonl`, limitado às últimas 200;
   - uma fonte que falha sai em `falhas` e fica zerada; o resultado fica em cache por 5 s.

## Consequências

- O acesso só funciona no Wi-Fi de casa, porque a central não tem acesso remoto. Para
  usar fora de casa, seria preciso uma VPN como o Tailscale, que hoje não está instalado
  e exige autorização.
- A resposta enviada pela central é gravada no mesmo transcript. Se a conversa estiver
  aberta no app do Claude ou do Codex, talvez seja preciso reabri-la para ver o turno
  novo.
- Os formatos dos transcripts não são uma API pública. Se mudarem, o leitor pula a linha
  ou o arquivo, porque falha fechado. Ele nunca inventa uma pendência.
- Com a presença ligada, os mesmos itens aparecem nas duas abas: em Pendências como
  cartões "Noah" e na aba Presença com o "o que fazer". Se a repetição incomodar, os
  cartões "Noah" podem sair de Pendências.
- O app no iPhone (ícone e "Adicionar à Tela de Início") ainda não foi testado num
  aparelho.
- A resposta usa o plano da própria CLI, ou seja, a assinatura do usuário. Não há chave
  de API nem custo novo.
