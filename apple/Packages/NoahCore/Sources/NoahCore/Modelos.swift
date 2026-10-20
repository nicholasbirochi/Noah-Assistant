import Foundation

/// O que a central (src/central/servidor.py) devolve. Os nomes dos campos
/// seguem o JSON; os de Swift só trocam o que colide com `Identifiable`.

public enum Fonte {
    /// Mesmos rótulos do PWA (src/central/pwa/app.js).
    public static func nome(_ fonte: String) -> String {
        ["claude": "Claude", "codex": "Codex", "noah": "Noah"][fonte] ?? fonte
    }
}

public struct Pendencia: Codable, Identifiable, Hashable, Sendable {
    public var fonte: String
    /// Id da conversa na fonte (o `id` do JSON).
    public var ident: String
    public var titulo: String
    public var projeto: String
    /// ISO 8601; vazio para o Noah.
    public var quando: String
    public var mensagem: String
    public var versao: String
    public var podeResponder: Bool
    /// "fonte:id": a mesma em todos os aparelhos, por isso vira o id do aviso.
    public var chave: String
    public var respondendo: Bool

    public var id: String { chave }

    enum CodingKeys: String, CodingKey {
        case fonte, ident = "id", titulo, projeto, quando, mensagem, versao
        case podeResponder = "pode_responder", chave, respondendo
    }

    public init(fonte: String, ident: String, titulo: String, projeto: String = "", quando: String = "",
                mensagem: String = "", versao: String = "", podeResponder: Bool = true,
                chave: String? = nil, respondendo: Bool = false) {
        self.fonte = fonte
        self.ident = ident
        self.titulo = titulo
        self.projeto = projeto
        self.quando = quando
        self.mensagem = mensagem
        self.versao = versao
        self.podeResponder = podeResponder
        self.chave = chave ?? "\(fonte):\(ident)"
        self.respondendo = respondendo
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let fonte = try c.decode(String.self, forKey: .fonte)
        let ident = try c.decode(String.self, forKey: .ident)
        self.init(
            fonte: fonte, ident: ident,
            titulo: try c.decodeIfPresent(String.self, forKey: .titulo) ?? "",
            projeto: try c.decodeIfPresent(String.self, forKey: .projeto) ?? "",
            quando: try c.decodeIfPresent(String.self, forKey: .quando) ?? "",
            mensagem: try c.decodeIfPresent(String.self, forKey: .mensagem) ?? "",
            versao: try c.decodeIfPresent(String.self, forKey: .versao) ?? "",
            podeResponder: try c.decodeIfPresent(Bool.self, forKey: .podeResponder) ?? true,
            chave: try c.decodeIfPresent(String.self, forKey: .chave),
            respondendo: try c.decodeIfPresent(Bool.self, forKey: .respondendo) ?? false)
    }
}

/// Resposta em andamento ou terminada (Job.para_json em src/central/resposta.py).
public struct Job: Codable, Identifiable, Hashable, Sendable {
    public var id: String
    public var chave: String
    public var titulo: String
    public var fonte: String
    /// rodando | concluido | erro
    public var estado: String
    public var detalhe: String?
    public var inicio: Double
    public var fim: Double?

    public init(id: String, chave: String, titulo: String, fonte: String, estado: String,
                detalhe: String? = nil, inicio: Double, fim: Double? = nil) {
        self.id = id
        self.chave = chave
        self.titulo = titulo
        self.fonte = fonte
        self.estado = estado
        self.detalhe = detalhe
        self.inicio = inicio
        self.fim = fim
    }

    public var rodando: Bool { estado == "rodando" }

    /// Mesmos rótulos do PWA.
    public var rotuloEstado: String {
        ["rodando": "respondendo…", "concluido": "respondeu", "erro": "falhou"][estado] ?? estado
    }
}

public struct RespostaPendencias: Codable, Sendable, Equatable {
    public var itens: [Pendencia]
    public var respondendo: [Job]
    public var falhas: [String]
    public var geradoEm: Double?

    enum CodingKeys: String, CodingKey {
        case itens, respondendo, falhas, geradoEm = "gerado_em"
    }

    public init(itens: [Pendencia], respondendo: [Job] = [], falhas: [String] = [], geradoEm: Double? = nil) {
        self.itens = itens
        self.respondendo = respondendo
        self.falhas = falhas
        self.geradoEm = geradoEm
    }
}

public struct ItemPresenca: Codable, Hashable, Sendable {
    public var source: String
    public var why: String
    public var action: String

    public init(source: String, why: String, action: String) {
        self.source = source
        self.why = why
        self.action = action
    }
}

public struct EstadoPresenca: Codable, Sendable, Equatable {
    public var ligada: Bool
    public var variavel: String
    public var itens: [ItemPresenca]
    public var falhas: [String]

    public init(ligada: Bool, variavel: String = "NOAH_PRESENCE_ENABLED", itens: [ItemPresenca] = [], falhas: [String] = []) {
        self.ligada = ligada
        self.variavel = variavel
        self.itens = itens
        self.falhas = falhas
    }
}

/// Sinal ao vivo do Cérebro (`GET /central/api/cerebro`): quem consultou,
/// registrou ou delegou aos auxiliares na janela recente. A central conta só
/// chamadas de ferramenta que executam a CLI do Cérebro; uma fonte que falhou
/// vem em `falhas`, zerada.
public struct SinalCerebro: Codable, Sendable, Equatable {
    public struct Uso: Codable, Sendable, Equatable {
        public var consultas: Int
        public var registros: Int
        public var ultima: Double?
        /// Quantas vezes cada pasta do cofre ("00"…"07") apareceu nas consultas
        /// e registros da janela. nil quando a central é anterior a essa contagem.
        public var partes: [String: Int]?

        public init(consultas: Int = 0, registros: Int = 0, ultima: Double? = nil, partes: [String: Int]? = nil) {
            self.consultas = consultas
            self.registros = registros
            self.ultima = ultima
            self.partes = partes
        }
    }

    public struct Delegacao: Codable, Sendable, Equatable {
        public var delegacoes: Int
        public var ultima: Double?

        public init(delegacoes: Int = 0, ultima: Double? = nil) {
            self.delegacoes = delegacoes
            self.ultima = ultima
        }
    }

    public var janela: Int
    /// Por fonte: "claude", "codex", "noah".
    public var cerebro: [String: Uso]
    /// Por fonte: "claude", "codex".
    public var auxiliares: [String: Delegacao]
    /// Nomes das fontes que a central não conseguiu ler ("Claude Code", "Codex", "Noah").
    public var falhas: [String]

    enum CodingKeys: String, CodingKey {
        case janela = "janela_s", cerebro, auxiliares, falhas
    }

    public init(janela: Int = 600, cerebro: [String: Uso] = [:], auxiliares: [String: Delegacao] = [:],
                falhas: [String] = []) {
        self.janela = janela
        self.cerebro = cerebro
        self.auxiliares = auxiliares
        self.falhas = falhas
    }
}

public struct RespostaJob: Codable, Sendable {
    public var job: Job
}

// MARK: - Tarefa e detalhe

extension Pendencia {
    /// Separador que a central põe entre o porquê e o que fazer nos itens do
    /// Noah (pendencias_noah em src/central/fontes.py).
    static let separadorAcao = "\n\n→ "

    /// Gerada sozinha pelo Noah (Presença), não por uma conversa esperando você.
    public var automatica: Bool { fonte == "noah" }

    /// O que fazer, numa linha, para a tela inicial: a ação sugerida nos itens
    /// do Noah, o título da conversa nos demais.
    public var tarefa: String {
        guard automatica, let acao else { return titulo }
        return acao
    }

    /// Ação sugerida pelo Noah, quando a mensagem traz uma.
    public var acao: String? {
        guard let r = mensagem.range(of: Self.separadorAcao) else { return nil }
        let acao = mensagem[r.upperBound...].trimmingCharacters(in: .whitespacesAndNewlines)
        return acao.isEmpty ? nil : acao
    }

    /// O texto completo sem a ação: o porquê (Noah) ou a última mensagem do agente.
    public var motivo: String {
        guard let r = mensagem.range(of: Self.separadorAcao) else { return mensagem }
        return String(mensagem[..<r.lowerBound]).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// De onde veio, numa frase, para o detalhe.
    public var origem: String {
        if automatica { return "Gerada automaticamente pelo Noah a partir de \(titulo)." }
        return "\(Fonte.nome(fonte)) terminou e está esperando sua resposta."
    }

    /// Conversas esperando você primeiro; depois as geradas pelo Noah. Mantém a
    /// ordem da central dentro de cada grupo.
    public static func separar(_ itens: [Pendencia]) -> (conversas: [Pendencia], automaticas: [Pendencia]) {
        (itens.filter { !$0.automatica }, itens.filter(\.automatica))
    }
}
