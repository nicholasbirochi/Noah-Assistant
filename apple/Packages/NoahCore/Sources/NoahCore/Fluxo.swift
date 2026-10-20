import Foundation

/// Mapa do caminho da informação entre os agentes, o Cérebro, a central e os
/// aparelhos (aba Fluxo). As ligações com a central mostram pendências que
/// chegam e respostas em andamento. As ligações com o Cérebro e os auxiliares
/// vêm do sinal da central (`SinalCerebro`): consultas, registros e delegações
/// nos últimos minutos. Sem esse sinal (central antiga) ou com a fonte em falha,
/// a ligação fica "sem sinal ao vivo", nunca com atividade inventada. O mesmo
/// sinal conta as pastas do cofre citadas (`Parte`), para o Cérebro aparecer em
/// pedaços com as partes que cada agente tocou; sem essa contagem, nada acende.
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

    // MARK: - Partes do Cérebro

    /// As pastas do cofre, na ordem em que o Cérebro aparece em pedaços.
    public enum Parte: String, CaseIterable, Sendable, Comparable {
        case regras = "00", indices = "01", projetos = "02", mapas = "03"
        case decisoes = "04", padroes = "05", logs = "06", templates = "07"

        public var nome: String {
            switch self {
            case .regras: "Regras"
            case .indices: "Índices"
            case .projetos: "Projetos"
            case .mapas: "Mapas"
            case .decisoes: "Decisões"
            case .padroes: "Padrões"
            case .logs: "Logs"
            case .templates: "Templates"
            }
        }

        /// Nome da pasta no cofre.
        public var pasta: String {
            switch self {
            case .regras: "00 - Regras para Agentes"
            case .indices: "01 - Índices"
            case .projetos: "02 - Projetos"
            case .mapas: "03 - Graphify e Mapas de Projeto"
            case .decisoes: "04 - Decisões Técnicas"
            case .padroes: "05 - Padrões e Preferências"
            case .logs: "06 - Logs de Tarefas"
            case .templates: "07 - Templates"
            }
        }

        public static func < (a: Parte, b: Parte) -> Bool { a.rawValue < b.rawValue }
    }

    /// Agentes que consultam o Cérebro (cada um tem seu bonequinho no Fluxo).
    public static let consultam: [No] = [.claude, .codex, .noah]

    /// Que partes do Cérebro o agente tocou na janela e quantas vezes.
    /// nil = sem sinal por parte: central antiga (sem `partes`), fonte em falha
    /// ou sinal ausente. Vazio = tem sinal, mas nenhuma pasta foi citada.
    public static func partes(_ no: No, _ sinal: SinalCerebro?) -> [Parte: Int]? {
        guard let sinal, !sinal.falhas.contains(no.nome), let brutas = sinal.cerebro[no.rawValue]?.partes else {
            return nil
        }
        var saida: [Parte: Int] = [:]
        for (codigo, n) in brutas where n > 0 {
            if let parte = Parte(rawValue: codigo) { saida[parte, default: 0] += n }
        }
        return saida
    }

    /// Para cada parte do Cérebro, quem a tocou na janela (na ordem de `consultam`).
    public static func visitas(_ sinal: SinalCerebro?) -> [Parte: [No]] {
        var saida: [Parte: [No]] = [:]
        for no in consultam {
            for parte in (partes(no, sinal) ?? [:]).keys.sorted() { saida[parte, default: []].append(no) }
        }
        return saida
    }

    /// Texto curto das partes tocadas, da mais citada para a menos ("Projetos, Mapas").
    public static func rotuloDasPartes(_ partes: [Parte: Int]) -> String {
        partes.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }
            .map(\.key.nome).joined(separator: ", ")
    }

    static func nadaNaJanela(_ sinal: SinalCerebro) -> String {
        "nada nos últimos \(max(1, sinal.janela / 60)) min"
    }

    static func contar(_ n: Int, _ singular: String, _ plural: String) -> String {
        "\(n) \(n == 1 ? singular : plural)"
    }
}
