# App Noah nativo (iPhone e Mac)

App SwiftUI para iPhone e Mac. As abas são **Pendências**, **Fluxo**, **Central**, **Presença** e
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
  - as ações Responder (texto livre), Aceitar e Dispensar. Aceitar só aparece quando a
    pergunta é simples, de sim ou não. As geradas pelo Noah são só leitura e só têm
    Dispensar.
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
  - **Cérebro em pedaços:** no Fluxo, o Cérebro aparece dividido nas 8 pastas do cofre (00 Regras a
    07 Templates). Acendem as pastas que algum agente tocou na janela, com um ponto na cor
    de cada um. Os bonequinhos do Claude Code, do Codex e do Noah andam até as pastas que
    consultaram. A contagem por pasta vem do mesmo sinal (`partes`). Com uma central
    antiga, sem essa contagem, nenhuma pasta acende e os bonequinhos ficam parados.
  - O painel "Agora", abaixo do mapa, lista cada ligação viva e as pastas tocadas
    ("1 consulta em Projetos, Decisões").
  - **Sem sinal ao vivo:** se a central é antiga (sem a rota) ou não conseguiu ler uma
    fonte, a ligação fica tracejada. O mapa mostra que o caminho existe sem inventar
    atividade.
  - Nas abas Fluxo e Central, o app relê a central, o painel e o sinal do Cérebro a cada 2 s; fora delas, a cada 20 s, ou 4 s enquanto alguém responde.
  - A animação pausa fora da aba e respeita "Reduzir movimento".
- **Central por voz.** A conversa com o Noah começa por voz: o rosto dele fica grande no
  meio, cresce com o volume da sua fala e mostra a legenda do que ele está entendendo.
  Uma pausa de 1,4 s envia a frase. Ele responde no chat e lê a resposta em voz alta.
  - **Botões embaixo:** o microfone deixa mudo ou liga de novo; a setinha "digitar" sobe o
    chat com o campo de texto (⌘Return envia no Mac), e a setinha para baixo volta para a
    voz; o alto-falante liga ou desliga a leitura das respostas. Mudo e leitura ficam
    guardados entre aberturas.
  - **Mesmo histórico:** voz e digitação mandam para a mesma conversa. O app mantém o mesmo identificador de sessão ao trocar de aba.
  - **Não se ouve a si mesmo:** o microfone fecha enquanto você digita, enquanto o Noah
    pensa e enquanto ele fala.
  - **Só no aparelho:** o reconhecimento usa o português offline do sistema
    (`requiresOnDeviceRecognition`), e o áudio não sai do aparelho. Se o aparelho não tiver
    português offline, a tela avisa em laranja e a setinha continua servindo para digitar.
  - **Leitura curta:** blocos de código, links e marcações de Markdown não são lidos, e a
    resposta longa para na última frase que cabe, com "O resto está no chat."
    (`FalaDoNoah`, em NoahCore).
  - **Permissões:** na primeira vez o sistema pede microfone e reconhecimento de fala. O
    texto do pedido é da Apple e não dá para trocar; o motivo aparece embaixo dele. Se
    você negar, a tela diz onde liberar.
- **Avisos com ação.** Cada pendência nova vira um aviso com Responder, Aceitar e
  Dispensar. Pergunta aberta não tem Aceitar; as só leitura têm apenas Dispensar.
  - Tocar no aviso abre o detalhe daquela pendência.
  - O aviso tem a mesma chave nos dois aparelhos.
  - O aviso some quando a pendência sai da lista ou alguém começa a respondê-la.
  - O número no ícone é a contagem do que espera você.
- **Ilha dinâmica e tela bloqueada (iPhone).** Uma Live Activity resume a central com as
  cores do protótipo `noah-coucou.html`:
  - azul, "Trabalhando": algum agente está respondendo;
  - âmbar, "Esperando você", com "!" e a contagem: há pendência para você;
  - verde, "Tudo pronto", olhos ^^: respostas terminaram há pouco e nada espera você.

  Esperando vence trabalhando, que vence pronto. Sem nada a mostrar, a atividade encerra.
  Tocar na ilha abre a pendência da vez (ou o Fluxo). Ligue e desligue em **Ajustes >
  Ilha dinâmica**. Na primeira vez o iOS pergunta, na tela bloqueada, se permite Atividades
  ao Vivo do Noah.
- **Widgets (iPhone).** O widget "Noah" existe nos tamanhos pequeno e médio da tela de
  início e nos formatos circular, retangular e em linha da tela bloqueada. Ele lê o mesmo
  resumo da ilha pelo App Group `group.com.nicholasbirochi.noah`.
- **Aprovação com Face ID.** Responder, Aceitar e Dispensar pedem Face ID no iPhone e
  Touch ID ou senha no Mac. Se você cancelar, nada é enviado e a pendência continua.
  - A trava fica no modelo do app, então vale para todo botão.
  - Ilha e widgets só abrem o app (links `noah://`): nada aprova sem passar pela trava.
  - As ações do aviso usam `.authenticationRequired`, e o iOS pede o desbloqueio.
  - Desligue em **Ajustes > Aprovação**. Sem senha no aparelho não há o que pedir, e a
    ação segue.
- **Mac.** O app fica na barra de menus mesmo com a janela fechada, para continuar
  avisando, e não aparece no Dock (`LSUIElement`). Há uma única janela principal; os
  atalhos **Abrir Noah** e os links `noah://` reutilizam essa janela. O ícone da barra é o rosto do Noah
  em preto e branco, que muda com o estado e mostra quantas pendências esperam você. Se
  um gerenciador de barra (Thaw, Ice, Bartender) esconder ícones novos, mova o do Noah
  para a parte visível nele. O painel da barra mostra o rosto do Noah no estado atual e até 8 pendências.
  Cada uma tem um botão que abre o app do agente (Claude, ou o ChatGPT, onde fica o Codex)
  e "Aceitar" (só em pergunta simples), que pede Touch ID. Há também "Abrir Noah" e "Sair".
- **Ilha no notch (Mac).** Uma pílula preta no notch, ou no meio da barra de menus se a
  tela não tiver notch, nas mesmas três cores da ilha do iPhone.
  - Passar o mouse ou clicar abre o cartão com as pendências e o que está sendo respondido.
  - Fecha só uns 0,6 s depois que o mouse sai. Uma margem de 20 pt em volta do cartão, e
    tudo acima dele até o topo da tela, ainda contam como "em cima": encostar na borda ou
    na sombra não fecha.
  - Quando chega pendência nova, abre sozinha por 4 s.
  - **Alcove.** O Alcove desenha por cima de qualquer janela no meio do topo. Com ele
    aberto, a ilha do Noah encosta à direita da área dele (ou à esquerda, se não couber).
    Em tela sem notch (monitor externo) ela fica à direita do Alcove, mas reserva os
    últimos 400 pt da barra para os ícones (Thaw, relógio); se não couber, vai para a esquerda.
    Desligue em **Ajustes > Encostar ao lado do Alcove**. O Alcove é fechado e licenciado,
    sem API de integração: mexer no app dele quebraria a assinatura e a licença, por isso o
    Noah só detecta onde ele está.
  - Liga e desliga em **Ajustes > Mostrar a ilha no alto da tela**.
- **Ícone.** Um botzinho preto e branco, sem antena: rosto claro em fundo grafite. Os
  PNGs do iPhone e do Mac e o `src/assets/AppIcon.icns` saem do mesmo script:
  `.venv/bin/python src/scripts/generate_app_icon.py` (precisa do PyObjC da `.venv`).
- **Atualização.** A cada 20 s, e a cada 4 s enquanto alguém responde. No iPhone, com o
  app fechado, o iOS acorda o app de tempos em tempos (`BGAppRefresh`). Sem conta paga
  da Apple não há push (APNs). Por isso a ilha e os widgets só mudam quando o app roda ou
  o iOS o acorda, e a Live Activity só começa com o app aberto. A ilha marca o resumo como
  velho depois de 30 min sem atualizar.

**Limites do iOS:** o app não consegue fechar nem apagar outros apps, e não existem widgets
do Mac por enquanto.

O token fica no Keychain. O endereço da central e o texto do "Aceitar" (padrão "Pode
seguir.") ficam em UserDefaults.

## Gerar e abrir

O projeto Xcode é gerado a partir de `project.yml` com [XcodeGen](https://github.com/yonaskolb/XcodeGen).
O `Noah.xcodeproj` gerado também está no repositório, para abrir sem instalar nada.

```bash
cd apple && xcodegen
```

O app do Mac é assinado localmente (`-`) e não precisa de conta.

### Instalar com conta pessoal sem App Groups

Se o perfil de assinatura não permitir App Groups, use o esquema **Noah-iOS-Pessoal**. Ele
mantém as telas, Face ID e a extensão WidgetKit necessária à Ilha dinâmica (Live Activity),
mas não inclui o widget de resumo da tela inicial/bloqueada. O esquema completo **Noah-iOS** continua incluindo widgets e exige o App
Group configurado na conta.

Para instalar a variante pessoal pelo terminal com uma equipe selecionada no Xcode:

```bash
xcodebuild -project Noah.xcodeproj -scheme Noah-iOS-Pessoal -destination 'platform=iOS,id=SEU-UDID' -allowProvisioningUpdates build
```

### Instalar no iPhone

A conta gratuita da Apple serve, mas o perfil vale 7 dias: depois disso, instale de novo.

1. No Xcode, **Settings > Accounts**, entre com o seu Apple ID. Ele cria o time pessoal.
2. Copie `Config/Local.xcconfig.example` para `Config/Local.xcconfig` e ponha o Team ID
   desse time. O arquivo é ignorado pelo git, e o repositório é público.
3. Ligue o iPhone no Mac pelo cabo, desbloqueie e toque em "Confiar".
4. No iPhone, ligue **Ajustes > Privacidade e Segurança > Modo de Desenvolvedor** (ele
   reinicia).
5. Abra `Noah.xcodeproj`, escolha o esquema **Noah-iOS** e o seu iPhone, e rode (⌘R).
   Pela linha de comando:

   ```bash
   xcodebuild -project Noah.xcodeproj -scheme Noah-iOS -configuration Release -destination 'generic/platform=iOS' -derivedDataPath "$TMPDIR/noah-dd-device" -allowProvisioningUpdates build
   xcrun devicectl device install app --device <UDID do iPhone> "$TMPDIR/noah-dd-device/Build/Products/Release-iphoneos/Noah.app"
   ```

   O UDID aparece em `xcrun devicectl list devices`. O build fica fora do OneDrive porque
   a sincronia dele estraga a assinatura.
6. Na primeira vez, o iPhone pede para confiar no desenvolvedor: **Ajustes > Geral > VPN e
   Gerenciamento de Dispositivos**, toque no seu Apple ID e em "Confiar".
7. Ligue o app à central pelo Wi-Fi de casa (próxima seção).

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
central, comparação de avisos, feed de atividade, as ligações da aba Fluxo, o resumo da
ilha, as regras da ilha no notch do Mac (abrir, fechar, encostar no Alcove) e os links
`noah://`. Ela tem
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
- a aba Fluxo com o Cérebro em pedaços (só no Mac): pastas acesas por agente, bonequinhos
  andando até elas e rótulos das ligações com o Cérebro fora do bloco dele;
- um item novo aparecendo nos dois;
- "Aceitar" no iPhone chegou à central, e o Mac moveu o item para Respostas e registrou
  no feed;
- a ilha dinâmica nos três visuais (âmbar com "!" e contagem, azul, verde com ^^) e a Live
  Activity na tela bloqueada;
- o link `noah://pendencia?chave=…` abrindo o detalhe da pendência;
- o Face ID antes de Aceitar: com rosto não reconhecido e "Cancelar", nada chegou à central;
  com rosto reconhecido, a resposta chegou;
- o app do Mac compila com o painel novo da barra de menus;
- a ilha no notch do Mac: abre com o mouse, continua aberta com o mouse na borda e fecha
  depois que ele sai; com o Alcove aberto, encosta ao lado dele;
- o ícone novo no Mac e na tela de início do Simulador.
- a Central por voz no Simulador: o rosto grande com os três botões, o aviso laranja
  quando falta português offline, e a setinha subindo o chat, com uma mensagem digitada
  chegando à central falsa e a resposta aparecendo;
- as regras de fechar a frase e de limpar a resposta antes de ler (`VozTests`).

**Atualização de 21/10/2026:** 82 testes Swift e 129 testes Python da Central, presença e
visualizador passaram. O esquema pessoal foi assinado e instalado num iPhone real. A
primeira abertura exige confiar no perfil nas configurações do próprio aparelho; a
instalação não comprova a conversa por voz nem a comunicação pela rede.

**Ainda não verificado:**
- a primeira abertura e a conversa num iPhone real após confiar na assinatura;
- o toque no aviso abrindo o detalhe;
- o pedido de permissão de avisos no Mac;
- o refresh em segundo plano do iOS;
- o Cérebro em pedaços no iPhone (layout estreito, 4 colunas). O target do iOS compila,
  mas a tela não foi vista. A janela do Mac tem largura mínima de 860, por isso ele usa
  sempre o layout largo.
- os widgets colocados na tela de início e na tela bloqueada (compilam e vão no app, mas
  adicioná-los pede edição manual da tela);
- o painel da barra de menus aberto na tela, o Touch ID no Mac e o botão que abre o app
  do agente.
- a voz de verdade: falar e ver a frase sair sozinha, e a resposta lida em voz alta. O
  Simulador não tem português offline, então isso pede o Mac ou um iPhone.

**Limite do sinal do Cérebro:** ele conta só chamadas de ferramenta que executam
`cerebro.py buscar|contexto|gravar` e `auxiliares.py`. O hook de início de sessão roda fora
das ferramentas e não entra. As pastas vêm dos caminhos de nota que a própria resposta da
ferramenta trouxe (ou do `--destino` num registro). Uma consulta que não citou nenhum
caminho conta, mas não acende pasta.

## Problema conhecido

`.inspector` derrubava o app no macOS (laço de layout do AppKit). Por isso o painel "Ao vivo"
é uma coluna comum no Mac e uma folha no iPhone. A janela do Mac tem mínimo de 860×520
pelo mesmo motivo.
