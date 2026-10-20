# App Noah nativo (iPhone e Mac)

App SwiftUI para iPhone e Mac. As abas são **Pendências**, **Presença**, **Fluxo** e
**Ajustes**. Os dois aparelhos leem a mesma central (`python src/cli.py central`, porta 8769), e é ela que os
sincroniza: o que você responde, aceita ou dispensa num aparelho some do outro na
próxima atualização. A decisão está em [ADR-0003](../docs/ADR-0003-app-nativo.md).

## O que tem

- **Pendências.** A tela inicial mostra só as tarefas, em linhas curtas:
  - **Para fazer:** conversas do Claude Code e do Codex esperando você.
  - **Geradas automaticamente:** itens que o Noah cria sozinho a partir da Presença,
    marcados como automáticos.
  - **Respostas:** o que está sendo respondido agora ou terminou há pouco.

  Toque numa tarefa para abrir o detalhe:
  - "O que fazer" e "Por quê", ou a última mensagem do agente;
  - Detalhes: origem (automática ou conversa), fonte, projeto e se dá para responder;
  - as ações Responder (texto livre), Aceitar e Dispensar. As geradas pelo Noah são só
    leitura e só têm Dispensar.
- **Painel "Ao vivo".** Mostra a hora da última sincronização, as contagens (para fazer,
  geradas pelo Noah, respondendo), o que está sendo respondido e o feed de atividade
  desde que o app abriu: entrou, saiu da lista, respondeu.
  - **Mac:** uma coluna fixa à direita, ligada e desligada pelo botão da barra de
    ferramentas.
  - **iPhone:** uma folha que sobe de baixo.
- **Fluxo.** Um mapa animado do caminho da informação entre Claude Code, Codex, Noah,
  Cérebro, Qwen local, a central e os aparelhos.
  - **Ligações com a central:** têm sinal ao vivo. Quando há pendência esperando ou
    resposta em andamento, partículas correm pela linha com a contagem ("1 para fazer").
  - **Consultas ao Cérebro e tarefas delegadas ao Qwen:** vêm do sinal da central
    (`GET /central/api/cerebro`), contado nos últimos 10 minutos. Com atividade, a linha
    ganha partículas e a contagem ("2 consultas · 1 registro", "1 tarefa delegada"). Sem
    nada na janela, ela fica parada ("nada nos últimos 10 min").
  - **Sem sinal ao vivo:** se a central é antiga (sem a rota) ou não conseguiu ler uma
    fonte, a ligação fica tracejada. O mapa mostra que o caminho existe sem inventar
    atividade.
  - Na aba Fluxo, o app relê a central a cada 10 s (4 s com resposta em andamento).
  - A animação pausa fora da aba e respeita "Reduzir movimento".
- **Avisos com ação.** Cada pendência nova vira um aviso com Responder, Aceitar e
  Dispensar; as só leitura têm apenas Dispensar.
  - Tocar no aviso abre o detalhe daquela pendência.
  - O aviso tem a mesma chave nos dois aparelhos.
  - O aviso some quando a pendência sai da lista ou alguém começa a respondê-la.
  - O número no ícone é a contagem do que espera você.
- **Mac.** O app fica na barra de menus mesmo com a janela fechada, para continuar
  avisando. O menu lista as pendências e abre o detalhe de cada uma.
- **Atualização.** A cada 20 s, e a cada 4 s enquanto alguém responde. No iPhone, com o
  app fechado, o iOS acorda o app de tempos em tempos (`BGAppRefresh`). Sem conta paga
  da Apple não há push (APNs).

O token fica no Keychain. O endereço da central e o texto do "Aceitar" (padrão "Pode
seguir.") ficam em UserDefaults.

## Gerar e abrir

O projeto Xcode é gerado a partir de `project.yml` com [XcodeGen](https://github.com/yonaskolb/XcodeGen).
O `Noah.xcodeproj` gerado também está no repositório, para abrir sem instalar nada.

```bash
cd apple && xcodegen
```

Para rodar no seu iPhone, copie `Config/Local.xcconfig.example` para `Config/Local.xcconfig`
e ponha o seu Team ID (Xcode > Settings > Accounts). Esse arquivo é ignorado pelo git, e o
repositório é público. A conta gratuita serve, mas o perfil vale 7 dias: depois disso é
preciso instalar de novo pelo Xcode. O app do Mac é assinado localmente (`-`) e não
precisa de conta.

## Ligar à central

- **Só no Mac.** Rode `python src/cli.py central` e deixe o endereço padrão
  `http://127.0.0.1:8769`, sem token.
- **Mac e iPhone juntos, pelo Wi-Fi de casa:**
  1. No Mac, rode `python src/cli.py central --host "$(ipconfig getifaddr en0)" --token "$(openssl rand -hex 16)"`
     e guarde o token.
  2. Em **Ajustes**, ponha `http://<IP do Mac>:8769` e o token **nos dois aparelhos,
     inclusive no Mac**. Com `--host`, a central só atende naquele IP, e o Mac em
     `127.0.0.1` ficaria de fora da sincronia.
  3. Toque em "Salvar e testar".

O IP do Mac vem do roteador (DHCP) e pode mudar. Se o app parar de achar a central,
confira o IP e atualize em Ajustes; reservar o IP no roteador evita isso. Fora de casa
precisaria de VPN (Tailscale), ainda não instalada.

## Testes

A lógica que não depende da tela fica no pacote `Packages/NoahCore`: modelos, cliente da
central, comparação de avisos, feed de atividade e as ligações da aba Fluxo. Ela tem
testes:

```bash
cd apple/Packages/NoahCore && swift test
```

Para testar sem a central de verdade, o app aceita outro endereço pela linha de comando:
`Noah.app/Contents/MacOS/Noah -endereco http://127.0.0.1:8779`.

## Verificado e não verificado

**Verificado no Simulador de iPhone e no app do Mac, ligados a uma central falsa (nunca a
conversas reais):**
- a tela inicial em seções, com as geradas pelo Noah marcadas;
- o detalhe dos dois tipos de item;
- o painel "Ao vivo" nos dois;
- as abas Presença e Ajustes;
- a aba Fluxo, parada e com item esperando e resposta em andamento: partículas nas
  ligações com a central, consultas ao Cérebro tracejadas, rótulos sem sobreposição;
- a aba Fluxo com o sinal do Cérebro: partículas e contagem nas consultas do Claude Code
  e do Noah e na delegação ao Qwen; com a leitura do Codex em falha, a ligação dele
  tracejada e a legenda "sem sinal ao vivo";
- um item novo aparecendo nos dois;
- "Aceitar" no iPhone chegou à central, e o Mac moveu o item para Respostas e registrou
  no feed.

**Ainda não verificado:**
- um iPhone de verdade;
- o toque no aviso abrindo o detalhe;
- o pedido de permissão de avisos no Mac;
- o refresh em segundo plano do iOS.

**Limite do sinal do Cérebro:** ele conta só chamadas de ferramenta que executam
`cerebro.py buscar|contexto|gravar` e `auxiliares.py`. O hook de início de sessão roda fora
das ferramentas e não entra.

## Problema conhecido

`.inspector` derrubava o app no macOS (laço de layout do AppKit). Por isso o painel "Ao vivo"
é uma coluna comum no Mac e uma folha no iPhone. A janela do Mac tem mínimo de 860×520
pelo mesmo motivo.
