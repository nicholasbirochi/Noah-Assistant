# Renomeacao para Noah

## O que mudou

Marca, prompts, CLI, HUD, portal, notificacoes, classe `NoahMenuBarApp`,
nome/identificador do bundle, exemplo de LaunchAgent, documentacao e fixtures
passaram a usar Noah.

- App novo: `Noah.app`, bundle `com.nicholasbirochi.noah`.
- Entrada nova: `src/scripts/noah_app_main.py`.
- LaunchAgent: `com.nicholasbirochi.noah.menubar.plist.example`.
- Configuracao: prefixo `NOAH_`, inclusive perfil `NOAH_APPLICATION_*`.
- Encerramento aceita somente os comandos Noah e "encerrar".
- O indexador exclui `PROJECT_ROOT`, acompanhando futura mudanca de pasta.
- Plano atualizado: `NOAH_Apple_Private_AI_Cluster_MASTER_v3.zip`.
- Pasta real: `54 - Noah`. GitHub e origin: `nicholasbirochi/Noah-Assistant`.
- `/Applications/Noah.app` instalado e aberto via LaunchServices.
- LaunchAgent Noah instalado e carregado; o antigo foi descarregado.
- Estado privado movido localmente para Application Support/Noah, fora do
  OneDrive, sem ler ou alterar o conteudo de sessoes, perfis ou voz.
- Prompt de continuidade do Claude removido a pedido do usuario.

## Identidade unica

As configuracoes especificas do assistente usam somente `NOAH_*`.
As configuracoes locais foram migradas preservando os valores privados.
O arquivo confidencial `application_profile.env` usa `NOAH_APPLICATION_*`.
O estado vive em Application Support/Noah e pode ser configurado com
`NOAH_LOCAL_STATE_DIR`. Nenhum alias de marca e usado no codigo ativo.

Voz: `voice/noah_reference.wav`. Lock: `noah.pid`. O portal usa
`noah_portal_*` e migra namespaces anteriores sem perder filtros/selecao.
A unica entrada de app e `src/scripts/noah_app_main.py`. Os caminhos do
venv usam `54 - Noah`. Backups de reversao ficam fora da arvore do projeto.

## Instalacao e backups locais

O app e LaunchAgent antigos foram preservados em:
`~/Library/Application Support/Noah/Backups/before-noah-only/`.

O novo servico abre `/Applications/Noah.app` com `/usr/bin/open -g`, mantendo
a identidade do bundle. O servico anterior foi descarregado; nao ha dois
servicos ativos.
O processo `open` termina com sucesso; o app continua independente, portanto
`launchctl` mostrar o launcher como "not running" nao indica queda do app.

O exemplo no repositorio reflete a configuracao instalada. Se a pasta mudar
novamente, reconstrua o bundle alias e revise os caminhos do LaunchAgent.
Os logs do launcher ficam em `~/Library/Logs/Noah/menubar.log`; esse arquivo
nao captura automaticamente toda a saida do app iniciado por LaunchServices.

Para reconstruir, na raiz do repo:

```bash
.venv/bin/python src/scripts/build_app.py
```

## O que ainda depende de validacao humana

- Confirmar o menu e a permissao de microfone da nova identidade, e testar voz.
- O gatilho padrao e duas palmas. "Hey Noah" requer um detector Noah local
  treinado e validado; nenhuma outra palavra e usada como fallback.
  openWakeWord usa `NOAH_WAKE_WORD_MODEL_PATH`; Porcupine usa
  `NOAH_PORCUPINE_MODEL_PATH` e AccessKey. Nao ha download automatico.
- Conferir atalhos fixados no Dock e pastas salvas nos editores, se usados.
- Validar um login/reinicio real; a abertura pelo novo LaunchAgent ja passou.

## Validacao realizada

- Baseline original: 792 testes. Identidade unica Noah: 808 testes passaram,
  incluindo ativacao, configuracao e preservacao dos filtros do portal.
- CLI `--help`: nome `noah` confirmado; pip funciona no novo venv.
- Plists do app/servico validados; GitHub e origin confirmados com o novo nome.
- Novo LaunchAgent carregado, ultimo exit code 0; processo Noah confirmado vivo.
- `codesign --verify --verbose=4` passou para o bundle instalado.
  A verificacao `--deep --strict` falhou com "No such file or directory"
  no novo bundle e tambem no app antigo antes de arquiva-lo; a assinatura
  basica e a abertura pelo LaunchAgent passaram.
  Causa (investigada em 2026-10-18, sem reassinar o app instalado): quem falha
  e o `--strict`, nao o `--deep` (`--deep` sozinho passa). O modo alias do
  py2app monta o bundle com links simbolicos: `MacOS/python` e
  `Resources/AppIcon.icns` apontam com caminho absoluto para o `.venv` e o
  `src/` do projeto, e `Resources/lib/python3.12/config` (para
  `.venv/lib/python3.12/config`, que um venv nao tem) e `site.pyc` (para
  `../../site.pyc`, que o py2app nao gera) apontam para lugar nenhum. O
  `--strict` recusa link quebrado ("No such file or directory") e, numa copia
  sem esses dois links e reassinada, recusa tambem link para fora do bundle
  ("invalid destination for symbolic link in bundle"). Ou seja, e limite do
  modo alias, nao defeito da assinatura: so um bundle congelado (sem links
  para fora) passaria no `--strict`, e o congelamento foi evitado de proposito
  (ver `src/scripts/build_app.py`). Nada foi mudado na assinatura.
- Inspecao visual indisponivel por timeout da automacao de interface.
- Nao foram testados microfone, voz, modelos, sites reais ou reinicio do Mac.

## Plano original e reversao

O plano de origem permanece intacto no backup local como `source-plan.zip`.
O plano Noah e contexto, nao evidencia de implementacao. Configuracoes
privadas e backups nao devem entrar no Git nem no cofre de conhecimento.
O historico anterior tem backup em `history.bundle`, fora do repositorio.

Revise o diff antes de reverter. Reverter o patch da renomeacao restaura as
fontes antigas; remover apenas os documentos/copias novos e outra decisao.
Para reverter a instalacao, pare Noah, descarregue o servico e restaure
app/LaunchAgent/configuracoes do backup. A renomeacao no GitHub e uma operacao
separada da reversao do patch. Nao use reset/clean global num checkout com
trabalho de outras pessoas.
