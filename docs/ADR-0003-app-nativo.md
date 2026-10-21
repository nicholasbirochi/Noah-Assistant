# ADR-0003: App Noah nativo para iPhone e Mac, sincronizado pela central

- **Status:** aceito (primeira versão em `apple/`)
- **Data:** 2026-10-20

## Contexto

A central de pendências do ADR-0002 já tinha uma página web, que o iPhone pode
"Adicionar à Tela de Início". O usuário pediu um aplicativo de verdade, "nada de web",
para o iPhone e para o Mac. Os dois aparelhos precisam "se conversar":

- cada um avisa o que chegou;
- dá para aceitar, responder ou dispensar em qualquer um deles;
- o que se faz num aparelho vale para o outro.

Depois vieram mais dois pedidos:

- a tela inicial mostra só as tarefas a fazer, e as geradas automaticamente pelo Noah
  aparecem marcadas, com o detalhe ao tocar;
- um painel lateral mostra as atualizações em tempo real. Ele fica **no mesmo app
  Noah**, sem criar outro app.

Restrições: sem API paga, sem conta paga da Apple, sem dependência nova significativa e
repositório público (nenhum Team ID ou dado pessoal no git).

## Decisão

1. **SwiftUI, um projeto para os dois sistemas** (`apple/project.yml`, gerado com
   XcodeGen). As abas são Pendências, Presença, Fluxo e Ajustes. A lógica sem tela fica no
   pacote `NoahCore`, que tem testes (`swift test`): modelos, cliente HTTP da central,
   comparação de avisos, feed de atividade e ligações da aba Fluxo.
2. **A central é a fonte da verdade.** Os dois apps só leem e escrevem nas rotas que já
   existem: `GET /central/api/pendencias`, `GET /central/api/presenca`,
   `POST /central/api/responder` e `POST /central/api/dispensar`. Nenhum dos apps guarda
   estado próprio das pendências, e a central não precisou mudar. A sincronia é cada app
   reler a central:
   - a cada 20 s;
   - a cada 4 s enquanto há resposta em andamento;
   - logo depois de cada ação.
3. **Avisos locais com ação.** Não há push (APNs), porque ele exige conta paga. Cada
   aparelho compara a lista nova com o que já avisou (`Sincronia.comparar`):
   - **Item novo ou alterado:** vira aviso com Responder, Aceitar e Dispensar. Aceitar
     só entra numa pergunta simples (`simples`); nas outras o aviso tem Responder e
     Dispensar, e os só-leitura só têm Dispensar.
   - **Item que sumiu ou que alguém começou a responder:** o aviso é apagado.
   - **Identificador:** é a chave da pendência, igual nos dois aparelhos.

   O Mac fica na barra de menus para continuar avisando com a janela fechada. O iPhone usa
   `BGAppRefresh`, e o iOS decide quando acordar o app.
4. **Tela inicial só com tarefas.** São linhas curtas em seções: Para fazer, Geradas
   automaticamente (fonte `noah`, marcadas e só leitura) e Respostas. O detalhe abre ao
   tocar e mostra o porquê, a origem, o projeto e as ações.
5. **Painel "Ao vivo" no mesmo app.** Ele mostra as contagens, a última sincronização e o
   feed do que mudou (`Atividade.eventos`). No Mac é uma coluna fixa ao lado do detalhe; no
   iPhone, uma folha. `.inspector` foi descartado porque derrubava o app no macOS.
6. **Aba Fluxo só anima o que a central vê.** O mapa (`Fluxo.ligacoes`) liga agentes,
   Cérebro, Qwen local, central e aparelhos. As ligações com a central vivem das
   pendências e respostas. As consultas ao Cérebro e as tarefas delegadas ao Qwen vivem
   do sinal `GET /central/api/cerebro` (ADR-0002, ponto 7), contado numa janela de 10
   minutos. Sem a rota (central antiga, 404) ou com a fonte em falha, a ligação fica
   tracejada com "sem sinal ao vivo": o caminho existe, mas a central não o enxerga, e o
   app não inventa atividade. O Cérebro aparece em pedaços, nas 8 pastas do cofre
   (`Fluxo.Parte`), e acende só as que o sinal conta em `partes`. Os bonequinhos de cada
   agente andam até essas pastas. Sem `partes` (central antiga), `Fluxo.partes` devolve
   nil e nada acende.
7. **Segredos fora do git.** O token fica no Keychain. O Team ID fica em
   `Config/Local.xcconfig`, que o git ignora, e o repositório leva só o `.example`.
8. **Ilha, widgets e tela bloqueada leem um resumo só.** O app calcula `Ilha.resumo`
   (esperando vence trabalhando, que vence pronto), grava no App Group
   `group.com.nicholasbirochi.noah` e atualiza a Live Activity. A extensão de widgets lê
   esse resumo e não fala com a central. Sem APNs, a Live Activity só começa com o app
   aberto e fica velha depois de 30 min sem atualizar.
9. **Aprovar pede o dono do aparelho.** Responder, Aceitar e Dispensar passam pela trava
   do modelo (`Cadeado`, LocalAuthentication: Face ID, Touch ID ou senha). Ilha e widgets
   só levam links `noah://`, e as ações do aviso usam `.authenticationRequired`. Assim
   nenhum caminho aprova sem desbloqueio. A trava pode ser desligada em Ajustes.
10. **Ilha no notch do Mac ao lado do Alcove, sem mexer nele.** As regras de abrir, fechar
    e posicionar ficam em `IlhaNotch` (NoahCore, com testes): fecha 0,6 s depois que o
    mouse sai de uma área com 20 pt de margem. O Alcove é fechado e licenciado e não tem
    API; alterar o app dele quebraria a assinatura e a licença. Por isso o Noah lê onde a
    janela do Alcove está e encosta ao lado dela.

## Consequências

- Para o iPhone participar, a central precisa escutar no IP da rede com token, e o Mac
  também deve apontar para esse IP. O IP pode mudar (DHCP), e fora de casa ainda falta uma
  VPN.
- Com o app fechado no iPhone, o aviso pode atrasar: depende do iOS acordar o app.
- Com a conta gratuita, o app no iPhone precisa ser reinstalado a cada 7 dias.
- A página web do ADR-0002 continua existindo. O app nativo não a substitui na central, só
  no uso diário.
- O sinal do Cérebro conta só chamadas de ferramenta registradas nos transcripts e as
  consultas do próprio Noah. Uma consulta feita fora disso (o hook de início de sessão,
  um terminal à parte) não aparece.
- Verificado só no Simulador e no Mac, com uma central falsa. Ainda falta testar num
  iPhone real, o toque no aviso abrindo o detalhe, o refresh em segundo plano, os widgets
  colocados nas telas e o painel da barra de menus com Touch ID. O build para aparelho
  precisa de um Apple ID no Xcode (conta gratuita: perfil de 7 dias).
- O iOS não deixa o app fechar nem apagar outros apps, e não há widgets do Mac.
