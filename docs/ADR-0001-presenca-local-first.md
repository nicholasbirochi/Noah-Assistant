# ADR-0001 — Presença proativa no HUD, local-first

- **Status:** aceito (primeira fatia implementada em `src/assistant/presence.py`)
- **Data:** 2026-10-18

## Contexto

O Grok Bot da xAI (página pública <https://x.ai/bot> e guias ligados a ela, só
observação pública — nada foi baixado, instalado nem descompilado) mostra uma ideia útil:
um assistente que, além do chat, tem **rotinas** disparadas por horário ou evento.
Algumas características chamaram atenção:

- as rotinas nascem **desligadas** até o usuário habilitar;
- ficam **quietas quando não há nada** a dizer ("quiet on noop") e **falham fechado**;
- cada item segue o formato **fonte → por que importa → o que fazer**;
- **nunca inventam urgência nem contagens**;
- por padrão são **somente leitura**, e qualquer ação espera aprovação.

O produto da xAI roda em nuvem: um computador remoto persistente, modelos hospedados e
plano pago. O Noah tem a premissa oposta: 100% local (Ollama), sem API paga e sem dados
pessoais saindo da máquina.

## Decisão

Reimplementar só a **ideia** (clean-room), em cima do que o Noah já tem:

1. **Fatos derivados por código, nunca pelo LLM.** `assistant/presence.py` conta o que já
   está em disco: propostas de currículo pendentes, conflitos abertos e lembretes. Usa a
   mesma postura de `assistant/briefing.py`, sem modelo nenhum no caminho, então não há
   como inventar número.
2. **Formato fonte → por quê → ação.** Cada item (`PresenceItem`) traz a fonte do fato,
   por que importa e o próximo passo concreto, que é um comando ou uma frase. O Noah **não
   executa** esse passo sozinho.
3. **Desligado por padrão.** No HUD só aparece com `NOAH_PRESENCE_ENABLED=true`. O comando
   `python src/cli.py presenca` é uma leitura explícita e funciona sempre.
4. **Quieto quando não há nada.** Sem itens, nada é exibido nem falado. Uma fonte ilegível
   é pulada: o card não chuta números para ela.
5. **Sem rede e sem nuvem, nem como fallback.** A presença não consulta RSS, site, API nem
   modelo remoto. Se uma capacidade local não estiver disponível, ela simplesmente não
   aparece. Nunca há troca silenciosa para um serviço externo. Isso vale também para as
   próximas fatias.
6. **Canal próprio no HUD.** O card usa um slot dedicado em `visualizer/state.py`
   (`publish_presence`/`current_presence`), independente do gráfico (`publish_data`).
   Assim um gráfico novo não apaga o card e vice-versa. O servidor reenvia o slot a cada
   aba nova. O texto é inserido com `textContent`, nunca como HTML.

## Consequências

- Ganho: o HUD passa a sugerir o próximo passo ao abrir, sem custo de API e sem dado
  pessoal saindo da máquina.
- Limite intencional: não há agendador (cron), bot-a-bot, gravação por demonstração nem
  ação automática. Cada um exigiria uma decisão própria; ficam no Roadmap.
- Risco controlado: a lista de fontes é fechada no código. Uma fonte nova precisa de teste
  próprio e entra pelo mesmo contrato (fato contável → item; erro → pula).

## Alternativas descartadas

- **Usar o app ou a API do Grok Bot:** é pago, roda em nuvem e mandaria dados pessoais
  para fora.
- **Engenharia reversa do app da xAI:** pode violar os termos de uso da xAI e não é
  necessária. A ideia pública basta.
- **Deixar o LLM local redigir as sugestões:** reabre o risco de afirmações sem lastro que
  o `briefing.py` já evita.
