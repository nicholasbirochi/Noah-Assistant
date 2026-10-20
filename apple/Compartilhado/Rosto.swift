import NoahCore
import SwiftUI

/// Cores do protótipo `noah-coucou.html`: azul trabalhando, âmbar esperando
/// você, verde tudo pronto. Os tons claros são para fundo escuro (ilha).
extension EstadoIlha {
    var cor: Color {
        switch self {
        case .trabalhando: Color(hex: 0x4D82F0)
        case .esperando: Color(hex: 0xF0A020)
        case .pronto: Color(hex: 0x34B357)
        case .quieto: Color(hex: 0x8A93A6)
        }
    }

    /// Tom para texto sobre preto (ilha dinâmica, Live Activity escura).
    var corClara: Color {
        switch self {
        case .trabalhando: Color(hex: 0x7FA6FF)
        case .esperando: Color(hex: 0xFFB340)
        case .pronto: Color(hex: 0x5FE08A)
        case .quieto: Color(hex: 0xC3CCDA)
        }
    }

    /// Degradê do corpo (claro no alto, forte embaixo), como `NOAH_G` no protótipo.
    var degrade: [Color] {
        switch self {
        case .trabalhando: [Color(hex: 0xEAF2FF), Color(hex: 0xA3C3FF), Color(hex: 0x4D82F0)]
        case .esperando: [Color(hex: 0xFFF5DC), Color(hex: 0xFFD27A), Color(hex: 0xF09A12)]
        case .pronto: [Color(hex: 0xEAFBEA), Color(hex: 0x9FE4A8), Color(hex: 0x38B257)]
        case .quieto: [Color(hex: 0xFFFFFF), Color(hex: 0xEEF2F8), Color(hex: 0xC3CCDA)]
        }
    }

    var simbolo: String {
        switch self {
        case .esperando: "exclamationmark.bubble.fill"
        case .trabalhando: "ellipsis.bubble.fill"
        case .pronto: "checkmark.bubble.fill"
        case .quieto: "bubble.left"
        }
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255,
                  green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255)
    }
}

/// O rosto do Noah: um cubo arredondado com dois olhos. Esperando você ganha
/// um "!" no canto; tudo pronto fecha os olhos em ^^.
struct Rosto: View {
    var estado: EstadoIlha
    var tamanho: CGFloat = 40
    /// Em widgets de tela bloqueada a cor vem do sistema (monocromático).
    var monocromatico = false

    var body: some View {
        let s = tamanho
        ZStack {
            RoundedRectangle(cornerRadius: s * 0.32, style: .continuous)
                .fill(corpo)
                .overlay(
                    RoundedRectangle(cornerRadius: s * 0.32, style: .continuous)
                        .strokeBorder(.white.opacity(monocromatico ? 0 : 0.5), lineWidth: max(0.5, s * 0.02))
                )
                .frame(width: s, height: s * 0.86)
            olhos(s)
                .offset(y: -s * 0.02)
        }
        .frame(width: s, height: s)
        .overlay(alignment: .topTrailing) {
            if estado == .esperando {
                Text("!")
                    .font(.system(size: s * 0.3, weight: .heavy, design: .rounded))
                    .foregroundStyle(.white)
                    .frame(width: s * 0.38, height: s * 0.38)
                    .background(Circle().fill(monocromatico ? Color.primary : Color(hex: 0xF0A020)))
                    .offset(x: s * 0.08, y: -s * 0.04)
            }
        }
        .accessibilityElement()
        .accessibilityLabel("Noah: \(estado.titulo)")
    }

    private var corpo: AnyShapeStyle {
        if monocromatico { return AnyShapeStyle(.primary.opacity(0.25)) }
        let g = estado.degrade
        return AnyShapeStyle(RadialGradient(colors: g, center: UnitPoint(x: 0.3, y: 0.15),
                                            startRadius: 0, endRadius: tamanho * 1.1))
    }

    private var corOlho: Color { monocromatico ? .primary : Color(hex: 0x1D2230) }

    @ViewBuilder
    private func olhos(_ s: CGFloat) -> some View {
        HStack(spacing: s * 0.2) {
            ForEach(0..<2, id: \.self) { _ in
                if estado == .pronto {
                    Arco()
                        .stroke(corOlho, style: StrokeStyle(lineWidth: max(1.2, s * 0.065), lineCap: .round))
                        .frame(width: s * 0.17, height: s * 0.1)
                } else {
                    Capsule()
                        .fill(corOlho)
                        .frame(width: s * 0.12, height: s * (estado == .esperando ? 0.24 : 0.2))
                }
            }
        }
    }
}

/// Olho fechado de feliz (^).
private struct Arco: Shape {
    func path(in r: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: r.minX, y: r.maxY))
        p.addQuadCurve(to: CGPoint(x: r.maxX, y: r.maxY), control: CGPoint(x: r.midX, y: r.minY - r.height * 0.6))
        return p
    }
}
