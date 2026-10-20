import Foundation

/// Mapa do caminho da informação entre os agentes, o Cérebro, a central e os
/// aparelhos (aba Fluxo). As ligações com a central mostram pendências que
/// chegam e respostas em andamento. As ligações com o Cérebro e os auxiliares
/// vêm do sinal da central (`SinalCerebro`): consultas, registros e delegações
/// nos últimos minutos. Sem esse sinal (central antiga) ou com a fonte em falha,
/// a ligação fica "sem sinal ao vivo", nunca com atividade inventada.
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

    public static func ligacoes(itens: [Pendencia], jobs: [Job], cerebro: SinalCerebro? = nil) -> [Ligacao] {
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
            usoDoCerebro(.claude, cerebro, "consulta e registra"),
            usoDoCerebro(.codex, cerebro, "consulta e registra"),
            usoDoCerebro(.noah, cerebro, "consulta"),
            delegacao(cerebro),
        ]
    }

    /// Agente → Cérebro: viva com o que houve na janela, parada se nada houve,
    /// sem sinal se a central não mandou o sinal ou não leu essa fonte.
    static func usoDoCerebro(_ no: No, _ sinal: SinalCerebro?, _ caminho: String) -> Ligacao {
        guard let sinal, !sinal.falhas.contains(no.nome), let uso = sinal.cerebro[no.rawValue] else {
            return Ligacao(de: no, para: .cerebro, estado: .semSinal, rotulo: "\(caminho) (\(semSinal))")
        }
        let n = uso.consultas + uso.registros
        guard n > 0 else {
            return Ligacao(de: no, para: .cerebro, estado: .parada, rotulo: nadaNaJanela(sinal))
        }
        var partes: [String] = []
        if uso.consultas > 0 { partes.append(contar(uso.consultas, "consulta", "consultas")) }
        if uso.registros > 0 { partes.append(contar(uso.registros, "registro", "registros")) }
        return Ligacao(de: no, para: .cerebro, estado: .viva, quantidade: n, rotulo: partes.joined(separator: " · "))
    }

    /// Cérebro → auxiliares: soma das delegações vindas do Claude Code e do Codex
    /// que a central conseguiu ler; sem sinal se não leu nenhuma das duas.
    static func delegacao(_ sinal: SinalCerebro?) -> Ligacao {
        let lidas = [No.claude, .codex].filter { !(sinal?.falhas.contains($0.nome) ?? true) }
        let usos = lidas.compactMap { sinal?.auxiliares[$0.rawValue] }
        guard let sinal, !usos.isEmpty else {
            return Ligacao(de: .cerebro, para: .auxiliares, estado: .semSinal,
                           rotulo: "delega tarefa pequena (\(semSinal))")
        }
        let n = usos.reduce(0) { $0 + $1.delegacoes }
        return n > 0
            ? Ligacao(de: .cerebro, para: .auxiliares, estado: .viva, quantidade: n,
                      rotulo: contar(n, "tarefa delegada", "tarefas delegadas"))
            : Ligacao(de: .cerebro, para: .auxiliares, estado: .parada, rotulo: nadaNaJanela(sinal))
    }

    static func nadaNaJanela(_ sinal: SinalCerebro) -> String {
        "nada nos últimos \(max(1, sinal.janela / 60)) min"
    }

    static func contar(_ n: Int, _ singular: String, _ plural: String) -> String {
        "\(n) \(n == 1 ? singular : plural)"
    }
}
