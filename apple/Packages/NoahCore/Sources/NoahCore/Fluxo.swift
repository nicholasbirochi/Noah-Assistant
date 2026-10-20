import Foundation

/// Mapa do caminho da informação entre os agentes, o Cérebro, a central e os
/// aparelhos (aba Fluxo). Só as ligações com a central têm sinal ao vivo:
/// pendências que chegam e respostas em andamento. As consultas ao Cérebro não
/// passam pela central, então aparecem como caminho "sem sinal ao vivo", nunca
/// como atividade inventada.
public enum Fluxo {
    public enum No: String, CaseIterable, Sendable {
        case claude, codex, noah, auxiliares, cerebro, central, aparelhos

        public var nome: String {
            switch self {
            case .claude: "Claude Code"
            case .codex: "Codex"
            case .noah: "Noah"
            case .auxiliares: "Qwen local"
            case .cerebro: "Cérebro"
            case .central: "Central"
            case .aparelhos: "iPhone e Mac"
            }
        }

        public var detalhe: String {
            switch self {
            case .claude, .codex: "conversas"
            case .noah: "voz e presença"
            case .auxiliares: "auxiliares"
            case .cerebro: "segundo cérebro"
            case .central: "porta 8769"
            case .aparelhos: "este app"
            }
        }
    }

    public enum Estado: Hashable, Sendable {
        /// Há dado da central passando agora.
        case viva
        /// Ligação com sinal, mas nada passando.
        case parada
        /// Caminho que existe, mas a central não enxerga.
        case semSinal
    }

    public struct Ligacao: Hashable, Sendable, Identifiable {
        public let de: No
        public let para: No
        public let estado: Estado
        public let quantidade: Int
        public let rotulo: String
        public var id: String { "\(de.rawValue)>\(para.rawValue)" }

        public init(de: No, para: No, estado: Estado, quantidade: Int = 0, rotulo: String) {
            self.de = de
            self.para = para
            self.estado = estado
            self.quantidade = quantidade
            self.rotulo = rotulo
        }
    }

    public static let semSinal = "sem sinal ao vivo"

    public static func ligacoes(itens: [Pendencia], jobs: [Job]) -> [Ligacao] {
        let esperando = itens.filter { !$0.respondendo }
        let rodando = jobs.filter(\.rodando)
        func esperandoDe(_ fonte: String) -> Int { esperando.filter { $0.fonte == fonte }.count }
        func rodandoDe(_ fonte: String) -> Int { rodando.filter { $0.fonte == fonte }.count }
        func ligacao(_ de: No, _ para: No, _ n: Int, _ rotulo: String, _ parado: String) -> Ligacao {
            Ligacao(de: de, para: para, estado: n > 0 ? .viva : .parada, quantidade: n, rotulo: n > 0 ? rotulo : parado)
        }

        let claude = esperandoDe("claude"), codex = esperandoDe("codex"), noah = esperandoDe("noah")
        return [
            ligacao(.claude, .central, claude, contar(claude, "pendência", "pendências"), "nada esperando"),
            ligacao(.codex, .central, codex, contar(codex, "pendência", "pendências"), "nada esperando"),
            ligacao(.noah, .central, noah, contar(noah, "gerada", "geradas") + " pelo Noah", "nada gerado"),
            ligacao(.central, .aparelhos, esperando.count, contar(esperando.count, "para fazer", "para fazer"),
                    "nada para fazer"),
            ligacao(.aparelhos, .central, rodando.count, contar(rodando.count, "resposta enviada", "respostas enviadas"),
                    "nenhuma resposta agora"),
            ligacao(.central, .claude, rodandoDe("claude"), "respondendo", "sem resposta agora"),
            ligacao(.central, .codex, rodandoDe("codex"), "respondendo", "sem resposta agora"),
            Ligacao(de: .claude, para: .cerebro, estado: .semSinal, rotulo: "consulta e registra (\(semSinal))"),
            Ligacao(de: .codex, para: .cerebro, estado: .semSinal, rotulo: "consulta e registra (\(semSinal))"),
            Ligacao(de: .noah, para: .cerebro, estado: .semSinal, rotulo: "consulta (\(semSinal))"),
            Ligacao(de: .cerebro, para: .auxiliares, estado: .semSinal, rotulo: "delega tarefa pequena (\(semSinal))"),
        ]
    }

    static func contar(_ n: Int, _ singular: String, _ plural: String) -> String {
        "\(n) \(n == 1 ? singular : plural)"
    }
}
