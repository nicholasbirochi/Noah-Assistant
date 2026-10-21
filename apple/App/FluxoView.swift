import NoahCore
import SwiftUI

/// Aba Fluxo: por onde a informação passa. Claude Code, Codex e Noah ligam
/// direto em cada modelo que usam (Qwen local, Nemotron, Copilot), no Cérebro
/// (que abre nas pastas 00 a 07, e cada pasta nas notas e subpastas dela) e na
/// central, que leva tudo aos aparelhos.
/// Partículas só correm nas ligações com rastro real (`Fluxo.grafo`); os
/// caminhos que a central não enxerga ficam tracejados.
struct FluxoView: View {
    @Environment(Modelo.self) private var modelo
    @Environment(\.accessibilityReduceMotion) private var reduzirMovimento
    @State private var cerebroAberto = true
    /// Pastas abertas no mapa (ids do `Fluxo`), em qualquer nível.
    @State private var abertos: Set<String> = []

    var body: some View {
        let grafo = Fluxo.grafo(itens: modelo.itens, jobs: modelo.jobs, painel: modelo.painel,
                                cerebroAberto: cerebroAberto, abertos: abertos, cerebro: modelo.cerebro)
        VStack(spacing: 0) {
            cabecalho
            GeometryReader { geo in
                let largo = geo.size.width >= 600
                let mapa = Mapa(largura: geo.size.width - 24,
                                alturaBase: largo ? max(geo.size.height - 170, 600) : 900,
                                grafo: grafo, largo: largo)
                let tamanho = mapa.tamanho
                ScrollView {
                    VStack(spacing: 0) {
                        ZStack {
                            TimelineView(.animation(minimumInterval: 1 / 30,
                                                    paused: modelo.aba != .fluxo || reduzirMovimento)) { ctx in
                                Canvas { g, _ in
                                    let t = reduzirMovimento ? 0.35 : ctx.date.timeIntervalSinceReferenceDate
                                    for l in grafo.ligacoes { Desenho.ligacao(l, mapa: mapa, tempo: t, em: &g) }
                                }
                            }
                            ForEach(mapa.blocos, id: \.pai) { bloco in
                                Text(grafo.no(bloco.pai)?.nome ?? "")
                                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                                    .foregroundStyle(Paleta.cerebro.opacity(0.8))
                                    .lineLimit(1)
                                    .frame(width: tamanho.width - 16, alignment: .leading)
                                    .position(x: tamanho.width / 2, y: bloco.y)
                                    .transition(.opacity)
                            }
                            ForEach(grafo.nos) { no in
                                NoFluxo(no: no, aceso: grafo.aceso(no.id), largura: mapa.largura(no),
                                        aberto: aberto(no)) { alternar(no) }
                                .position(mapa.ponto(no.id))
                                .transition(.scale(scale: 0.6).combined(with: .opacity))
                            }
                        }
                        .frame(width: tamanho.width, height: tamanho.height)
                        .padding(.horizontal, 12)
                        Agora(grafo: grafo, ollama: modelo.painel?.ollama, erro: modelo.erroPainel)
                        CerebroPartes(sinal: modelo.cerebro)
                    }
                }
                .scrollIndicators(.hidden)
            }
        }
        .background(Paleta.fundo.ignoresSafeArea())
        .environment(\.colorScheme, .dark)
        .task { await modelo.atualizarPainel() }
    }

    /// Cérebro e pastas abrem e fecham; os outros nós não têm o que abrir.
    private func aberto(_ no: Fluxo.No) -> Bool? {
        switch no.tipo {
        case .cerebro: cerebroAberto
        case .pasta: abertos.contains(no.id)
        default: nil
        }
    }

    private func alternar(_ no: Fluxo.No) {
        withAnimation(.spring(duration: 0.35)) {
            if no.tipo == .cerebro {
                cerebroAberto.toggle()
            } else if abertos.contains(no.id) {
                // Fechar uma pasta fecha também o que estava aberto dentro dela.
                abertos = abertos.filter { $0 != no.id && !$0.hasPrefix(no.id + "/") }
            } else {
                abertos.insert(no.id)
            }
        }
    }

    private var cabecalho: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text("FLUXO").font(.system(.title3, design: .monospaced).weight(.bold))
                Text("por onde a informação passa").font(.system(.caption, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
            Spacer()
            TimelineView(.periodic(from: .now, by: 1)) { ctx in
                HStack(spacing: 6) {
                    Circle().fill(modelo.erro == nil ? Paleta.verde : Color.red).frame(width: 7, height: 7)
                    Text(pulso(ctx.date)).font(.system(.caption, design: .monospaced)).foregroundStyle(.secondary)
                }
            }
        }
        .padding(.horizontal, 16).padding(.top, 14).padding(.bottom, 4)
    }

    private func pulso(_ agora: Date) -> String {
        guard let quando = modelo.atualizadoEm else { return modelo.erro == nil ? "conectando…" : "sem conexão" }
        let s = max(0, Int(agora.timeIntervalSince(quando)))
        return modelo.erro == nil ? "central lida há \(s) s" : "sem conexão há \(s) s"
    }
}

// MARK: - Posições

/// Onde cada nó fica. Na tela larga (Mac), em colunas: modelos | agentes |
/// Cérebro e central | pastas e aparelhos. Na estreita (iPhone), em faixas:
/// modelos em cima, agentes, central à esquerda e Cérebro à direita, pastas
/// embaixo. Assim os agentes saem para os modelos de um lado e para o Cérebro
/// e a central do outro, sem passar um pelo outro.
///
/// O que se abre dentro de uma pasta vai em blocos abaixo do mapa, um por
/// pasta aberta, e o mapa cresce para caber (rola na tela).
struct Mapa {
    let tamanho: CGSize
    let largo: Bool
    /// Um bloco por pasta aberta: o id dela e a altura do título do bloco.
    let blocos: [(pai: String, y: CGFloat)]
    private let posicoes: [String: CGPoint]

    static func filho(_ no: Fluxo.No) -> Bool { no.tipo == .nota || (no.tipo == .pasta && no.id.contains("/")) }

    init(largura: CGFloat, alturaBase: CGFloat, grafo: Fluxo.Grafo, largo: Bool) {
        self.largo = largo
        let modelos = grafo.nos.filter { $0.tipo == .modelo }.map(\.id)
        let pastas = grafo.nos.filter { $0.tipo == .pasta && !Self.filho($0) }.map(\.id)
        var p: [String: (Double, Double)] = [:]
        func espalhar(_ i: Int, _ n: Int, _ de: Double, _ ate: Double) -> Double {
            n <= 1 ? (de + ate) / 2 : de + (ate - de) * Double(i) / Double(n - 1)
        }
        if largo {
            for (i, id) in modelos.enumerated() { p[id] = (0.09, espalhar(i, modelos.count, 0.07, 0.93)) }
            p[Fluxo.claude] = (0.34, 0.2)
            p[Fluxo.codex] = (0.34, 0.5)
            p[Fluxo.noah] = (0.34, 0.8)
            p[Fluxo.cerebro] = (0.6, 0.24)
            p[Fluxo.central] = (0.6, 0.68)
            for (i, id) in pastas.enumerated() { p[id] = (0.87, espalhar(i, pastas.count, 0.05, 0.68)) }
            p[Fluxo.aparelhos] = (0.87, 0.88)
        } else {
            let colunas = [0.17, 0.5, 0.83]
            for (i, id) in modelos.enumerated() { p[id] = (colunas[i % 3], 0.04 + Double(i / 3) * 0.08) }
            p[Fluxo.claude] = (0.17, 0.28)
            p[Fluxo.codex] = (0.5, 0.28)
            p[Fluxo.noah] = (0.83, 0.28)
            p[Fluxo.central] = (0.22, 0.45)
            p[Fluxo.aparelhos] = (0.22, 0.58)
            p[Fluxo.cerebro] = (0.72, 0.5)
            for (i, id) in pastas.enumerated() { p[id] = ([0.27, 0.73][i % 2], 0.68 + Double(i / 2) * 0.08) }
        }
        var pontos = p.mapValues { CGPoint(x: $0.0 * largura, y: $0.1 * alturaBase) }

        // Filhos agrupados pela pasta de onde saem, na ordem em que aparecem.
        var ordem: [String] = [], grupos: [String: [String]] = [:]
        for no in grafo.nos where Self.filho(no) {
            guard let pai = grafo.ligacoes.first(where: { $0.para == no.id })?.de else { continue }
            if grupos[pai] == nil { ordem.append(pai) }
            grupos[pai, default: []].append(no.id)
        }
        let colunas = largo ? 4 : 2
        let linha: CGFloat = 58
        var y = alturaBase + 20
        var blocos: [(pai: String, y: CGFloat)] = []
        for pai in ordem {
            let filhos = grupos[pai] ?? []
            blocos.append((pai, y))
            for (i, id) in filhos.enumerated() {
                let x = (CGFloat(i % colunas) + 0.5) / CGFloat(colunas) * largura
                pontos[id] = CGPoint(x: x, y: y + 34 + CGFloat(i / colunas) * linha)
            }
            y += 34 + CGFloat((filhos.count + colunas - 1) / colunas) * linha
        }
        self.blocos = blocos
        posicoes = pontos
        tamanho = CGSize(width: largura, height: ordem.isEmpty ? alturaBase : y)
    }

    func ponto(_ id: String) -> CGPoint {
        posicoes[id] ?? CGPoint(x: tamanho.width / 2, y: tamanho.height / 2)
    }

    /// Largura máxima da caixa: modelos e pastas têm nomes longos e vizinhos perto.
    func largura(_ no: Fluxo.No) -> CGFloat? {
        switch no.tipo {
        case .modelo: largo ? tamanho.width * 0.17 : tamanho.width / 3 - 8
        case _ where Self.filho(no): largo ? tamanho.width * 0.22 : tamanho.width / 2 - 12
        case .pasta: largo ? tamanho.width * 0.24 : tamanho.width / 2 - 12
        default: largo ? nil : tamanho.width / 3 - 4
        }
    }

    /// Curva entre dois nós. As ligações de volta (resposta) se afastam um
    /// pouco da de ida para não ficarem por cima.
    func curva(_ l: Fluxo.Ligacao) -> (CGPoint, CGPoint, CGPoint, CGPoint) {
        let a = ponto(l.de), b = ponto(l.para)
        let dx = b.x - a.x, dy = b.y - a.y
        var c1: CGPoint, c2: CGPoint
        if abs(dx) >= abs(dy) {
            c1 = CGPoint(x: a.x + dx * 0.5, y: a.y)
            c2 = CGPoint(x: b.x - dx * 0.5, y: b.y)
        } else {
            c1 = CGPoint(x: a.x, y: a.y + dy * 0.5)
            c2 = CGPoint(x: b.x, y: b.y - dy * 0.5)
        }
        if Self.volta.contains(l.id) {
            let comp = max(1, hypot(dx, dy))
            let n = CGPoint(x: -dy / comp * 30, y: dx / comp * 30)
            c1 = CGPoint(x: c1.x + n.x, y: c1.y + n.y)
            c2 = CGPoint(x: c2.x + n.x, y: c2.y + n.y)
        }
        return (a, c1, c2, b)
    }

    static let volta: Set<String> = ["central>claude", "central>codex", "central>noah", "aparelhos>central"]

    /// Em que ponto da curva vai o rótulo. Na tela estreita as três consultas ao
    /// Cérebro têm o meio quase na mesma altura, então os rótulos são escalonados.
    func meioDoRotulo(_ l: Fluxo.Ligacao) -> Double {
        guard !largo, l.para == Fluxo.cerebro else { return 0.5 }
        switch l.de {
        case Fluxo.claude: return 0.3
        case Fluxo.noah: return 0.7
        default: return 0.5
        }
    }

    /// Espaço livre entre as caixas dos dois nós, para o rótulo não ficar por baixo delas.
    func espacoDoRotulo(_ l: Fluxo.Ligacao) -> CGFloat {
        let a = ponto(l.de), b = ponto(l.para)
        return hypot(b.x - a.x, b.y - a.y) - 130
    }
}

// MARK: - Desenho

enum Desenho {
    static func ligacao(_ l: Fluxo.Ligacao, mapa: Mapa, tempo: Double, em g: inout GraphicsContext) {
        let (a, c1, c2, b) = mapa.curva(l)
        var caminho = Path()
        caminho.move(to: a)
        caminho.addCurve(to: b, control1: c1, control2: c2)
        let cor = Paleta.cor(id: l.de)

        switch l.estado {
        case .parada:
            g.stroke(caminho, with: .color(.white.opacity(0.08)), lineWidth: 1)
        case .semSinal:
            // Tracejado andando devagar: mostra o sentido sem fingir pacotes de dado.
            let fase = -CGFloat(tempo.truncatingRemainder(dividingBy: 10) * 6)
            g.stroke(caminho, with: .color(cor.opacity(0.6)),
                     style: StrokeStyle(lineWidth: 1.3, lineCap: .round, dash: [3, 7], dashPhase: fase))
            // Rótulo curto ("consulta e registra"); o "sem sinal" fica na legenda
            // para não poluir o mapa.
            let curto = l.rotulo.components(separatedBy: " (").first ?? l.rotulo
            rotulo(curto, cor: cor.opacity(0.8), tamanho: 9, em: ponto(a, c1, c2, b, mapa.meioDoRotulo(l)),
                   cabe: mapa.espacoDoRotulo(l), g: &g)
        case .viva:
            g.stroke(caminho, with: .color(cor.opacity(0.35)), lineWidth: 1.5)
            let n = min(2 + l.quantidade, 6)
            let periodo = 1.8
            g.drawLayer { brilho in
                brilho.addFilter(.blur(radius: 4))
                for i in 0..<n {
                    let t = fracao(tempo / periodo + Double(i) / Double(n))
                    brilho.fill(circulo(ponto(a, c1, c2, b, t), 5), with: .color(cor.opacity(0.9)))
                }
            }
            for i in 0..<n {
                let t = fracao(tempo / periodo + Double(i) / Double(n))
                for k in 0..<8 {
                    let tk = t - Double(k) * 0.012
                    guard tk > 0 else { break }
                    let alfa = 1 - Double(k) / 8
                    g.fill(circulo(ponto(a, c1, c2, b, tk), 2.4 * alfa + 0.4), with: .color(cor.opacity(alfa)))
                }
            }
            if !l.rotulo.isEmpty {
                rotulo(l.rotulo, cor: cor, tamanho: 10, em: ponto(a, c1, c2, b, 0.5), cabe: .infinity, g: &g)
            }
        }
    }

    /// Texto sobre a linha com fundo escuro, para não brigar com as partículas.
    /// Se não couber no espaço entre os nós, fica só a primeira palavra.
    static func rotulo(_ texto: String, cor: Color, tamanho: CGFloat, em p: CGPoint, cabe: CGFloat,
                       g: inout GraphicsContext) {
        func resolver(_ x: String) -> GraphicsContext.ResolvedText {
            g.resolve(Text(x).font(.system(size: tamanho, design: .monospaced)).foregroundColor(cor))
        }
        var t = resolver(texto)
        var s = t.measure(in: CGSize(width: 400, height: 40))
        if s.width > cabe, let primeira = texto.split(separator: " ").first {
            t = resolver(String(primeira))
            s = t.measure(in: CGSize(width: 400, height: 40))
        }
        let caixa = CGRect(x: p.x - s.width / 2 - 4, y: p.y - s.height / 2 - 2, width: s.width + 8, height: s.height + 4)
        g.fill(Path(roundedRect: caixa, cornerRadius: 4), with: .color(Paleta.fundo.opacity(0.85)))
        g.draw(t, at: p)
    }

    static func ponto(_ a: CGPoint, _ c1: CGPoint, _ c2: CGPoint, _ b: CGPoint, _ t: Double) -> CGPoint {
        let u = 1 - t
        let x = u * u * u * a.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * b.x
        let y = u * u * u * a.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * b.y
        return CGPoint(x: x, y: y)
    }

    static func fracao(_ v: Double) -> Double { v - v.rounded(.down) }

    static func circulo(_ c: CGPoint, _ r: CGFloat) -> Path {
        Path(ellipseIn: CGRect(x: c.x - r, y: c.y - r, width: r * 2, height: r * 2))
    }
}

enum Paleta {
    static let fundo = Color(red: 0.035, green: 0.04, blue: 0.055)
    static let verde = Color(red: 0.3, green: 0.85, blue: 0.5)
    static let claude = Color(red: 0.98, green: 0.6, blue: 0.3)
    static let noah = Color(red: 0.7, green: 0.52, blue: 1)
    static let modelo = Color(red: 0.3, green: 0.8, blue: 0.85)
    static let cerebro = Color(red: 1, green: 0.45, blue: 0.7)
    static let central = Color(red: 0.4, green: 0.62, blue: 1)
    static let aparelhos = Color(red: 0.85, green: 0.88, blue: 0.95)

    /// Cor de um nó do Fluxo ou de um `de`/`para` do feed da central
    /// ("agente", "cerebro", id de modelo, "modelo:<id>", "pasta-NN", "nota:…").
    static func cor(id: String) -> Color {
        switch id {
        case Fluxo.claude, "agente": claude
        case Fluxo.codex: verde
        case Fluxo.noah: noah
        case Fluxo.cerebro: cerebro
        case Fluxo.central: central
        case Fluxo.aparelhos, "app": aparelhos
        default:
            id.hasPrefix("pasta-") ? cerebro.opacity(0.85)
                : id.hasPrefix("nota:") || id.hasPrefix("mais:") ? cerebro.opacity(0.6) : modelo
        }
    }
}

// MARK: - Peças

struct NoFluxo: View {
    let no: Fluxo.No
    let aceso: Bool
    var largura: CGFloat?
    /// No Cérebro e nas pastas: aberto ou fechado. Nulo nos outros nós.
    var aberto: Bool?
    var alternar: () -> Void = {}

    var body: some View {
        let cor = Paleta.cor(id: no.id)
        let caixa = VStack(spacing: 2) {
            HStack(spacing: 4) {
                Text(no.nome).font(.system(size: 12, weight: .semibold, design: .monospaced))
                if let aberto {
                    Image(systemName: aberto ? "chevron.down" : "chevron.right")
                        .font(.system(size: 9, weight: .bold)).foregroundStyle(cor)
                }
            }
            Text(no.detalhe).font(.system(size: 9, design: .monospaced)).foregroundStyle(.secondary)
        }
        .lineLimit(1)
        .truncationMode(.tail)
        .padding(.horizontal, 10).padding(.vertical, 7)
        .frame(maxWidth: largura)
        .fixedSize(horizontal: largura == nil, vertical: true)
        .background(Color(white: 0.07), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(cor.opacity(aceso ? 0.9 : 0.35), lineWidth: aceso ? 1.5 : 1))
        .shadow(color: aceso ? cor.opacity(0.6) : .clear, radius: 8)

        if aberto != nil {
            Button(action: alternar) { caixa }
                .buttonStyle(.plain)
                .accessibilityLabel("\(no.nome), \(aberto == true ? "fechar" : "abrir")")
        } else {
            caixa.accessibilityElement(children: .combine)
        }
    }
}

/// Embaixo do mapa: o que está passando agora, em texto, e a legenda.
struct Agora: View {
    let grafo: Fluxo.Grafo
    var ollama: Bool?
    var erro: String?

    var body: some View {
        // As ligações do Codex aos modelos e ao Cérebro acendem junto com as do
        // Claude e não levam rótulo: aqui viram uma linha só.
        let vivas = grafo.ligacoes.filter { $0.estado == .viva && !$0.rotulo.isEmpty }
        VStack(alignment: .leading, spacing: 6) {
            Text("AGORA").font(.system(size: 10, weight: .bold, design: .monospaced)).foregroundStyle(.secondary)
            if vivas.isEmpty {
                Text("Nada passando agora.").font(.system(.caption, design: .monospaced))
            }
            ForEach(vivas) { l in
                Text("\(nome(l)) → \(grafo.no(l.para)?.nome ?? l.para) · \(l.rotulo)")
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(Paleta.cor(id: l.de))
            }
            if ollama == false {
                Text("Ollama fora do ar: os Qwen locais não respondem.")
                    .font(.system(.caption, design: .monospaced)).foregroundStyle(.orange)
            }
            if let erro {
                Text("Atividade dos modelos indisponível: \(erro)")
                    .font(.system(.caption, design: .monospaced)).foregroundStyle(.red)
            }
            Divider().padding(.vertical, 2)
            Legenda(tracejada: false, texto: "ao vivo: dado lido da central")
            Legenda(tracejada: true, texto: "\(Fluxo.semSinal): consultas ao Cérebro não deixam rastro")
            Text("O registro dos modelos não diz se foi o Claude ou o Codex que delegou: as duas ligações acendem. Toque no Cérebro e nas pastas para abrir ou fechar o que tem dentro.")
                .font(.system(size: 10, design: .monospaced)).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color(white: 0.06), in: RoundedRectangle(cornerRadius: 10))
        .padding(.horizontal, 16).padding(.bottom, 12)
    }

    private func nome(_ l: Fluxo.Ligacao) -> String {
        let delegado = l.para.hasPrefix("modelo:") || (l.para == Fluxo.cerebro && l.rotulo == "registrou nota")
        if l.de == Fluxo.claude && delegado { return "Claude/Codex" }
        return grafo.no(l.de)?.nome ?? l.de
    }
}

struct Legenda: View {
    let tracejada: Bool
    let texto: String

    var body: some View {
        HStack(spacing: 8) {
            Path { p in p.move(to: CGPoint(x: 0, y: 4)); p.addLine(to: CGPoint(x: 26, y: 4)) }
                .stroke(Color.white.opacity(0.6), style: StrokeStyle(lineWidth: 1.4, dash: tracejada ? [3, 4] : []))
                .frame(width: 26, height: 8)
            Text(texto).font(.system(size: 10, design: .monospaced)).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}


/// Mostra as pastas numeradas que cada agente consultou ou atualizou na janela.
/// Se a central ainda não envia esse dado, os oito indicadores ficam apagados.
private struct CerebroPartes: View {
    let sinal: SinalCerebro?

    var body: some View {
        let visitas = Fluxo.visitas(sinal)
        VStack(alignment: .leading, spacing: 8) {
            Text("PARTES DO CÉREBRO").font(.system(size: 10, weight: .bold, design: .monospaced)).foregroundStyle(.secondary)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 92), spacing: 6)], spacing: 6) {
                ForEach(Fluxo.Parte.allCases, id: \.self) { parte in
                    let atores = visitas[parte] ?? []
                    HStack(spacing: 4) {
                        Text(parte.rawValue).fontWeight(.bold)
                        Text(parte.nome).lineLimit(1)
                        Spacer(minLength: 0)
                        ForEach(atores, id: \.self) { ator in
                            MascoteMini(ator: ator).frame(width: 16, height: 18)
                        }
                    }
                    .font(.system(size: 9, design: .monospaced))
                    .padding(6)
                    .background(atores.isEmpty ? Color(white: 0.08) : Paleta.cor(id: atores[0].rawValue).opacity(0.18),
                                in: RoundedRectangle(cornerRadius: 6))
                    .overlay(RoundedRectangle(cornerRadius: 6).stroke(.white.opacity(atores.isEmpty ? 0.08 : 0.3)))
                    .accessibilityLabel("\(parte.nome): \(atores.map(\.nome).joined(separator: ", "))")
                }
            }
            Text(sinal == nil ? "Esta central não envia sinal por pasta." : "Pontos mostram quem passou por cada pasta nos últimos \(max(1, (sinal?.janela ?? 600) / 60)) min.")
                .font(.system(size: 9, design: .monospaced)).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color(white: 0.06), in: RoundedRectangle(cornerRadius: 10))
        .padding(.horizontal, 16).padding(.bottom, 12)
    }
}


private struct MascoteMini: View {
    let ator: Fluxo.Ator

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 20)) { contexto in
            Canvas { g, size in
                Boneco.desenhar(ator, em: g, pe: CGPoint(x: size.width / 2, y: size.height),
                                altura: size.height, tempo: contexto.date.timeIntervalSinceReferenceDate,
                                andando: false, esquerda: false)
            }
        }
        .accessibilityLabel(ator.nome)
    }
}
