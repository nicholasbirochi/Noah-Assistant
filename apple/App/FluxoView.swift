import NoahCore
import SwiftUI

/// Aba Fluxo: por onde a informação passa entre os agentes, o Cérebro, a
/// central e os aparelhos. Partículas só correm nas ligações com dado real da
/// central (`Fluxo.ligacoes`), inclusive as consultas ao Cérebro e as tarefas
/// delegadas aos auxiliares (sinal de `GET /central/api/cerebro`). Sem esse
/// sinal (central antiga) esses caminhos ficam tracejados. O Cérebro aparece em
/// pedaços (as pastas 00–07 do cofre): acende a parte que cada agente tocou, e
/// o bonequinho do agente vai até ela; sem sinal por parte, ninguém sai de casa.
struct FluxoView: View {
    @Environment(Modelo.self) private var modelo
    @Environment(\.accessibilityReduceMotion) private var reduzirMovimento

    var body: some View {
        let ligacoes = Fluxo.ligacoes(itens: modelo.itens, jobs: modelo.jobs, cerebro: modelo.cerebro)
        let parado = modelo.aba != .fluxo || reduzirMovimento
        VStack(spacing: 0) {
            cabecalho
            GeometryReader { geo in
                let mapa = Mapa(tamanho: geo.size)
                ZStack {
                    TimelineView(.animation(minimumInterval: 1 / 30, paused: parado)) { ctx in
                        Canvas { g, _ in
                            let t = reduzirMovimento ? 0.35 : ctx.date.timeIntervalSinceReferenceDate
                            for l in ligacoes { Desenho.ligacao(l, mapa: mapa, tempo: t, em: &g) }
                        }
                    }
                    CerebroEmPedacos(mapa: mapa, visitas: Fluxo.visitas(modelo.cerebro),
                                     comSinal: Fluxo.consultam.contains { Fluxo.partes($0, modelo.cerebro) != nil },
                                     aceso: ligacoes.contains { $0.estado == .viva && ($0.de == .cerebro || $0.para == .cerebro) })
                    ForEach(Fluxo.No.allCases.filter { $0 != .cerebro }, id: \.self) { no in
                        NoFluxo(no: no, aceso: ligacoes.contains { $0.estado == .viva && ($0.de == no || $0.para == no) })
                            .position(mapa.ponto(no))
                    }
                    TimelineView(.animation(minimumInterval: 1 / 30, paused: parado)) { ctx in
                        Canvas { g, _ in
                            let t = reduzirMovimento ? 0 : ctx.date.timeIntervalSinceReferenceDate
                            Passeio.desenhar(mapa: mapa, sinal: modelo.cerebro, tempo: t, parado: reduzirMovimento, em: g)
                        }
                    }
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
                }
            }
            .padding(.horizontal, 12)
            Agora(ligacoes: ligacoes, sinal: modelo.cerebro)
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
        let p = CGPoint(x: x * tamanho.width, y: y * tamanho.height)
        guard no == .cerebro else { return p }
        // O Cérebro em pedaços é mais largo que um nó: não deixa sair da tela.
        let meio = blocoDoCerebro.size
        return CGPoint(x: max(p.x, meio.width / 2 + 2), y: max(p.y, meio.height / 2 + 2))
    }

    // MARK: Cérebro em pedaços

    /// 2 colunas × 4 linhas na tela larga, 4 × 2 na estreita.
    var colunas: Int { largo ? 2 : 4 }
    var tamanhoDoPedaco: CGSize { largo ? CGSize(width: 76, height: 24) : CGSize(width: 46, height: 26) }
    static let folga: CGFloat = 4, margem: CGFloat = 6, titulo: CGFloat = 16

    var blocoDoCerebro: CGRect {
        let linhas = (Fluxo.Parte.allCases.count + colunas - 1) / colunas
        let p = tamanhoDoPedaco
        let largura = CGFloat(colunas) * p.width + CGFloat(colunas - 1) * Self.folga + Self.margem * 2
        let altura = Self.titulo + CGFloat(linhas) * p.height + CGFloat(linhas - 1) * Self.folga + Self.margem * 2
        let (x, y): (Double, Double) = largo ? Self.largo(.cerebro) : Self.estreito(.cerebro)
        let c = CGPoint(x: max(x * tamanho.width, largura / 2 + 2), y: max(y * tamanho.height, altura / 2 + 2))
        return CGRect(x: c.x - largura / 2, y: c.y - altura / 2, width: largura, height: altura)
    }

    func pedaco(_ parte: Fluxo.Parte) -> CGRect {
        let i = Fluxo.Parte.allCases.firstIndex(of: parte) ?? 0
        let p = tamanhoDoPedaco, b = blocoDoCerebro
        return CGRect(x: b.minX + Self.margem + CGFloat(i % colunas) * (p.width + Self.folga),
                      y: b.minY + Self.margem + Self.titulo + CGFloat(i / colunas) * (p.height + Self.folga),
                      width: p.width, height: p.height)
    }

    private static func largo(_ no: Fluxo.No) -> (Double, Double) {
        switch no {
        case .cerebro: (0.1, 0.33)
        case .auxiliares: (0.1, 0.72)
        case .claude: (0.42, 0.18)
        case .codex: (0.42, 0.47)
        case .noah: (0.42, 0.76)
        case .central: (0.66, 0.47)
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

    /// Área ocupada por um nó (por cima das linhas), com folga: o Cérebro em
    /// pedaços inteiro ou a caixa de um nó comum.
    func caixa(_ no: Fluxo.No) -> CGRect {
        if no == .cerebro { return blocoDoCerebro.insetBy(dx: -3, dy: -3) }
        let p = ponto(no)
        return CGRect(x: p.x - 54, y: p.y - 24, width: 108, height: 48)
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
            if Self.tocaCerebro(l) {
                rotuloLivre(curto, cor: cor.opacity(0.8), tamanho: 9, l, mapa: mapa, curva: (a, c1, c2, b), g: &g)
            } else {
                rotulo(curto, cor: cor.opacity(0.8), tamanho: 9, em: ponto(a, c1, c2, b, mapa.meioDoRotulo(l)),
                       cabe: mapa.espacoDoRotulo(l), g: &g)
            }
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
            if Self.tocaCerebro(l) {
                rotuloLivre(l.rotulo, cor: cor, tamanho: 10, l, mapa: mapa, curva: (a, c1, c2, b), g: &g)
            } else {
                rotulo(l.rotulo, cor: cor, tamanho: 10, em: ponto(a, c1, c2, b, 0.5), cabe: .infinity, g: &g)
            }
        }
    }

    static func tocaCerebro(_ l: Fluxo.Ligacao) -> Bool { l.de == .cerebro || l.para == .cerebro }

    /// Rótulo das ligações com o Cérebro, que em pedaços ocupa bem mais que um
    /// nó: procura, a partir do meio, um ponto da curva onde a caixa não fique
    /// por baixo do bloco nem do outro nó. Se o texto inteiro não couber em
    /// lugar nenhum, tenta a primeira parte ("3 consultas") e depois a primeira palavra.
    static func rotuloLivre(_ texto: String, cor: Color, tamanho: CGFloat, _ l: Fluxo.Ligacao, mapa: Mapa,
                            curva: (CGPoint, CGPoint, CGPoint, CGPoint), g: inout GraphicsContext) {
        let (a, c1, c2, b) = curva
        let obstaculos = [mapa.caixa(l.de), mapa.caixa(l.para)]
        let inicio = mapa.meioDoRotulo(l)
        // inicio, inicio + 0.05, inicio - 0.05, inicio + 0.1…
        var passos: [Double] = []
        for k in 0...16 {
            let sinal: Double = k % 2 == 0 ? 1 : -1
            let passo: Double = inicio + sinal * Double((k + 1) / 2) * 0.05
            if passo >= 0.05, passo <= 0.95 { passos.append(passo) }
        }
        var candidatos = [texto]
        if let parte = texto.components(separatedBy: " · ").first, parte != texto { candidatos.append(parte) }
        if let palavra = texto.split(separator: " ").first.map(String.init), !candidatos.contains(palavra) {
            candidatos.append(palavra)
        }
        for candidato in candidatos {
            let t = g.resolve(Text(candidato).font(.system(size: tamanho, design: .monospaced)).foregroundColor(cor))
            let s = t.measure(in: CGSize(width: 400, height: 40))
            for passo in passos {
                let p = ponto(a, c1, c2, b, passo)
                let x: CGFloat = p.x - s.width / 2 - 4, y: CGFloat = p.y - s.height / 2 - 2
                let caixa = CGRect(x: x, y: y, width: s.width + 8, height: s.height + 4)
                if !obstaculos.contains(where: { $0.intersects(caixa) }) {
                    g.fill(Path(roundedRect: caixa, cornerRadius: 4), with: .color(Paleta.fundo.opacity(0.85)))
                    g.draw(t, at: p)
                    return
                }
            }
        }
        // Nenhum lugar livre (tela muito apertada): fica só a cor da linha.
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

/// O Cérebro em pedaços: uma peça por pasta do cofre. Acende a parte que algum
/// agente tocou na janela, com um ponto da cor de cada um. Sem `partes` no
/// sinal (central antiga ou fonte em falha), avisa e não acende nada.
struct CerebroEmPedacos: View {
    let mapa: Mapa
    let visitas: [Fluxo.Parte: [Fluxo.No]]
    let comSinal: Bool
    let aceso: Bool

    var body: some View {
        let cor = Paleta.cor(.cerebro)
        let bloco = mapa.blocoDoCerebro
        ZStack {
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(white: 0.07))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(cor.opacity(aceso ? 0.9 : 0.35), lineWidth: aceso ? 1.5 : 1))
                .shadow(color: aceso ? cor.opacity(0.5) : .clear, radius: 8)
                .frame(width: bloco.width, height: bloco.height)
                .position(x: bloco.midX, y: bloco.midY)
            HStack(spacing: 6) {
                Text("Cérebro").font(.system(size: 11, weight: .semibold, design: .monospaced))
                Text(comSinal ? "segundo cérebro" : "sem sinal por parte")
                    .font(.system(size: 8, design: .monospaced)).foregroundStyle(.secondary)
            }
            .lineLimit(1)
            .position(x: bloco.midX, y: bloco.minY + Mapa.margem + Mapa.titulo / 2 - 1)
            ForEach(Fluxo.Parte.allCases, id: \.self) { parte in
                let r = mapa.pedaco(parte)
                Pedaco(parte: parte, quem: visitas[parte] ?? [], largo: mapa.largo)
                    .frame(width: r.width, height: r.height)
                    .position(x: r.midX, y: r.midY)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(rotuloAcessivel)
    }

    private var rotuloAcessivel: String {
        guard comSinal else { return "Cérebro, sem sinal por parte" }
        let tocadas = Fluxo.Parte.allCases.compactMap { p in
            visitas[p].map { "\(p.nome) por \($0.map(\.nome).joined(separator: " e "))" }
        }
        return tocadas.isEmpty ? "Cérebro, nenhuma parte consultada agora" : "Cérebro: " + tocadas.joined(separator: "; ")
    }
}

struct Pedaco: View {
    let parte: Fluxo.Parte
    let quem: [Fluxo.No]
    let largo: Bool

    var body: some View {
        let aceso = !quem.isEmpty
        let cor = Paleta.cor(quem.first ?? .cerebro)
        Group {
            if largo {
                HStack(spacing: 3) {
                    Text(parte.rawValue).fontWeight(.bold)
                    Text(parte.nome)
                    Spacer(minLength: 0)
                }
                .font(.system(size: 9, design: .monospaced))
                .padding(.leading, 5)
            } else {
                VStack(spacing: 0) {
                    Text(parte.rawValue).font(.system(size: 8, weight: .bold, design: .monospaced))
                    Text(parte.nome).font(.system(size: 7, design: .monospaced))
                }
            }
        }
        .lineLimit(1)
        .minimumScaleFactor(0.8)
        .foregroundStyle(aceso ? Color.white : Color.white.opacity(0.4))
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(aceso ? cor.opacity(0.22) : Color(white: 0.1), in: RoundedRectangle(cornerRadius: 5))
        .overlay(RoundedRectangle(cornerRadius: 5).stroke(aceso ? cor.opacity(0.85) : .white.opacity(0.08), lineWidth: 1))
        .overlay(alignment: .topTrailing) {
            HStack(spacing: 2) {
                ForEach(quem, id: \.self) { Circle().fill(Paleta.cor($0)).frame(width: 4, height: 4) }
            }
            .padding(3)
        }
    }
}

/// Os bonequinhos: cada agente que consulta o Cérebro fica ao lado do seu nó
/// e, quando o sinal diz que ele tocou partes do Cérebro, vai a cada uma, para
/// um instante e volta. Sem partes (ou sem sinal por parte), fica em casa.
enum Passeio {
    /// Pontos por segundo andando; segundos parado numa parte e em casa.
    static let passo: Double = 110, naParte = 1.3, emCasa = 2.4

    struct Pose { var pe: CGPoint; var andando: Bool; var esquerda: Bool }

    static func altura(_ mapa: Mapa) -> CGFloat { mapa.largo ? 38 : 28 }

    /// Onde o bonequinho fica parado: à esquerda do nó (larga) ou em cima (estreita),
    /// do lado de onde sai o caminho para o Cérebro.
    static func casa(_ no: Fluxo.No, _ mapa: Mapa) -> CGPoint {
        let p = mapa.ponto(no)
        return mapa.largo ? CGPoint(x: p.x - 74, y: p.y + 18) : CGPoint(x: p.x, y: p.y - 20)
    }

    /// Pés no pé da peça, um pouco deslocados por agente para não se sobreporem.
    static func paradas(_ no: Fluxo.No, _ partes: [Fluxo.Parte: Int], _ mapa: Mapa) -> [CGPoint] {
        let i = CGFloat((Fluxo.consultam.firstIndex(of: no) ?? 1) - 1)
        return partes.keys.sorted().map { parte in
            let r = mapa.pedaco(parte)
            return CGPoint(x: r.midX + i * r.width * 0.28, y: r.maxY - 1)
        }
    }

    static func pose(casa: CGPoint, paradas: [CGPoint], tempo: Double) -> Pose {
        guard !paradas.isEmpty else { return Pose(pe: casa, andando: false, esquerda: false) }
        let pontos = [casa] + paradas + [casa]
        let trechos = (0..<(pontos.count - 1)).map { i -> (CGPoint, CGPoint, Double, Double) in
            let a = pontos[i], b = pontos[i + 1]
            return (a, b, max(0.6, hypot(b.x - a.x, b.y - a.y) / passo), i == pontos.count - 2 ? emCasa : naParte)
        }
        let ciclo = trechos.reduce(0) { $0 + $1.2 + $1.3 }
        var t = Desenho.fracao(tempo / ciclo) * ciclo
        for (a, b, anda, espera) in trechos {
            if t < anda {
                let f = t / anda, s = f * f * (3 - 2 * f)
                let pulo = abs(sin(f * .pi * max(2, (anda * 3).rounded()))) * 4
                return Pose(pe: CGPoint(x: a.x + (b.x - a.x) * s, y: a.y + (b.y - a.y) * s - pulo),
                            andando: true, esquerda: b.x < a.x)
            }
            t -= anda
            if t < espera { return Pose(pe: b, andando: false, esquerda: false) }
            t -= espera
        }
        return Pose(pe: casa, andando: false, esquerda: false)
    }

    static func desenhar(mapa: Mapa, sinal: SinalCerebro?, tempo: Double, parado: Bool, em g: GraphicsContext) {
        let poses = Fluxo.consultam.enumerated().map { i, no -> (Fluxo.No, Pose) in
            let casa = casa(no, mapa)
            // Com movimento reduzido, ninguém anda: as peças acesas já contam a história.
            let paradas = parado ? [] : paradas(no, Fluxo.partes(no, sinal) ?? [:], mapa)
            return (no, pose(casa: casa, paradas: paradas, tempo: tempo + Double(i) * 1.7))
        }
        // Quem está mais embaixo fica na frente.
        for (no, p) in poses.sorted(by: { $0.1.pe.y < $1.1.pe.y }) {
            Boneco.desenhar(no, em: g, pe: p.pe, altura: altura(mapa), tempo: tempo,
                            andando: p.andando, esquerda: p.esquerda)
        }
    }
}

/// Embaixo do mapa: o que está passando agora, em texto, e a legenda.
struct Agora: View {
    let ligacoes: [Fluxo.Ligacao]
    /// Sinal do Cérebro; nil numa central sem a rota.
    let sinal: SinalCerebro?
    var janela: Int? { sinal?.janela }

    var body: some View {
        let vivas = ligacoes.filter { $0.estado == .viva }
        let semSinal = ligacoes.contains { $0.estado == .semSinal }
        VStack(alignment: .leading, spacing: 6) {
            Text("AGORA").font(.system(size: 10, weight: .bold, design: .monospaced)).foregroundStyle(.secondary)
            if vivas.isEmpty {
                Text("Nada passando agora.").font(.system(.caption, design: .monospaced))
            }
            ForEach(vivas) { l in
                Text("\(l.de.nome) → \(l.para.nome) · \(l.rotulo)\(emPartes(l))")
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

    /// " em Projetos, Mapas" nas consultas ao Cérebro, quando a central conta as partes.
    private func emPartes(_ l: Fluxo.Ligacao) -> String {
        guard l.para == .cerebro, let p = Fluxo.partes(l.de, sinal), !p.isEmpty else { return "" }
        return " em " + Fluxo.rotuloDasPartes(p)
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
