import CoreGraphics
import Foundation

/// Regras da ilha no notch do Mac que não dependem do AppKit: o tamanho da
/// pílula fechada e quando abrir, espiar e fechar. O painel de verdade fica
/// em `apple/App/IlhaMac.swift`.
public enum IlhaNotch {
    /// Quanto tempo a ilha fica aberta sozinha quando chega pendência nova.
    public static let tempoEspiando: TimeInterval = 4
    /// Folga depois que o mouse sai, para não fechar num tremor da mão nem
    /// quando o mouse passa pela borda ou pela sombra do cartão.
    public static let folgaAoSair: TimeInterval = 0.6
    /// Margem em volta do cartão aberto que ainda conta como "em cima".
    public static let margemAberta: CGFloat = 20
    /// Distância entre a área do Alcove e a ilha do Noah, quando ficam lado a lado.
    public static let vaoAlcove: CGFloat = 8

    /// Tamanho da pílula fechada. Com notch, as asas saem dos lados dele;
    /// sem notch, fica no meio da barra de menus, da altura dela.
    public static func tamanhoFechado(_ estado: EstadoIlha, notch: CGSize, barra: CGFloat) -> CGSize {
        let asa: CGFloat = estado == .quieto ? 34 : 84
        if notch.width > 0 { return CGSize(width: notch.width + asa * 2, height: notch.height) }
        return CGSize(width: estado == .quieto ? 120 : 190, height: barra)
    }

    /// Espia só quando aumenta o que espera você; responder ou dispensar não abre a ilha.
    public static func deveEspiar(antes: Int, depois: Int) -> Bool { depois > antes }

    /// Área que conta como "mouse em cima", em coordenadas de tela (origem embaixo).
    /// Aberta: o cartão mais `margemAberta` dos lados e embaixo, e tudo acima dele
    /// até a borda da tela, para a borda e a sombra não fecharem a ilha. Fechada: a
    /// pílula com poucos pontos de folga, para abrir encostando no topo sem pegar a barra de menus.
    public static func zonaDeHover(_ forma: CGRect, aberta: Bool) -> CGRect {
        if aberta {
            let m = margemAberta
            return CGRect(x: forma.minX - m, y: forma.minY - m,
                          width: forma.width + m * 2, height: forma.height + m + 40)
        }
        return forma.insetBy(dx: -8, dy: -4)
    }

    /// Onde fica a ilha na horizontal. Sem Alcove, centralizada na tela. Com o
    /// Alcove ocupando o meio do topo (ele desenha por cima de qualquer janela), a
    /// ilha encosta à direita da área dele e cresce para a direita; se não couber,
    /// à esquerda, crescendo para a esquerda.
    /// - Parameters:
    ///   - tela: faixa horizontal da tela (minX...maxX).
    ///   - largura: largura do painel da ilha.
    ///   - alcove: faixa horizontal ocupada pelo Alcove, se ele estiver aberto nesta tela.
    public static func posicao(tela: ClosedRange<CGFloat>, largura: CGFloat,
                               alcove: ClosedRange<CGFloat>?) -> Posicao {
        guard let a = alcove else {
            return Posicao(x: (tela.lowerBound + tela.upperBound - largura) / 2, alinhamento: .centro)
        }
        let direita = a.upperBound + vaoAlcove
        if direita + largura <= tela.upperBound { return Posicao(x: direita, alinhamento: .esquerda) }
        let esquerda = a.lowerBound - vaoAlcove - largura
        if esquerda >= tela.lowerBound { return Posicao(x: esquerda, alinhamento: .direita) }
        return Posicao(x: (tela.lowerBound + tela.upperBound - largura) / 2, alinhamento: .centro)
    }

    public enum Alinhamento: Equatable, Sendable { case centro, esquerda, direita }

    /// `x`: borda esquerda do painel; `alinhamento`: onde a pílula fica dentro dele.
    public struct Posicao: Equatable, Sendable {
        public var x: CGFloat
        public var alinhamento: Alinhamento
        public init(x: CGFloat, alinhamento: Alinhamento) {
            self.x = x
            self.alinhamento = alinhamento
        }
    }

    public enum Acao: Equatable, Sendable { case abrir, fechar, nada }

    /// Segue o mouse a cada passo do relógio e diz o que fazer com a ilha.
    public struct Seguidor: Sendable {
        public private(set) var aberta = false
        private var saiuEm: Date?
        private var espiarAte: Date?

        public init() {}

        /// `dentro`: o mouse está sobre a ilha (com a folga já aplicada).
        /// `segurar`: você está escrevendo uma resposta; aberta, ela não fecha
        /// quando o mouse sai, só quando o campo perde o foco.
        public mutating func passo(dentro: Bool, agora: Date, segurar: Bool = false) -> Acao {
            if dentro || (segurar && aberta) {
                saiuEm = nil
                return aberta ? .nada : abrir()
            }
            guard aberta else { return .nada }
            if let ate = espiarAte, agora < ate { return .nada }
            guard let saiu = saiuEm else {
                saiuEm = agora
                return .nada
            }
            return agora.timeIntervalSince(saiu) > IlhaNotch.folgaAoSair ? fechar() : .nada
        }

        /// Abre sozinha por `tempoEspiando`, mesmo com o mouse longe.
        public mutating func espiar(agora: Date) -> Acao {
            espiarAte = agora.addingTimeInterval(IlhaNotch.tempoEspiando)
            saiuEm = nil
            return aberta ? .nada : abrir()
        }

        public mutating func abrir() -> Acao {
            aberta = true
            return .abrir
        }

        public mutating func fechar() -> Acao {
            aberta = false
            saiuEm = nil
            espiarAte = nil
            return .fechar
        }
    }
}
