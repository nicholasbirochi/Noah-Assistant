import Foundation

/// Decide quando a sua fala virou uma mensagem para o Noah na aba Central.
/// O reconhecedor devolve o texto acumulado da frase a cada trecho; quando ele
/// para de mudar por `silencio` segundos, a frase está pronta para enviar.
public struct TurnoDeVoz: Sendable {
    /// Pausa que fecha a frase.
    public var silencio: TimeInterval
    /// O que já foi ouvido da frase em andamento.
    public private(set) var parcial = ""
    private var ultimaMudanca: Date?

    public init(silencio: TimeInterval = 1.4) {
        self.silencio = silencio
    }

    /// Novo trecho do reconhecedor (o texto inteiro da frase até agora).
    public mutating func ouviu(_ texto: String, em quando: Date) {
        let limpo = texto.trimmingCharacters(in: .whitespacesAndNewlines)
        guard limpo != parcial else { return }
        parcial = limpo
        ultimaMudanca = quando
    }

    /// Se a pausa já passou, devolve a frase pronta e começa outra. Ruído de um
    /// caractere só ("a", "é") não vira mensagem.
    public mutating func fechar(em agora: Date) -> String? {
        guard let desde = ultimaMudanca, agora.timeIntervalSince(desde) >= silencio else { return nil }
        let frase = parcial
        descartar()
        return frase.filter { $0.isLetter || $0.isNumber }.count >= 2 ? frase : nil
    }

    /// Esquece a frase em andamento (microfone mudo, Noah falando).
    public mutating func descartar() {
        parcial = ""
        ultimaMudanca = nil
    }
}

public enum FalaDoNoah {
    /// Texto da resposta pronto para a voz do sistema: sem blocos de código,
    /// marcações de Markdown nem endereços, e curto. O resto fica no chat.
    public static func paraFalar(_ resposta: String, limite: Int = 600) -> String {
        var t = resposta
        // Bloco de código não se lê em voz alta.
        t = t.replacingOccurrences(of: "```[\\s\\S]*?```", with: " (código no chat) ",
                                   options: .regularExpression)
        // [texto](link) vira só o texto; endereço solto sai.
        t = t.replacingOccurrences(of: "\\[([^\\]]+)\\]\\([^)]*\\)", with: "$1", options: .regularExpression)
        t = t.replacingOccurrences(of: "https?://\\S+", with: "", options: .regularExpression)
        t = t.replacingOccurrences(of: "[`*_#>|]", with: "", options: .regularExpression)
        // Marcador de lista no começo da linha.
        t = t.replacingOccurrences(of: "(?m)^\\s*[-•]\\s+", with: "", options: .regularExpression)
        t = t.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespaces)
        guard t.count > limite else { return t }
        // Corta no fim da última frase que cabe.
        let corte = String(t.prefix(limite))
        if let fim = corte.lastIndex(where: { ".!?".contains($0) }), corte.distance(from: corte.startIndex, to: fim) > limite / 3 {
            return String(corte[...fim]) + " O resto está no chat."
        }
        return corte + "… O resto está no chat."
    }
}
