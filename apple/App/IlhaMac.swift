#if os(macOS)
import AppKit
import NoahCore
import SwiftUI

/// A ilha do Noah no alto da tela do Mac, como no protótipo `noah-coucou.html`:
/// uma pílula preta no notch (ou no meio da barra de menus, em telas sem notch)
/// com o rosto no estado atual. Passe o mouse ou clique para abrir as pendências.
///
/// A janela é um painel sem borda que não ativa o app. Fechada, deixa o mouse
/// passar (`ignoresMouseEvents`), para não roubar cliques da barra de menus; a
/// posição do mouse é lida a cada 0,1 s, o que não pede permissão de
/// Acessibilidade.
///
/// Aberta, cada item abre o detalhe por baixo (a última mensagem do agente) e um
/// campo para escrever a resposta. Enquanto você escreve, a ilha não fecha quando
/// o mouse sai; fecha quando o campo perde o foco (clique em outro app).
///
/// O Alcove (outro app de ilha) desenha por cima de qualquer janela no meio do
/// topo. Com ele aberto, a ilha do Noah encosta ao lado da área dele, em vez de
/// ficar escondida embaixo (ajuste "Encostar ao lado do Alcove").
@MainActor @Observable
final class IlhaMac {
    static let shared = IlhaMac()

    /// Fechada: a pílula; aberta: o painel com as pendências.
    private(set) var aberta = false
    /// Largura e altura do notch (zero sem notch) e altura da barra de menus.
    private(set) var notch = CGSize.zero
    private(set) var barra: CGFloat = 24
    /// Onde a pílula fica dentro do painel: no meio, ou encostada ao lado do Alcove.
    private(set) var alinhamento = IlhaNotch.Alinhamento.centro
    /// Tamanho real do conteúdo aberto, medido pela vista, para saber onde o mouse sai.
    var tamanhoAberto = CGSize(width: IlhaMac.larguraAberta, height: 160)
    /// O campo de resposta da ilha tem o foco: segura a ilha aberta.
    @ObservationIgnored var escrevendo = false

    static let larguraAberta: CGFloat = 440
    static let alturaMaxima: CGFloat = 560
    /// Altura máxima da lista de itens; passou disso, ela rola.
    static let alturaLista: CGFloat = 380
    /// Folga dos lados do painel para a sombra do cartão aberto.
    static let margemSombra: CGFloat = 20
    static let thaw = "com.stonerl.Thaw"
    static let alcove = "com.henrikruscon.Alcove"

    @ObservationIgnored var modelo: Modelo?
    @ObservationIgnored private var painel: PainelIlha?
    @ObservationIgnored private var relogio: Timer?
    @ObservationIgnored private var seguidor = IlhaNotch.Seguidor()
    @ObservationIgnored private var observador: NSObjectProtocol?
    @ObservationIgnored private var passos = 0

    /// Liga ou desliga conforme Ajustes. Chamado ao abrir o app e ao mudar o ajuste.
    func aplicar() {
        Ajustes.ilhaLigada ? ligar() : desligar()
    }

    private func ligar() {
        guard painel == nil, let modelo else { return }
        let p = PainelIlha()
        let vista = NSHostingView(rootView: IlhaDoNotch().environment(modelo).environment(self))
        vista.sizingOptions = []
        p.contentView = vista
        painel = p
        posicionar()
        p.orderFrontRegardless()
        observador = NotificationCenter.default.addObserver(
            forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main
        ) { [weak self] _ in MainActor.assumeIsolated { self?.posicionar() } }
        relogio = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.seguirMouse() }
        }
    }

    private func desligar() {
        relogio?.invalidate()
        relogio = nil
        if let observador { NotificationCenter.default.removeObserver(observador) }
        observador = nil
        painel?.orderOut(nil)
        painel = nil
        _ = seguidor.fechar()
        aberta = false
    }

    /// A tela com notch, se houver; senão a principal.
    private var tela: NSScreen? {
        NSScreen.screens.first { $0.safeAreaInsets.top > 0 } ?? NSScreen.main ?? NSScreen.screens.first
    }

    private func posicionar() {
        guard let painel, let tela else { return }
        let f = tela.frame
        if tela.safeAreaInsets.top > 0,
           let esquerda = tela.auxiliaryTopLeftArea, let direita = tela.auxiliaryTopRightArea {
            notch = CGSize(width: f.width - esquerda.width - direita.width, height: tela.safeAreaInsets.top)
        } else {
            notch = .zero
        }
        barra = max(22, f.maxY - tela.visibleFrame.maxY)
        let largura = IlhaMac.larguraAberta + IlhaMac.margemSombra * 2
        let alcove = faixaDoAlcove(em: tela)
        // O Alcove cobre o notch: ao lado dele, a pílula é da altura da barra de menus.
        if alcove != nil { notch = .zero }
        // Sem notch (monitor externo), a ilha fica à direita do Alcove, mas sem
        // chegar nos ícones da barra de menus (os do Thaw, o relógio).
        let limite = tela.safeAreaInsets.top == 0 ? f.maxX - IlhaNotch.reservaIcones : nil
        let thaw = NSRunningApplication.runningApplications(withBundleIdentifier: IlhaMac.thaw).first
        // Preferência do usuário: à direita, dois ícones (~56 pt) mais perto do centro.
        let pos = IlhaNotch.posicao(tela: f.minX...f.maxX, largura: largura, alcove: alcove,
                                    limiteDireita: limite, recuoDireita: thaw == nil ? 0 : 56)
        if alinhamento != pos.alinhamento { alinhamento = pos.alinhamento }
        atualizarCamada(thawEmExecucao: thaw != nil)
        let quadro = NSRect(x: pos.x, y: f.maxY - IlhaMac.alturaMaxima, width: largura, height: IlhaMac.alturaMaxima)
        if painel.frame != quadro { painel.setFrame(quadro, display: true) }
    }

    /// O painel aberto cobre os ícones vizinhos; fechado deixa o Thaw acessível.
    private func atualizarCamada(thawEmExecucao: Bool? = nil) {
        let thaw = thawEmExecucao ?? !NSRunningApplication.runningApplications(withBundleIdentifier: IlhaMac.thaw).isEmpty
        let deslocamento = IlhaNotch.deslocamentoDaCamada(aberta: aberta, thawEmExecucao: thaw)
        painel?.level = NSWindow.Level(rawValue: NSWindow.Level.statusBar.rawValue + deslocamento)
    }

    /// Faixa horizontal das janelas do Alcove no alto desta tela, se ele estiver aberto.
    /// A lista de janelas dá dono e posição sem pedir permissão de Gravação de Tela.
    private func faixaDoAlcove(em tela: NSScreen) -> ClosedRange<CGFloat>? {
        guard Ajustes.ilhaAoLadoDoAlcove,
              let app = NSRunningApplication.runningApplications(withBundleIdentifier: IlhaMac.alcove).first,
              let lista = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements],
                                                     kCGNullWindowID) as? [[String: Any]] else { return nil }
        // A lista usa origem no alto da tela principal; o AppKit, embaixo.
        let alturaPrincipal = NSScreen.screens.first?.frame.maxY ?? tela.frame.maxY
        let f = tela.frame
        var faixa: ClosedRange<CGFloat>?
        for w in lista where (w[kCGWindowOwnerPID as String] as? pid_t) == app.processIdentifier {
            guard let b = w[kCGWindowBounds as String] as? NSDictionary,
                  let r = CGRect(dictionaryRepresentation: b) else { continue }
            let topo = alturaPrincipal - r.minY
            // Só a área do topo (a ilha dele), não a janela de ajustes.
            guard abs(topo - f.maxY) < 2, r.minX >= f.minX - 1, r.maxX <= f.maxX + 1,
                  r.width < f.width * 0.6 else { continue }
            faixa = faixa.map { min($0.lowerBound, r.minX)...max($0.upperBound, r.maxX) } ?? r.minX...r.maxX
        }
        return faixa
    }

    /// Retângulo da pílula (ou do painel aberto) em coordenadas de tela.
    private func zona(_ tamanho: CGSize) -> NSRect? {
        guard let painel else { return nil }
        let f = painel.frame
        let x: CGFloat
        switch alinhamento {
        case .centro: x = f.midX - tamanho.width / 2
        case .esquerda: x = f.minX + IlhaMac.margemSombra
        case .direita: x = f.maxX - IlhaMac.margemSombra - tamanho.width
        }
        return NSRect(x: x, y: f.maxY - tamanho.height, width: tamanho.width, height: tamanho.height)
    }

    private func seguirMouse() {
        guard let painel, let modelo else { return }
        // A cada 3 s confere se o Alcove abriu, fechou ou mudou de lugar.
        passos += 1
        if passos % 30 == 0 && !aberta { posicionar() }
        let fechada = IlhaNotch.tamanhoFechado(modelo.resumo.estado, notch: notch, barra: barra)
        let alvo = aberta ? tamanhoAberto : fechada
        let dentro = zona(alvo).map { IlhaNotch.zonaDeHover($0, aberta: aberta) }?
            .contains(NSEvent.mouseLocation) ?? false
        // Clicar em outro app tira a tecla do painel, e a ilha volta a fechar ao sair.
        let segurar = escrevendo && painel.isKeyWindow
        executar(seguidor.passo(dentro: dentro, agora: Date(), segurar: segurar))
        painel.ignoresMouseEvents = !aberta
    }

    /// Recalcula a posição agora (ao mudar o ajuste do Alcove).
    func reposicionar() { posicionar() }

    func abrir() { executar(seguidor.abrir()) }
    func fechar() { executar(seguidor.fechar()) }
    func alternar() { aberta ? fechar() : abrir() }

    /// Uma pendência nova chegou: abre sozinha por alguns segundos, como a ilha do iPhone.
    func espiar() {
        guard painel != nil else { return }
        executar(seguidor.espiar(agora: Date()))
    }

    private func executar(_ acao: IlhaNotch.Acao) {
        switch acao {
        case .abrir:
            withAnimation(.spring(response: 0.38, dampingFraction: 0.78)) { aberta = true }
        case .fechar:
            withAnimation(.spring(response: 0.32, dampingFraction: 0.9)) { aberta = false }
            escrevendo = false
            // Devolve o teclado: fechada, a pílula não deve receber o que você digita.
            if let painel, painel.isKeyWindow {
                painel.orderOut(nil)
                painel.orderFrontRegardless()
            }
        case .nada:
            break
        }
        if acao != .nada { atualizarCamada() }
        painel?.ignoresMouseEvents = !aberta
    }

    /// Traz a janela principal do Noah; abre uma nova pelo link `noah://` se estiver fechada.
    func mostrarJanela(_ url: URL = Atalho.lista) {
        modelo?.ir(url)
        fechar()
        NSApp.activate()
        if let janela = NSApp.windows.first(where: { $0.identifier?.rawValue.hasPrefix("principal") == true }) {
            janela.makeKeyAndOrderFront(nil)
        } else {
            NSWorkspace.shared.open(url)
        }
    }
}

/// Painel sem borda em todos os espaços e em tela cheia; sua camada acompanha aberto/fechado.
final class PainelIlha: NSPanel {
    init() {
        super.init(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel],
                   backing: .buffered, defer: false)
        isFloatingPanel = true
        level = .statusBar
        collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle]
        backgroundColor = .clear
        isOpaque = false
        hasShadow = false
        hidesOnDeactivate = false
        isMovable = false
        ignoresMouseEvents = true
        animationBehavior = .none
    }

    // Recebe cliques sem ativar o app; os botões funcionam no primeiro clique.
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
    // Sem isso o AppKit empurra a janela para baixo da barra de menus.
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
}

// MARK: - Vista

struct IlhaDoNotch: View {
    @Environment(Modelo.self) private var modelo
    @Environment(IlhaMac.self) private var ilha
    @Environment(\.accessibilityReduceMotion) private var semMovimento
    /// Itens com o detalhe aberto, pela chave.
    @State private var expandidas: Set<String> = []
    @State private var alturaLista: CGFloat = 0
    @FocusState private var foco: String?

    var body: some View {
        let r = modelo.resumo
        let fechada = IlhaNotch.tamanhoFechado(r.estado, notch: ilha.notch, barra: ilha.barra)
        VStack(alignment: ancora.horizontal, spacing: 0) {
            ZStack(alignment: ancora.alignment) {
                if ilha.aberta {
                    aberto(r)
                        // Mede o cartão em si: é a área que segura a ilha aberta.
                        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: {
                            ilha.tamanhoAberto = CGSize(width: IlhaMac.larguraAberta, height: $0)
                        }
                        .transition(.opacity.combined(with: .scale(scale: 0.92, anchor: ancora.point)))
                } else {
                    fechado(r, tamanho: fechada)
                        .transition(.opacity)
                }
            }
            .frame(width: ilha.aberta ? IlhaMac.larguraAberta : fechada.width,
                   height: ilha.aberta ? nil : fechada.height, alignment: .top)
            .background(
                FormaIlha(raio: ilha.aberta ? 28 : min(14, fechada.height / 2))
                    .fill(.black)
                    .shadow(color: .black.opacity(ilha.aberta ? 0.45 : 0), radius: 16, y: 6)
            )
            .overlay(
                FormaIlha(raio: ilha.aberta ? 28 : min(14, fechada.height / 2))
                    .stroke(r.estado.corClara.opacity(r.estado == .quieto ? 0 : (ilha.aberta ? 0.25 : 0.4)),
                            lineWidth: 1)
            )
            .onTapGesture { if !ilha.aberta { ilha.abrir() } }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, ilha.alinhamento == .centro ? 0 : IlhaMac.margemSombra)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: ancora.alignment)
        .animation(semMovimento ? nil : .spring(response: 0.38, dampingFraction: 0.8), value: r.estado)
        .onChange(of: r.esperando) { antes, depois in
            if IlhaNotch.deveEspiar(antes: antes, depois: depois) { ilha.espiar() }
        }
        .onChange(of: foco) { _, campo in ilha.escrevendo = campo != nil }
        .environment(\.colorScheme, .dark)
    }

    /// Canto onde a ilha se apoia: o meio do topo, ou o lado que encosta no Alcove.
    private var ancora: (alignment: Alignment, horizontal: HorizontalAlignment, point: UnitPoint) {
        switch ilha.alinhamento {
        case .centro: (.top, .center, .top)
        case .esquerda: (.topLeading, .leading, .topLeading)
        case .direita: (.topTrailing, .trailing, .topTrailing)
        }
    }

    // MARK: Fechada

    @ViewBuilder
    private func fechado(_ r: ResumoIlha, tamanho: CGSize) -> some View {
        let rosto = max(14, min(20, tamanho.height - 10))
        if ilha.notch.width > 0 {
            // Rosto na asa esquerda, texto na direita; o meio é o próprio notch.
            HStack(spacing: 0) {
                Rosto(estado: r.estado, tamanho: rosto)
                    .padding(.leading, 12)
                Spacer(minLength: ilha.notch.width)
                if r.estado != .quieto {
                    Text(r.curto).font(.system(size: 11, weight: .semibold, design: .rounded))
                        .foregroundStyle(r.estado.corClara).lineLimit(1).minimumScaleFactor(0.7)
                        .padding(.trailing, 12)
                }
            }
            .frame(width: tamanho.width, height: tamanho.height)
        } else {
            HStack(spacing: 7) {
                Rosto(estado: r.estado, tamanho: rosto)
                Text(r.curto).font(.system(size: 12, weight: .semibold, design: .rounded))
                    .foregroundStyle(r.estado.corClara).lineLimit(1)
                if r.estado == .trabalhando { Pontos(cor: r.estado.corClara, parado: semMovimento) }
            }
            .padding(.horizontal, 10)
            .frame(width: tamanho.width, height: tamanho.height)
        }
    }

    // MARK: Aberta

    private func aberto(_ r: ResumoIlha) -> some View {
        // Perguntas primeiro; depois as respostas prontas, na ordem da central.
        let livres = modelo.itens.filter { !$0.respondendo }
        let abertas = livres.filter(\.pergunta) + livres.filter { !$0.pergunta }
        let rodando = Sincronia.jobsVisiveis(modelo.jobs, agora: Date().timeIntervalSince1970).filter(\.rodando)
        return VStack(alignment: .leading, spacing: 10) {
            // Espaço do notch (ou da barra de menus) para nada ficar escondido atrás dele.
            Color.clear.frame(height: max(ilha.notch.height, ilha.barra) - 6)

            HStack(spacing: 10) {
                Rosto(estado: r.estado, tamanho: 34)
                VStack(alignment: .leading, spacing: 1) {
                    Text(r.estado.titulo).font(.system(size: 15, weight: .bold, design: .rounded))
                        .foregroundStyle(r.estado.corClara)
                    Text(subtitulo(r)).font(.caption).foregroundStyle(.white.opacity(0.6)).lineLimit(1)
                }
                Spacer()
                botaoRedondo("arrow.clockwise", ajuda: "Atualizar") { Task { await modelo.atualizar() } }
                botaoRedondo("macwindow", ajuda: "Abrir Noah") { ilha.mostrarJanela() }
            }

            if let erro = modelo.erro {
                Label("Sem central: \(erro)", systemImage: "wifi.exclamationmark")
                    .font(.caption).foregroundStyle(Color(hex: 0xFF8A80)).lineLimit(2)
            }

            if abertas.isEmpty && rodando.isEmpty {
                Text(r.estado == .pronto ? "Respostas prontas. Nada espera você." : "Nada esperando você.")
                    .font(.callout).foregroundStyle(.white.opacity(0.7))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 4)
            } else {
                ScrollView {
                    VStack(spacing: 6) {
                        ForEach(abertas.prefix(6)) { p in linha(p) }
                        if abertas.count > 6 {
                            Button("Mais \(abertas.count - 6) no Noah") { ilha.mostrarJanela() }
                                .buttonStyle(.plain).font(.caption.bold()).foregroundStyle(.white.opacity(0.7))
                        }
                        ForEach(rodando.prefix(2)) { j in linhaJob(j) }
                    }
                    .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { alturaLista = $0 }
                }
                .scrollIndicators(.automatic)
                .frame(height: min(max(alturaLista, 1), IlhaMac.alturaLista))
            }

            HStack(spacing: 14) {
                Button { ilha.mostrarJanela(Atalho.fluxo) } label: {
                    Label("Fluxo", systemImage: "point.3.connected.trianglepath.dotted")
                }
                Button { ilha.mostrarJanela() } label: { Label("Pendências", systemImage: "tray.full") }
                Spacer()
                if let quando = modelo.atualizadoEm {
                    // Texto próprio: `style: .relative` sai em inglês (o app não tem localização).
                    TimelineView(.periodic(from: .now, by: 1)) { ctx in
                        let s = max(0, Int(ctx.date.timeIntervalSince(quando)))
                        Text(s < 2 ? "agora" : "há \(s) s").monospacedDigit()
                    }
                    .foregroundStyle(.white.opacity(0.4))
                }
            }
            .buttonStyle(.plain)
            .font(.caption)
            .foregroundStyle(.white.opacity(0.75))
        }
        .padding(.horizontal, 18)
        .padding(.bottom, 14)
        .frame(width: IlhaMac.larguraAberta)
    }

    private func subtitulo(_ r: ResumoIlha) -> String {
        var partes: [String] = []
        if r.esperando > 0 { partes.append(r.esperando == 1 ? "1 para você" : "\(r.esperando) para você") }
        if r.rodando > 0 { partes.append(r.rodando == 1 ? "1 respondendo" : "\(r.rodando) respondendo") }
        if r.prontas > 0 { partes.append(r.prontas == 1 ? "1 pronta" : "\(r.prontas) prontas") }
        return partes.isEmpty ? r.linha : partes.joined(separator: " · ")
    }

    private func linha(_ p: Pendencia) -> some View {
        let ocupado = modelo.enviando.contains(p.chave)
        let aberto = expandidas.contains(p.chave)
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 5) {
                        Text(Fonte.nome(p.fonte) + (p.automatica ? " · gerada pelo Noah" : ""))
                            .foregroundStyle(EstadoIlha.esperando.corClara)
                        if !p.automatica { selo(p) }
                    }
                    .font(.caption2.bold())
                    Text(p.tarefa).font(.callout).foregroundStyle(.white).lineLimit(aberto ? 4 : 2)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                Image(systemName: "chevron.down")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(.white.opacity(0.5))
                    .rotationEffect(.degrees(aberto ? 180 : 0))
                if let app = Fonte.app(p.fonte) {
                    botaoRedondo("arrow.up.forward.app", ajuda: "Abrir no \(Fonte.nome(p.fonte))") { abrirApp(app) }
                }
                if !p.automatica && p.simples && p.podeResponder {
                    Button { Task { await modelo.aceitar(p) } } label: {
                        Text(ocupado ? "…" : "Aceitar").font(.caption.bold())
                            .padding(.horizontal, 10).padding(.vertical, 5)
                            .background(Capsule().fill(EstadoIlha.pronto.cor))
                            .foregroundStyle(.white)
                    }
                    .buttonStyle(.plain).disabled(ocupado)
                    .help("Responde “\(Ajustes.respostaAceitar)”; pede \(Cadeado.nome) antes de enviar")
                }
            }
            .contentShape(Rectangle())
            .onTapGesture { alternar(p) }
            .help(aberto ? "Esconder o detalhe" : "Ver o detalhe e responder")

            if aberto { detalhe(p, ocupado: ocupado) }
        }
        .padding(.horizontal, 10).padding(.vertical, 7)
        .background(.white.opacity(aberto ? 0.11 : 0.08), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    /// "Pergunta" quando o agente pede algo; "Resposta pronta" quando só terminou.
    private func selo(_ p: Pendencia) -> some View {
        let cor = p.pergunta ? EstadoIlha.esperando.corClara : EstadoIlha.pronto.corClara
        return Text(p.pergunta ? "Pergunta" : "Resposta pronta")
            .padding(.horizontal, 5).padding(.vertical, 1)
            .background(cor.opacity(0.16), in: Capsule())
            .foregroundStyle(cor)
    }

    private func alternar(_ p: Pendencia) {
        withAnimation(semMovimento ? nil : .spring(response: 0.3, dampingFraction: 0.85)) {
            if expandidas.remove(p.chave) == nil {
                expandidas.insert(p.chave)
            } else if foco == p.chave {
                foco = nil
            }
        }
    }

    /// O detalhe por baixo do item: o que fazer, a última mensagem e o campo de resposta.
    @ViewBuilder
    private func detalhe(_ p: Pendencia, ocupado: Bool) -> some View {
        let rascunho = Binding(get: { modelo.rascunhos[p.chave] ?? "" },
                               set: { modelo.rascunhos[p.chave] = $0 })
        let vazio = rascunho.wrappedValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        let enviar = {
            let texto = rascunho.wrappedValue
            guard !texto.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
            Task { await modelo.responder(p, texto: texto) }
        }
        VStack(alignment: .leading, spacing: 8) {
            Text(p.origem).font(.caption).foregroundStyle(.white.opacity(0.55))
            if let acao = p.acao {
                Text(acao).font(.callout.weight(.semibold)).foregroundStyle(.white)
                    .textSelection(.enabled)
            }
            if !p.motivo.isEmpty {
                TextoRolavel(texto: p.motivo, alturaMaxima: 150)
            }
            if p.podeResponder {
                HStack(alignment: .bottom, spacing: 6) {
                    TextField("Sua resposta", text: rascunho, axis: .vertical)
                        .textFieldStyle(.plain)
                        .lineLimit(1...5)
                        .focused($foco, equals: p.chave)
                        .onSubmit(enviar)
                        .disabled(ocupado)
                        .padding(.horizontal, 10).padding(.vertical, 7)
                        .background(.white.opacity(0.1), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    Button(action: enviar) {
                        Image(systemName: ocupado ? "ellipsis" : "arrow.up")
                            .font(.system(size: 12, weight: .bold))
                            .frame(width: 28, height: 28)
                            .background(Circle().fill(vazio ? Color.white.opacity(0.12) : EstadoIlha.pronto.cor))
                            .foregroundStyle(.white)
                    }
                    .buttonStyle(.plain)
                    .disabled(ocupado || vazio)
                    .help("Enviar para \(Fonte.nome(p.fonte)); pede \(Cadeado.nome) antes")
                }
            }
            HStack(spacing: 14) {
                Button("Abrir no Noah") { ilha.mostrarJanela(Atalho.pendencia(p.chave)) }
                Button("Dispensar") { Task { await modelo.dispensar(p) } }.disabled(ocupado)
                Spacer()
                if p.podeResponder { Text("Return envia").foregroundStyle(.white.opacity(0.35)) }
            }
            .buttonStyle(.plain)
            .font(.caption)
            .foregroundStyle(.white.opacity(0.7))
        }
        .transition(.opacity)
    }

    private func linhaJob(_ j: Job) -> some View {
        HStack(spacing: 8) {
            ProgressView().controlSize(.small).tint(EstadoIlha.trabalhando.corClara)
            VStack(alignment: .leading, spacing: 1) {
                Text("\(Fonte.nome(j.fonte)) respondendo").font(.caption2.bold())
                    .foregroundStyle(EstadoIlha.trabalhando.corClara)
                Text(j.titulo).font(.callout).foregroundStyle(.white.opacity(0.85)).lineLimit(1)
            }
            Spacer()
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(EstadoIlha.trabalhando.cor.opacity(0.14), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private func botaoRedondo(_ simbolo: String, ajuda: String, _ acao: @escaping () -> Void) -> some View {
        Button(action: acao) {
            Image(systemName: simbolo).font(.system(size: 12, weight: .semibold))
                .frame(width: 26, height: 26)
                .background(Circle().fill(.white.opacity(0.12)))
                .foregroundStyle(.white.opacity(0.85))
        }
        .buttonStyle(.plain)
        .help(ajuda)
    }

    /// Só abre o app do agente; fechar ou apagar outro app não cabe aqui.
    private func abrirApp(_ identificador: String) {
        guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: identificador) else {
            return modelo.mostrar("App não encontrado neste Mac.")
        }
        NSWorkspace.shared.openApplication(at: url, configuration: .init())
    }
}

/// Retângulo com só os cantos de baixo arredondados: o alto encosta na borda da tela.
struct FormaIlha: Shape {
    var raio: CGFloat
    var animatableData: CGFloat {
        get { raio }
        set { raio = newValue }
    }

    func path(in r: CGRect) -> Path {
        let k = min(raio, r.height / 2, r.width / 2)
        return Path(roundedRect: r, cornerRadii: RectangleCornerRadii(bottomLeading: k, bottomTrailing: k),
                    style: .continuous)
    }
}



/// Texto selecionável que cresce até `alturaMaxima` e, passado isso, rola.
private struct TextoRolavel: View {
    var texto: String
    var alturaMaxima: CGFloat
    @State private var altura: CGFloat = 0

    var body: some View {
        ScrollView {
            Text(texto)
                .font(.callout)
                .foregroundStyle(.white.opacity(0.85))
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { altura = $0 }
        }
        .frame(height: min(max(altura, 1), alturaMaxima))
    }
}

/// Três pontinhos de "trabalhando", parados se o sistema pede menos movimento.
private struct Pontos: View {
    var cor: Color
    var parado: Bool

    var body: some View {
        TimelineView(.animation(minimumInterval: 0.15, paused: parado)) { t in
            let fase = Int(t.date.timeIntervalSinceReferenceDate / 0.3) % 3
            HStack(spacing: 2) {
                ForEach(0..<3, id: \.self) { i in
                    Circle().fill(cor.opacity(parado || i == fase ? 1 : 0.35)).frame(width: 3.5, height: 3.5)
                }
            }
        }
    }
}
#endif
