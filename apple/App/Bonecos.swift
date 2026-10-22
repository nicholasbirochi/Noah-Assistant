import NoahCore
import SwiftUI

/// Bonequinhos dos agentes que consultam o Cérebro, desenhados num espaço de
/// 180×180 (os mesmos traços do protótipo em SVG) e escalados para o mapa:
/// o Maestro (Claude Code), o Escriba (Codex) e o Noah, com antena de voz.
/// `pe` é onde os pés tocam o chão; o bonequinho respira, pisca e, andando,
/// vira para o lado em que vai.
enum Boneco {
    static let tinta = Color(red: 0x2a / 255, green: 0x24 / 255, blue: 0x33 / 255)
    static let rosa = Color(red: 1, green: 0x8f / 255, blue: 0xa3 / 255)

    struct RGB {
        let r: Double, g: Double, b: Double
        /// Clareia (amt > 0) ou escurece (amt < 0) como o `shade` do protótipo.
        func cor(_ amt: Double = 0) -> Color {
            func canal(_ v: Double) -> Double { min(1, max(0, v * (1 + amt))) }
            return Color(red: canal(r), green: canal(g), blue: canal(b))
        }
    }

    static func rgb(_ no: Fluxo.Ator) -> RGB {
        switch no {
        case .claude: RGB(r: 0xe2 / 255, g: 0x72 / 255, b: 0x5b / 255)
        case .codex: RGB(r: 0x2a / 255, g: 0x9d / 255, b: 0x8f / 255)
        case .noah: RGB(r: 0.7, g: 0.52, b: 1)
        }
    }

    static func desenhar(_ no: Fluxo.Ator, em g: GraphicsContext, pe: CGPoint, altura: CGFloat,
                         tempo: Double, andando: Bool, esquerda: Bool) {
        var c = g
        let escala = altura / 150
        let respira = andando ? 0 : sin(tempo * 2 * .pi / 3.2) * 0.025
        c.translateBy(x: pe.x, y: pe.y)
        c.rotate(by: .degrees(andando ? sin(tempo * 14) * 4 : 0))
        c.scaleBy(x: escala * (1 - respira) * (esquerda ? -1 : 1), y: escala * (1 + respira))
        c.translateBy(x: -90, y: -176)
        // Pisca por um instante a cada 4,6 s; cada um no seu ritmo.
        let fase = Desenho.fracao((tempo + Double(no.rawValue.count)) / 4.6)
        let olho: CGFloat = fase > 0.95 ? 0.1 : 1
        let cor = rgb(no)
        switch no {
        case .claude: maestro(c, cor, olho)
        case .codex: escriba(c, cor, olho)
        case .noah: noah(c, cor, olho)
        }
    }

    // MARK: - Os três

    static let redondo = SVG.caminho("M90 45 C132 45 146 80 146 115 C146 150 122 166 90 166 C58 166 34 150 34 115 C34 80 48 45 90 45Z")

    private static func maestro(_ c: GraphicsContext, _ cor: RGB, _ olho: CGFloat) {
        sombra(c, 90, 50)
        pes(c, 70, 110, 168, cor)
        membro(c, "M48 116 Q28 104 24 84", cor)
        membro(c, "M132 116 Q152 104 156 86", cor)
        corpo(c, redondo, cor)
        brilho(c, 64, 70)
        preencher(c, SVG.caminho("M86 47 Q82 28 99 31 Q89 36 95 46"), cor.cor(), contorno: 3.5)
        olhos(c, 75, 105, 100, olho)
        bochechas(c, 61, 119, 114)
        sorrisao(c, 90, 116)
        let roxo = Color(red: 0x3b / 255, green: 0x2e / 255, blue: 0x5a / 255)
        preencher(c, SVG.caminho("M90 141 L74 132 L74 150 Z M90 141 L106 132 L106 150 Z"), roxo, contorno: 3)
        preencher(c, elipse(90, 141, 4.5, 4.5), roxo, contorno: 3)
        tracar(c, SVG.caminho("M157 84 L170 46"), tinta, 4.5)
        preencher(c, elipse(170, 45, 3.5, 3.5), .white, contorno: 2.5)
        mao(c, 24, 84, cor)
        mao(c, 156, 86, cor)
        estrela(c, 160, 28, 7)
        let nota = Color.white.opacity(0.75)
        tracar(c, SVG.caminho("M22 60 L22 42 L34 38 L34 56"), nota, 3)
        c.fill(elipse(18.5, 60, 4.5, 3.4), with: .color(nota))
        c.fill(elipse(30.5, 56, 4.5, 3.4), with: .color(nota))
    }

    private static func escriba(_ c: GraphicsContext, _ cor: RGB, _ olho: CGFloat) {
        sombra(c, 90, 50)
        pes(c, 70, 110, 168, cor)
        corpo(c, SVG.caminho("M90 38 C130 38 142 70 142 112 C142 150 120 166 90 166 C60 166 38 150 38 112 C38 70 50 38 90 38Z"), cor)
        brilho(c, 64, 64)
        olhos(c, 76, 104, 98, olho)
        for x in [76.0, 104] {
            c.fill(elipse(x, 98, 12.5, 12.5), with: .color(.white.opacity(0.28)))
            c.stroke(elipse(x, 98, 12.5, 12.5), with: .color(tinta), lineWidth: 3.5)
        }
        tracar(c, SVG.caminho("M88.5 97 Q90 94 91.5 97"), tinta, 3.5)
        bochechas(c, 58, 122, 118)
        sorriso(c, 90, 120)
        preencher(c, SVG.caminho("M90 137 Q73 131 52 135 L52 161 Q73 157 90 162 Q107 157 128 161 L128 135 Q107 131 90 137Z"),
                  Color(red: 0x9b / 255, green: 0x2c / 255, blue: 0x3b / 255), contorno: 3.5)
        preencher(c, SVG.caminho("M90 134 Q76 128 57 132 L57 156 Q76 152 90 158 Z M90 134 Q104 128 123 132 L123 156 Q104 152 90 158 Z"),
                  Color(red: 1, green: 0xf6 / 255, blue: 0xe0 / 255), contorno: 3)
        for d in ["M64 140 Q75 137 84 140", "M64 146 Q75 143 84 146", "M96 140 Q105 137 116 140", "M96 146 Q105 143 112 146"] {
            tracar(c, SVG.caminho(d), tinta.opacity(0.4), 2)
        }
        mao(c, 56, 147, cor)
        mao(c, 124, 147, cor)
    }

    /// Desenho novo (o protótipo não tem o Noah): corpo redondo na cor do Noah,
    /// olhos felizes e uma antena com ondas de voz.
    private static func noah(_ c: GraphicsContext, _ cor: RGB, _ olho: CGFloat) {
        sombra(c, 90, 50)
        pes(c, 70, 110, 168, cor)
        membro(c, "M48 120 Q32 116 28 102", cor)
        membro(c, "M132 120 Q148 116 152 102", cor)
        tracar(c, SVG.caminho("M90 47 L90 30"), tinta, 4)
        preencher(c, elipse(90, 26, 6, 6), cor.cor(0.25), contorno: 3.5)
        let onda = Color.white.opacity(0.8)
        tracar(c, SVG.caminho("M102 20 Q108 26 102 32"), onda, 3)
        tracar(c, SVG.caminho("M109 14 Q119 26 109 38"), onda, 3)
        tracar(c, SVG.caminho("M78 20 Q72 26 78 32"), onda, 3)
        corpo(c, redondo, cor)
        brilho(c, 64, 70)
        if olho < 1 {
            tracar(c, SVG.caminho("M69 100 L81 100 M99 100 L111 100"), tinta, 3.5)
        } else {
            for x in [75.0, 105] { tracar(c, SVG.caminho("M\(x - 6) 102 Q\(x) 94 \(x + 6) 102"), tinta, 3.5) }
        }
        bochechas(c, 61, 119, 114)
        sorriso(c, 90, 118)
        mao(c, 28, 102, cor)
        mao(c, 152, 102, cor)
        estrela(c, 30, 52, 6)
    }

    // MARK: - Peças (as mesmas funções do protótipo)

    private static func elipse(_ x: CGFloat, _ y: CGFloat, _ rx: CGFloat, _ ry: CGFloat) -> Path {
        Path(ellipseIn: CGRect(x: x - rx, y: y - ry, width: rx * 2, height: ry * 2))
    }

    private static func preencher(_ c: GraphicsContext, _ p: Path, _ cor: Color, contorno: CGFloat = 4) {
        c.fill(p, with: .color(cor))
        c.stroke(p, with: .color(tinta), style: StrokeStyle(lineWidth: contorno, lineCap: .round, lineJoin: .round))
    }

    private static func tracar(_ c: GraphicsContext, _ p: Path, _ cor: Color, _ largura: CGFloat) {
        c.stroke(p, with: .color(cor), style: StrokeStyle(lineWidth: largura, lineCap: .round, lineJoin: .round))
    }

    private static func sombra(_ c: GraphicsContext, _ cx: CGFloat, _ rx: CGFloat) {
        c.fill(elipse(cx, 176, rx, 6), with: .color(.black.opacity(0.35)))
    }

    private static func corpo(_ c: GraphicsContext, _ p: Path, _ cor: RGB) { preencher(c, p, cor.cor()) }

    private static func brilho(_ c: GraphicsContext, _ x: CGFloat, _ y: CGFloat) {
        let giro = CGAffineTransform(rotationAngle: -35 * .pi / 180).concatenating(CGAffineTransform(translationX: x, y: y))
        c.fill(elipse(0, 0, 11, 6).applying(giro), with: .color(.white.opacity(0.3)))
    }

    private static func membro(_ c: GraphicsContext, _ d: String, _ cor: RGB, _ w: CGFloat = 8) {
        let p = SVG.caminho(d)
        tracar(c, p, tinta, w + 8)
        tracar(c, p, cor.cor(), w)
    }

    private static func mao(_ c: GraphicsContext, _ x: CGFloat, _ y: CGFloat, _ cor: RGB) {
        preencher(c, elipse(x, y, 7, 7), cor.cor(), contorno: 3.5)
    }

    private static func pes(_ c: GraphicsContext, _ x1: CGFloat, _ x2: CGFloat, _ y: CGFloat, _ cor: RGB) {
        for x in [x1, x2] { preencher(c, elipse(x, y, 14, 7.5), cor.cor(-0.28)) }
    }

    private static func olhos(_ c: GraphicsContext, _ x1: CGFloat, _ x2: CGFloat, _ y: CGFloat, _ abertura: CGFloat) {
        let rx: CGFloat = 4.6, ry: CGFloat = 6
        for x in [x1, x2] {
            c.fill(elipse(x, y, rx, ry * abertura), with: .color(tinta))
            if abertura == 1 { c.fill(elipse(x - rx * 0.33, y - ry * 0.37, rx * 0.37, rx * 0.37), with: .color(.white)) }
        }
    }

    private static func bochechas(_ c: GraphicsContext, _ x1: CGFloat, _ x2: CGFloat, _ y: CGFloat) {
        for x in [x1, x2] { c.fill(elipse(x, y, 7, 4.2), with: .color(rosa.opacity(0.5))) }
    }

    private static func sorriso(_ c: GraphicsContext, _ x: CGFloat, _ y: CGFloat) {
        tracar(c, SVG.caminho("M\(x - 7) \(y) Q\(x) \(y + 7) \(x + 7) \(y)"), tinta, 3.5)
    }

    private static func sorrisao(_ c: GraphicsContext, _ x: CGFloat, _ y: CGFloat) {
        preencher(c, SVG.caminho("M\(x - 8) \(y) Q\(x) \(y + 12) \(x + 8) \(y) Z"), tinta, contorno: 2.5)
        tracar(c, SVG.caminho("M\(x - 3.5) \(y + 5.5) Q\(x) \(y + 3) \(x + 3.5) \(y + 5.5)"), rosa, 2.5)
    }

    private static func estrela(_ c: GraphicsContext, _ x: CGFloat, _ y: CGFloat, _ s: CGFloat) {
        let d = "M\(x) \(y - s) Q\(x) \(y) \(x + s) \(y) Q\(x) \(y) \(x) \(y + s) Q\(x) \(y) \(x - s) \(y) Q\(x) \(y) \(x) \(y - s) Z"
        preencher(c, SVG.caminho(d), Color(red: 1, green: 0xe2 / 255, blue: 0x8a / 255), contorno: 2)
    }
}

/// Leitor mínimo de caminhos SVG: só os comandos absolutos M, L, Q, C e Z,
/// que são os que os bonequinhos usam.
enum SVG {
    static func caminho(_ d: String) -> Path {
        var p = Path()
        var numeros: [CGFloat] = []
        var comando: Character = " "
        var numero = ""

        func fecharNumero() {
            if let v = Double(numero) { numeros.append(CGFloat(v)) }
            numero = ""
        }
        func aplicar() {
            var i = 0
            func ponto() -> CGPoint {
                defer { i += 2 }
                return CGPoint(x: numeros[i], y: numeros[i + 1])
            }
            switch comando {
            case "M":
                while i + 1 < numeros.count { if i == 0 { p.move(to: ponto()) } else { p.addLine(to: ponto()) } }
            case "L":
                while i + 1 < numeros.count { p.addLine(to: ponto()) }
            case "Q":
                while i + 3 < numeros.count {
                    let c = ponto()
                    p.addQuadCurve(to: ponto(), control: c)
                }
            case "C":
                while i + 5 < numeros.count {
                    let c1 = ponto(), c2 = ponto()
                    p.addCurve(to: ponto(), control1: c1, control2: c2)
                }
            case "Z":
                p.closeSubpath()
            default:
                break
            }
            numeros = []
        }

        for ch in d {
            if ch.isLetter {
                fecharNumero()
                aplicar()
                comando = ch
            } else if ch == "-" {
                fecharNumero()
                numero = "-"
            } else if ch.isNumber || ch == "." {
                numero.append(ch)
            } else {
                fecharNumero()
            }
        }
        fecharNumero()
        aplicar()
        return p
    }
}
