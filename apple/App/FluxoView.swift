import NoahCore
import SwiftUI

/// Aba Fluxo: por onde a informação passa entre os agentes, o Cérebro, a
/// central e os aparelhos. Partículas só correm nas ligações com dado real da
/// central (`Fluxo.ligacoes`), inclusive as consultas ao Cérebro e as tarefas
/// delegadas aos auxiliares (sinal de `GET /central/api/cerebro`). Sem esse
/// sinal (central antiga) esses caminhos ficam tracejados.
struct FluxoView: View {
    @Environment(Modelo.self) private var modelo
    @Environment(\.accessibilityReduceMotion) private var reduzirMovimento

    var body: some View {
        let ligacoes = Fluxo.ligacoes(itens: modelo.itens, jobs: modelo.jobs, cerebro: modelo.cerebro)
        VStack(spacing: 0) {
            cabecalho
            GeometryReader { geo in
                let mapa = Mapa(tamanho: geo.size)
                ZStack {
                    TimelineView(.animation(minimumInterval: 1 / 30,
                                            paused: modelo.aba != .fluxo || reduzirMovimento)) { ctx in
                        Canvas { g, _ in
                            let t = reduzirMovimento ? 0.35 : ctx.date.timeIntervalSinceReferenceDate
                            for l in ligacoes { Desenho.ligacao(l, mapa: mapa, tempo: t, em: &g) }
                        }
                    }
                    ForEach(Fluxo.No.allCases, id: \.self) { no in
                        NoFluxo(no: no, aceso: ligacoes.contains { $0.estado == .viva && ($0.de == no || $0.para == no) })
                            .position(mapa.ponto(no))
                    }
                }
            }
            .padding(.horizontal, 12)
            Agora(ligacoes: ligacoes, janela: modelo.cerebro?.janela)
        }
        .background(Paleta.fundo.ignoresSafeArea())
        .environment(\.colorScheme, .dark)
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

/// Onde cada nó fica: em colunas na tela larga (Mac), em linhas na estreita
/// (iPhone). Os agentes ficam entre o Cérebro e a central, para os caminhos de
/// consulta e os de pendência saírem por lados opostos sem se cruzar.
struct Mapa {
    let tamanho: CGSize
    var largo: Bool { tamanho.width >= tamanho.height * 0.9 }

    func ponto(_ no: Fluxo.No) -> CGPoint {
        let (x, y): (Double, Double) = largo ? Self.largo(no) : Self.estreito(no)
        return CGPoint(x: x * tamanho.width, y: y * tamanho.height)
    }

    private static func largo(_ no: Fluxo.No) -> (Double, Double) {
        switch no {
        case .cerebro: (0.1, 0.33)
        case .auxiliares: (0.1, 0.72)
        case .claude: (0.38, 0.18)
        case .codex: (0.38, 0.47)
        case .noah: (0.38, 0.76)
        case .central: (0.6, 0.47)
        case .aparelhos: (0.9, 0.47)
        }
    }

    private static func estreito(_ no: Fluxo.No) -> (Double, Double) {
        switch no {
        case .cerebro: (0.3, 0.08)
        case .auxiliares: (0.76, 0.08)
        case .claude: (0.17, 0.4)
        case .codex: (0.5, 0.4)
        case .noah: (0.83, 0.4)
        case .central: (0.5, 0.7)
        case .aparelhos: (0.5, 0.92)
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

    static let volta: Set<String> = ["central>claude", "central>codex", "aparelhos>central"]

    /// Em que ponto da curva vai o rótulo. Na tela estreita as três consultas ao
    /// Cérebro têm o meio na mesma altura, então os rótulos são escalonados.
    func meioDoRotulo(_ l: Fluxo.Ligacao) -> Double {
        guard !largo, l.para == .cerebro else { return 0.5 }
        switch l.de {
        case .claude: return 0.3
        case .noah: return 0.7
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
        let cor = Paleta.cor(l.de)

        switch l.estado {
        case .parada:
            g.stroke(caminho, with: .color(.white.opacity(0.08)), lineWidth: 1)
        case .semSinal:
            // Tracejado andando devagar: mostra o sentido sem fingir pacotes de dado.
            let fase = -CGFloat(tempo.truncatingRemainder(dividingBy: 10) * 6)
            g.stroke(caminho, with: .color(cor.opacity(0.6)),
                     style: StrokeStyle(lineWidth: 1.3, lineCap: .round, dash: [3, 7], dashPhase: fase))
            // Rótulo curto ("consulta", "delega tarefa pequena"); o "sem sinal"
            // fica na legenda para não poluir o mapa.
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
            rotulo(l.rotulo, cor: cor, tamanho: 10, em: ponto(a, c1, c2, b, 0.5), cabe: .infinity, g: &g)
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

    static func cor(_ no: Fluxo.No) -> Color {
        switch no {
        case .claude: Color(red: 0.98, green: 0.6, blue: 0.3)
        case .codex: verde
        case .noah: Color(red: 0.7, green: 0.52, blue: 1)
        case .auxiliares: Color(red: 0.3, green: 0.8, blue: 0.85)
        case .cerebro: Color(red: 1, green: 0.45, blue: 0.7)
        case .central: Color(red: 0.4, green: 0.62, blue: 1)
        case .aparelhos: Color(red: 0.85, green: 0.88, blue: 0.95)
        }
    }
}

// MARK: - Peças

struct NoFluxo: View {
    let no: Fluxo.No
    let aceso: Bool

    var body: some View {
        let cor = Paleta.cor(no)
        VStack(spacing: 2) {
            Text(no.nome).font(.system(size: 12, weight: .semibold, design: .monospaced))
            Text(no.detalhe).font(.system(size: 9, design: .monospaced)).foregroundStyle(.secondary)
        }
        .lineLimit(1)
        .padding(.horizontal, 10).padding(.vertical, 7)
        .background(Color(white: 0.07), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(cor.opacity(aceso ? 0.9 : 0.35), lineWidth: aceso ? 1.5 : 1))
        .shadow(color: aceso ? cor.opacity(0.6) : .clear, radius: 8)
        .accessibilityElement(children: .combine)
    }
}

/// Embaixo do mapa: o que está passando agora, em texto, e a legenda.
struct Agora: View {
    let ligacoes: [Fluxo.Ligacao]
    /// Janela do sinal do Cérebro em segundos; nil sem o sinal.
    let janela: Int?

    var body: some View {
        let vivas = ligacoes.filter { $0.estado == .viva }
        let semSinal = ligacoes.contains { $0.estado == .semSinal }
        VStack(alignment: .leading, spacing: 6) {
            Text("AGORA").font(.system(size: 10, weight: .bold, design: .monospaced)).foregroundStyle(.secondary)
            if vivas.isEmpty {
                Text("Nada passando agora.").font(.system(.caption, design: .monospaced))
            }
            ForEach(vivas) { l in
                Text("\(l.de.nome) → \(l.para.nome) · \(l.rotulo)")
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(Paleta.cor(l.de))
            }
            Divider().padding(.vertical, 2)
            Legenda(tracejada: false, texto: janela.map {
                "ao vivo: dado lido da central (Cérebro e auxiliares: últimos \(max(1, $0 / 60)) min)"
            } ?? "ao vivo: dado lido da central")
            if semSinal {
                Legenda(tracejada: true, texto: janela == nil
                    ? "sem sinal ao vivo: esta central ainda não conta as consultas ao Cérebro; atualize o Noah no Mac"
                    : "sem sinal ao vivo: a central não conseguiu ler essa fonte agora")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color(white: 0.06), in: RoundedRectangle(cornerRadius: 10))
        .padding(.horizontal, 16).padding(.bottom, 12)
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
