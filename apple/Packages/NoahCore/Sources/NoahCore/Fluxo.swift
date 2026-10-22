import Foundation

/// Mapa do caminho da informação (aba Fluxo): Claude Code, Codex e Noah ligados
/// direto a cada modelo que usam (Qwen local, Nemotron, Copilot), ao Cérebro e
/// às pastas dele, à central e aos aparelhos.
///
/// Só acende o que tem rastro real: pendências e respostas da central,
/// `ultimo_uso` dos auxiliares, notas novas no Cérebro e turnos do Noah (tudo de
/// `GET /central/api/atividade`), mais as consultas e registros de cada agente no
/// Cérebro (`GET /central/api/cerebro`, em `SinalCerebro`). Caminho que a central
/// não consegue ler aparece como "sem sinal ao vivo", nunca como atividade
/// inventada.
public enum Fluxo {
    public enum Tipo: String, Hashable, Sendable {
        case agente, noah, central, aparelhos, cerebro, pasta, modelo, nota
    }

    public struct No: Identifiable, Hashable, Sendable {
        public let id: String
        public let nome: String
        public let detalhe: String
        public let tipo: Tipo

        public init(id: String, nome: String, detalhe: String, tipo: Tipo) {
            self.id = id
            self.nome = nome
            self.detalhe = detalhe
            self.tipo = tipo
        }
    }

    public enum Estado: Hashable, Sendable {
        /// Há dado passando agora (ou nos últimos minutos).
        case viva
        /// Ligação com sinal, mas nada passando.
        case parada
        /// Caminho que existe, mas não deixa rastro que a central leia.
        case semSinal
    }

    public struct Ligacao: Hashable, Sendable, Identifiable {
        public let de: String
        public let para: String
        public let estado: Estado
        public let quantidade: Int
        public let rotulo: String
        public var id: String { "\(de)>\(para)" }

        public init(de: String, para: String, estado: Estado, quantidade: Int = 0, rotulo: String) {
            self.de = de
            self.para = para
            self.estado = estado
            self.quantidade = quantidade
            self.rotulo = rotulo
        }
    }

    public struct Grafo: Sendable {
        public let nos: [No]
        public let ligacoes: [Ligacao]

        public func no(_ id: String) -> No? { nos.first { $0.id == id } }
        public func ligacao(_ de: String, _ para: String) -> Ligacao? {
            ligacoes.first { $0.de == de && $0.para == para }
        }
        public func aceso(_ id: String) -> Bool {
            ligacoes.contains { $0.estado == .viva && ($0.de == id || $0.para == id) }
        }
    }

    public static let semSinal = "sem sinal ao vivo"
    /// Quanto tempo um uso, uma nota ou uma consulta continua aceso.
    public static let janela: Double = 600
    /// ROTAS de src/central/atividade.py, para quando a central ainda não respondeu.
    public static let modelosPadrao = ["qwen2.5-coder:7b", "qwen2.5-coder:14b", "qwen3-coder:30b", "nemotron", "copilot"]

    public static let claude = "claude", codex = "codex", noah = "noah"
    public static let central = "central", aparelhos = "aparelhos", cerebro = "cerebro"
    public static func modelo(_ id: String) -> String { "modelo:\(id)" }
    public static func pasta(_ numero: String) -> String { "pasta-\(numero)" }
    public static func subpasta(_ pai: String, _ nome: String) -> String { "\(pai)/\(nome)" }
    public static func nota(_ pai: String, _ nome: String) -> String { "nota:\(pai)/\(nome)" }
    /// Quantos itens de uma pasta aberta aparecem no mapa; o resto vira "+N".
    public static let maxFilhos = 12

    public static func grafo(itens: [Pendencia], jobs: [Job], painel: PainelCentral? = nil,
                             agora: Double = Date().timeIntervalSince1970, cerebroAberto: Bool = true,
                             abertos: Set<String> = [], cerebro sinal: SinalCerebro? = nil) -> Grafo {
        let agora = painel?.geradoEm ?? agora
        func recente(_ quando: Double?) -> Bool { quando.map { agora - $0 <= janela } ?? false }

        let pastas = painel?.cerebro.pastas ?? []
        var nos = [
            No(id: claude, nome: "Claude Code", detalhe: "conversas", tipo: .agente),
            No(id: codex, nome: "Codex", detalhe: "conversas", tipo: .agente),
            No(id: noah, nome: "Noah", detalhe: "voz e conversa", tipo: .noah),
            No(id: cerebro, nome: "Cérebro",
               detalhe: cerebroAberto ? "toque para fechar"
                   : pastas.isEmpty ? "segundo cérebro · toque" : "\(contar(pastas.count, "pasta", "pastas")) · toque",
               tipo: .cerebro),
            No(id: central, nome: "Central", detalhe: "porta 8769", tipo: .central),
            No(id: aparelhos, nome: "iPhone e Mac", detalhe: "este app", tipo: .aparelhos),
        ]
        var ligacoes = ligacoesDaCentral(itens: itens, jobs: jobs)

        // Modelos: os que têm rota (o que os agentes delegam) e o do Noah.
        let doNoah = painel?.noah?.modelo
        var modelos: [ModeloAuxiliar]
        if let painel {
            modelos = painel.modelos.filter { !$0.rotas.isEmpty || $0.id == doNoah }
            if let doNoah, !modelos.contains(where: { $0.id == doNoah }) {
                modelos.append(ModeloAuxiliar(id: doNoah, provedor: painel.noah?.provedor ?? "", local: true,
                                              disponivel: nil, rotas: []))
            }
        } else {
            modelos = modelosPadrao.map { ModeloAuxiliar(id: $0, disponivel: nil) }
        }
        for m in modelos {
            let id = modelo(m.id)
            nos.append(No(id: id, nome: nomeCurto(m), detalhe: detalhe(m, doNoah: m.id == doNoah, semDados: painel == nil),
                          tipo: .modelo))
            if !m.rotas.isEmpty {
                // O registro dos auxiliares não diz se foi o Claude ou o Codex que
                // delegou: as duas acendem, e só a do Claude leva o rótulo.
                let usou = recente(m.ultimoUso)
                let rotulo = contar(m.usos24h, "uso", "usos") + " em 24 h"
                ligacoes.append(Ligacao(de: claude, para: id, estado: usou ? .viva : .parada,
                                        quantidade: usou ? m.usos24h : 0, rotulo: usou ? rotulo : ""))
                ligacoes.append(Ligacao(de: codex, para: id, estado: usou ? .viva : .parada,
                                        quantidade: usou ? m.usos24h : 0, rotulo: ""))
            }
            if m.id == doNoah {
                let respondendo = painel?.noah?.respondendoDesde != nil
                ligacoes.append(Ligacao(de: noah, para: id, estado: respondendo ? .viva : .parada,
                                        quantidade: respondendo ? 1 : 0, rotulo: respondendo ? "pensando" : ""))
            }
        }

        // Conversa da aba Central: app -> central -> Noah.
        let conversando = painel?.noah?.respondendoDesde != nil
        ligacoes.append(Ligacao(de: central, para: noah, estado: conversando ? .viva : .parada,
                                quantidade: conversando ? 1 : 0, rotulo: conversando ? "conversa no app" : ""))

        // Cérebro: com o sinal da central, conta consultas e registros de cada um
        // na janela. Sem ele (central antiga), só nota nova deixa rastro.
        let eventos = painel?.eventos ?? []
        let nota = eventos.first { $0.tipo == "nota" && $0.para == cerebro && recente($0.quando) }
        let consultaDoNoah = eventos.contains { $0.de == noah && $0.para == cerebro && recente($0.quando) }
        for ator in Ator.allCases {
            let caminho = ator == .noah ? "consulta" : "consulta e registra"
            if let sinal {
                ligacoes.append(usoDoCerebro(ator, sinal, caminho))
            } else if ator == .noah ? consultaDoNoah : nota != nil {
                ligacoes.append(Ligacao(de: ator.rawValue, para: cerebro, estado: .viva, quantidade: 1,
                                        rotulo: ator == .noah ? "consultou" : ator == .claude ? "registrou nota" : ""))
            } else {
                ligacoes.append(Ligacao(de: ator.rawValue, para: cerebro, estado: .semSinal,
                                        rotulo: "\(caminho) (\(semSinal))"))
            }
        }

        // Pasta aberta mostra o que tem dentro (só nomes e datas), e assim por diante.
        func abrir(_ pai: String, _ itens: [ItemCerebro]) {
            guard abertos.contains(pai) else { return }
            for item in itens.prefix(maxFilhos) {
                let id = item.pasta ? subpasta(pai, item.nome) : Fluxo.nota(pai, item.nome)
                let nova = recente(item.atualizadaEm)
                nos.append(No(id: id, nome: item.nome,
                              detalhe: item.pasta ? contar(item.notas, "nota", "notas")
                                  : nova ? "nota nova" : idade(item.atualizadaEm, agora: agora),
                              tipo: item.pasta ? .pasta : .nota))
                ligacoes.append(Ligacao(de: pai, para: id, estado: nova ? .viva : .parada,
                                        quantidade: nova ? 1 : 0, rotulo: nova && item.pasta ? "nota nova" : ""))
                if item.pasta { abrir(id, item.itens) }
            }
            if itens.count > maxFilhos {
                let id = "mais:\(pai)"
                nos.append(No(id: id, nome: "+\(itens.count - maxFilhos)", detalhe: "mais itens", tipo: .nota))
                ligacoes.append(Ligacao(de: pai, para: id, estado: .parada, rotulo: ""))
            }
        }

        if cerebroAberto {
            for p in pastas {
                let id = pasta(p.numero)
                nos.append(No(id: id, nome: "\(p.numero) \(p.nome)", detalhe: contar(p.notas, "nota", "notas"),
                              tipo: .pasta))
                let nova = recente(p.atualizadaEm)
                ligacoes.append(Ligacao(de: cerebro, para: id, estado: nova ? .viva : .parada,
                                        quantidade: nova ? 1 : 0, rotulo: nova ? "nota nova" : ""))
                abrir(id, p.itens)
            }
        }
        return Grafo(nos: nos, ligacoes: ligacoes)
    }

    // MARK: - Uso do Cérebro

    /// Quem consulta o Cérebro; o `rawValue` é o id do nó e a chave em `SinalCerebro.cerebro`.
    public enum Ator: String, CaseIterable, Sendable {
        case claude, codex, noah

        /// Como aparece em `SinalCerebro.falhas`.
        public var nome: String {
            switch self {
            case .claude: "Claude Code"
            case .codex: "Codex"
            case .noah: "Noah"
            }
        }
    }

    /// As pastas numeradas do Cérebro, na ordem do cofre.
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

    public static let consultam: [Ator] = Ator.allCases

    /// A ligação de um agente ao Cérebro segundo o sinal: viva com a contagem,
    /// parada se nada passou na janela, sem sinal se a central não leu a fonte.
    static func usoDoCerebro(_ ator: Ator, _ sinal: SinalCerebro, _ caminho: String) -> Ligacao {
        guard !sinal.falhas.contains(ator.nome), let uso = sinal.cerebro[ator.rawValue] else {
            return Ligacao(de: ator.rawValue, para: cerebro, estado: .semSinal, rotulo: "\(caminho) (\(semSinal))")
        }
        let n = uso.consultas + uso.registros
        guard n > 0 else {
            return Ligacao(de: ator.rawValue, para: cerebro, estado: .parada, rotulo: nadaNaJanela(sinal))
        }
        var partes: [String] = []
        if uso.consultas > 0 { partes.append(contar(uso.consultas, "consulta", "consultas")) }
        if uso.registros > 0 { partes.append(contar(uso.registros, "registro", "registros")) }
        return Ligacao(de: ator.rawValue, para: cerebro, estado: .viva, quantidade: n,
                       rotulo: partes.joined(separator: " · "))
    }

    /// Em que partes do Cérebro o agente mexeu na janela; nil quando não há sinal.
    public static func partes(_ ator: Ator, _ sinal: SinalCerebro?) -> [Parte: Int]? {
        guard let sinal, !sinal.falhas.contains(ator.nome), let brutas = sinal.cerebro[ator.rawValue]?.partes else {
            return nil
        }
        var saida: [Parte: Int] = [:]
        for (codigo, n) in brutas where n > 0 {
            if let parte = Parte(rawValue: codigo) { saida[parte, default: 0] += n }
        }
        return saida
    }

    /// Para cada parte, quem passou por ela (na ordem de `consultam`).
    public static func visitas(_ sinal: SinalCerebro?) -> [Parte: [Ator]] {
        var saida: [Parte: [Ator]] = [:]
        for ator in consultam {
            for parte in (partes(ator, sinal) ?? [:]).keys.sorted() { saida[parte, default: []].append(ator) }
        }
        return saida
    }

    /// "Projetos, Mapas, Logs": as mais usadas primeiro, empate pela ordem do cofre.
    public static func rotuloDasPartes(_ partes: [Parte: Int]) -> String {
        partes.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }
            .map(\.key.nome).joined(separator: ", ")
    }

    static func nadaNaJanela(_ sinal: SinalCerebro) -> String { "nada nos últimos \(max(1, sinal.janela / 60)) min" }

    // MARK: - Central e rótulos

    /// Pendências que chegam e respostas que voltam: o que passa pela central.
    static func ligacoesDaCentral(itens: [Pendencia], jobs: [Job]) -> [Ligacao] {
        let esperando = itens.filter { !$0.respondendo }
        let rodando = jobs.filter(\.rodando)
        func esperandoDe(_ fonte: String) -> Int { esperando.filter { $0.fonte == fonte }.count }
        func rodandoDe(_ fonte: String) -> Int { rodando.filter { $0.fonte == fonte }.count }
        func ligacao(_ de: String, _ para: String, _ n: Int, _ rotulo: String, _ parado: String) -> Ligacao {
            Ligacao(de: de, para: para, estado: n > 0 ? .viva : .parada, quantidade: n, rotulo: n > 0 ? rotulo : parado)
        }

        let c = esperandoDe(claude), x = esperandoDe(codex), n = esperandoDe(noah)
        return [
            ligacao(claude, central, c, contar(c, "pendência", "pendências"), "nada esperando"),
            ligacao(codex, central, x, contar(x, "pendência", "pendências"), "nada esperando"),
            ligacao(noah, central, n, contar(n, "gerada", "geradas") + " pelo Noah", "nada gerado"),
            ligacao(central, aparelhos, esperando.count, contar(esperando.count, "para fazer", "para fazer"),
                    "nada para fazer"),
            ligacao(aparelhos, central, rodando.count, contar(rodando.count, "resposta enviada", "respostas enviadas"),
                    "nenhuma resposta agora"),
            ligacao(central, claude, rodandoDe(claude), "respondendo", "sem resposta agora"),
            ligacao(central, codex, rodandoDe(codex), "respondendo", "sem resposta agora"),
        ]
    }

    /// "qwen2.5-coder:14b" vira "qwen2.5-coder"; os remotos ficam com o nome da central.
    static func nomeCurto(_ m: ModeloAuxiliar) -> String {
        guard m.local, let i = m.id.firstIndex(of: ":") else { return m.local ? m.id : m.nome }
        return String(m.id[..<i])
    }

    static func detalhe(_ m: ModeloAuxiliar, doNoah: Bool, semDados: Bool) -> String {
        if semDados { return "sem dados" }
        if m.disponivel == false { return "indisponível" }
        if !m.local {
            if m.provedor.contains("NVIDIA") { return "NVIDIA grátis" }
            if m.provedor.contains("Copilot") { return "GitHub CLI" }
            return m.provedor
        }
        var partes: [String] = []
        if let i = m.id.firstIndex(of: ":") { partes.append(String(m.id[m.id.index(after: i)...])) }
        partes.append(m.carregado ? "na memória" : doNoah ? "do Noah" : "local")
        return partes.joined(separator: " · ")
    }

    /// "há 5 min", "há 3 h", "há 2 dias"; sem data, só "nota".
    static func idade(_ quando: Double?, agora: Double) -> String {
        guard let quando else { return "nota" }
        let s = max(0, agora - quando)
        if s < 3600 { return "há \(max(1, Int(s / 60))) min" }
        if s < 86_400 { return "há \(Int(s / 3600)) h" }
        let d = Int(s / 86_400)
        return d == 1 ? "há 1 dia" : "há \(d) dias"
    }

    static func contar(_ n: Int, _ singular: String, _ plural: String) -> String {
        "\(n) \(n == 1 ? singular : plural)"
    }
}
