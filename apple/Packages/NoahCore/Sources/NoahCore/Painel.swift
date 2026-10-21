import Foundation

/// `GET /central/api/atividade` (src/central/atividade.py + servidor.py): os
/// modelos auxiliares, as pastas do Cérebro, o feed de quem falou com quem e o
/// estado do Noah. Alimenta a aba Central e as ligações do Fluxo.
public struct PainelCentral: Decodable, Sendable, Equatable {
    public var ollama: Bool
    public var modelos: [ModeloAuxiliar]
    public var cerebro: Cerebro
    public var eventos: [EventoCentral]
    public var falhas: [String]
    public var noah: EstadoNoah?
    public var geradoEm: Double?
    /// Conversas Claude ativas com sidechains verificados; payload legado pode omitir.
    public var conversasClaude: [ConversaClaudeAtiva]

    public struct Cerebro: Decodable, Sendable, Equatable {
        public var pastas: [PastaCerebro]
        public init(pastas: [PastaCerebro]) { self.pastas = pastas }
    }

    enum CodingKeys: String, CodingKey {
        case ollama, modelos, cerebro, eventos, falhas, noah
        case conversasClaude = "conversas_claude"
        case geradoEm = "gerado_em"
    }

    public init(ollama: Bool = true, modelos: [ModeloAuxiliar] = [], pastas: [PastaCerebro] = [],
                eventos: [EventoCentral] = [], falhas: [String] = [], noah: EstadoNoah? = nil,
                geradoEm: Double? = nil, conversasClaude: [ConversaClaudeAtiva] = []) {
        self.ollama = ollama
        self.modelos = modelos
        self.cerebro = Cerebro(pastas: pastas)
        self.eventos = eventos
        self.falhas = falhas
        self.noah = noah
        self.geradoEm = geradoEm
        self.conversasClaude = conversasClaude
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ollama = try c.decodeIfPresent(Bool.self, forKey: .ollama) ?? false
        modelos = try c.decodeIfPresent([ModeloAuxiliar].self, forKey: .modelos) ?? []
        cerebro = (try? c.decode(Cerebro.self, forKey: .cerebro)) ?? Cerebro(pastas: [])
        eventos = try c.decodeIfPresent([EventoCentral].self, forKey: .eventos) ?? []
        falhas = try c.decodeIfPresent([String].self, forKey: .falhas) ?? []
        noah = try c.decodeIfPresent(EstadoNoah.self, forKey: .noah)
        geradoEm = try c.decodeIfPresent(Double.self, forKey: .geradoEm)
        conversasClaude = try c.decodeIfPresent([ConversaClaudeAtiva].self, forKey: .conversasClaude) ?? []
    }
}

public struct ConversaClaudeAtiva: Decodable, Sendable, Equatable, Identifiable {
    public var id: String
    public var quando: Double
    public var subagentes: [Subagente]

    public init(id: String, quando: Double, subagentes: [Subagente]) {
        self.id = id
        self.quando = quando
        self.subagentes = subagentes
    }
}

/// Um auxiliar: Qwen no Ollama local, Nemotron ou Copilot. `disponivel` nulo
/// quer dizer que não deu para saber (Ollama fora do ar).
public struct ModeloAuxiliar: Decodable, Sendable, Equatable, Identifiable {
    public var id: String
    public var nome: String
    public var provedor: String
    public var local: Bool
    public var disponivel: Bool?
    public var carregado: Bool
    public var rotas: [String]
    public var usos24h: Int
    public var ultimoUso: Double?

    enum CodingKeys: String, CodingKey {
        case id, nome, provedor, local, disponivel, carregado, rotas
        case usos24h = "usos_24h"
        case ultimoUso = "ultimo_uso"
    }

    public init(id: String, nome: String? = nil, provedor: String = "Ollama local", local: Bool = true,
                disponivel: Bool? = true, carregado: Bool = false, rotas: [String] = ["codigo"],
                usos24h: Int = 0, ultimoUso: Double? = nil) {
        self.id = id
        self.nome = nome ?? id
        self.provedor = provedor
        self.local = local
        self.disponivel = disponivel
        self.carregado = carregado
        self.rotas = rotas
        self.usos24h = usos24h
        self.ultimoUso = ultimoUso
    }
}

public struct PastaCerebro: Decodable, Sendable, Equatable, Identifiable {
    public var numero: String
    public var nome: String
    public var notas: Int
    public var atualizadaEm: Double?
    /// Subpastas e notas (só nome e data), para abrir a pasta no Fluxo.
    public var itens: [ItemCerebro]
    public var id: String { numero }

    enum CodingKeys: String, CodingKey {
        case numero, nome, notas, itens
        case atualizadaEm = "atualizada_em"
    }

    public init(numero: String, nome: String, notas: Int, atualizadaEm: Double? = nil, itens: [ItemCerebro] = []) {
        self.numero = numero
        self.nome = nome
        self.notas = notas
        self.atualizadaEm = atualizadaEm
        self.itens = itens
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        numero = try c.decode(String.self, forKey: .numero)
        nome = try c.decode(String.self, forKey: .nome)
        notas = try c.decode(Int.self, forKey: .notas)
        atualizadaEm = try c.decodeIfPresent(Double.self, forKey: .atualizadaEm)
        // Central antiga não manda a árvore.
        itens = try c.decodeIfPresent([ItemCerebro].self, forKey: .itens) ?? []
    }
}

/// Uma subpasta (com os itens dela) ou uma nota dentro de uma pasta do Cérebro.
public struct ItemCerebro: Decodable, Sendable, Equatable {
    public var nome: String
    public var pasta: Bool
    public var notas: Int
    public var atualizadaEm: Double?
    public var itens: [ItemCerebro]

    enum CodingKeys: String, CodingKey {
        case nome, tipo, notas, itens
        case atualizadaEm = "atualizada_em"
    }

    public static func nota(_ nome: String, atualizadaEm: Double? = nil) -> ItemCerebro {
        ItemCerebro(nome: nome, pasta: false, notas: 1, atualizadaEm: atualizadaEm, itens: [])
    }
    public static func pasta(_ nome: String, _ itens: [ItemCerebro], notas: Int? = nil) -> ItemCerebro {
        ItemCerebro(nome: nome, pasta: true, notas: notas ?? itens.reduce(0) { $0 + $1.notas },
                    atualizadaEm: itens.compactMap(\.atualizadaEm).max(), itens: itens)
    }

    init(nome: String, pasta: Bool, notas: Int, atualizadaEm: Double?, itens: [ItemCerebro]) {
        self.nome = nome
        self.pasta = pasta
        self.notas = notas
        self.atualizadaEm = atualizadaEm
        self.itens = itens
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        nome = try c.decode(String.self, forKey: .nome)
        pasta = try c.decodeIfPresent(String.self, forKey: .tipo) == "pasta"
        notas = try c.decodeIfPresent(Int.self, forKey: .notas) ?? (pasta ? 0 : 1)
        atualizadaEm = try c.decodeIfPresent(Double.self, forKey: .atualizadaEm)
        itens = try c.decodeIfPresent([ItemCerebro].self, forKey: .itens) ?? []
    }
}

/// Uma linha do feed. `tipo`: auxiliar, nota, resposta ou noah. `de`/`para`
/// são "agente" (Claude ou Codex, o registro não diz qual), "central", "noah",
/// "cerebro", "claude"/"codex" ou o id de um modelo.
public struct EventoCentral: Decodable, Sendable, Equatable, Identifiable, Hashable {
    public var quando: Double
    public var tipo: String
    public var de: String
    public var para: String
    public var texto: String
    public var id: String { "\(quando)|\(tipo)|\(de)>\(para)|\(texto)" }

    public init(quando: Double, tipo: String, de: String, para: String, texto: String) {
        self.quando = quando
        self.tipo = tipo
        self.de = de
        self.para = para
        self.texto = texto
    }
}

public struct EstadoNoah: Decodable, Sendable, Equatable {
    public var respondendoDesde: Double?
    public var turnos: [Turno]
    public var provedor: String
    public var modelo: String

    public struct Turno: Decodable, Sendable, Equatable {
        public var quando: Double
        public var ferramentas: [String]
        public init(quando: Double, ferramentas: [String]) {
            self.quando = quando
            self.ferramentas = ferramentas
        }
    }

    enum CodingKeys: String, CodingKey {
        case turnos, provedor, modelo
        case respondendoDesde = "respondendo_desde"
    }

    public init(respondendoDesde: Double? = nil, turnos: [Turno] = [], provedor: String = "ollama",
                modelo: String = "qwen2.5:7b") {
        self.respondendoDesde = respondendoDesde
        self.turnos = turnos
        self.provedor = provedor
        self.modelo = modelo
    }
}

/// `POST /central/api/conversa`: a resposta do Noah e as ferramentas que ele usou.
public struct RespostaConversa: Decodable, Sendable, Equatable {
    public var sessao: String
    public var resposta: String
    public var ferramentas: [String]
    public var provedor: String?
    public var modelo: String?
}
