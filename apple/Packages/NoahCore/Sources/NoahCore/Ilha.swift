import Foundation

/// O que a ilha dinâmica, a tela bloqueada e os widgets mostram: um resumo curto
/// da central, no mesmo código de cores do protótipo `noah-coucou.html`
/// (azul trabalhando, âmbar esperando você, verde tudo pronto).
public enum EstadoIlha: String, Codable, Hashable, Sendable {
    /// Nada pendente nem rodando: a Live Activity encerra.
    case quieto
    /// Algum agente está respondendo (azul).
    case trabalhando
    /// Pendência esperando você (âmbar, com "!").
    case esperando
    /// Respostas terminaram há pouco e nada espera você (verde, olhos ^^).
    case pronto

    public var titulo: String {
        switch self {
        case .quieto: "Tudo calmo"
        case .trabalhando: "Trabalhando"
        case .esperando: "Esperando você"
        case .pronto: "Tudo pronto"
        }
    }
}

/// Resumo gravado pelo app e lido pela extensão (widgets e Live Activity).
/// Também é o `ContentState` da Live Activity, então precisa ser pequeno.
public struct ResumoIlha: Codable, Hashable, Sendable {
    public var estado: EstadoIlha
    /// Pendências que ainda esperam você: perguntas, sem quem já está respondendo.
    public var esperando: Int
    /// Respostas rodando agora.
    public var rodando: Int
    /// Respostas prontas: na lista sem pergunta, ou que terminaram nos últimos 10 min.
    public var prontas: Int
    /// Linha principal: a pendência mais recente, ou o que está rodando.
    public var linha: String
    /// Agente da linha principal ("Claude", "Codex"…), vazio se não houver.
    public var agente: String
    /// Chave da pendência da linha principal, para abrir o detalhe ao tocar.
    public var chave: String?
    public var atualizadoEm: Date

    public init(estado: EstadoIlha, esperando: Int = 0, rodando: Int = 0, prontas: Int = 0,
                linha: String = "", agente: String = "", chave: String? = nil,
                atualizadoEm: Date = Date()) {
        self.estado = estado
        self.esperando = esperando
        self.rodando = rodando
        self.prontas = prontas
        self.linha = linha
        self.agente = agente
        self.chave = chave
        self.atualizadoEm = atualizadoEm
    }

    public static let vazio = ResumoIlha(estado: .quieto, linha: "Nada esperando você",
                                         atualizadoEm: Date(timeIntervalSince1970: 0))

    /// Texto curto para a ilha compacta e o widget em linha da tela bloqueada.
    public var curto: String {
        switch estado {
        case .esperando: esperando == 1 ? "1 esperando" : "\(esperando) esperando"
        case .trabalhando: rodando <= 1 ? "Trabalhando" : "\(rodando) rodando"
        case .pronto: "Tudo pronto"
        case .quieto: "Tudo calmo"
        }
    }

    /// Mesmo conteúdo, ignorando a hora: evita recarregar widgets e a ilha à toa.
    public func mesmoConteudo(_ outro: ResumoIlha) -> Bool {
        var a = self, b = outro
        a.atualizadoEm = .distantPast
        b.atualizadoEm = .distantPast
        return a == b
    }
}

public enum Ilha {
    /// App Group que o app e a extensão de widgets compartilham.
    public static let grupo = "group.com.nicholasbirochi.noah"
    static let chaveResumo = "resumoIlha"

    /// Esperando você vence trabalhando, que vence pronto: o que pede ação aparece primeiro.
    /// Só pergunta espera você; resposta pronta (sem pergunta) conta como pronta.
    public static func resumo(itens: [Pendencia], jobs: [Job],
                              agora: Double = Date().timeIntervalSince1970) -> ResumoIlha {
        let abertas = itens.filter { !$0.respondendo && $0.pergunta }
        let relatorios = itens.filter { !$0.respondendo && !$0.pergunta }
        let visiveis = Sincronia.jobsVisiveis(jobs, agora: agora)
        let rodando = visiveis.filter(\.rodando)
        // O job que terminou e virou resposta pronta na lista conta uma vez só.
        let chavesRelatorios = Set(relatorios.map(\.chave))
        let jobsProntos = visiveis.filter { $0.estado == "concluido" && !chavesRelatorios.contains($0.chave) }
        let nProntas = relatorios.count + jobsProntos.count
        // Quem está respondendo pela lista também conta como trabalho, mesmo antes
        // de o job aparecer na resposta da central.
        let respondendo = itens.filter(\.respondendo)
        let nRodando = max(rodando.count, respondendo.count)
        let data = Date(timeIntervalSince1970: agora)

        if let p = abertas.first {
            return ResumoIlha(estado: .esperando, esperando: abertas.count, rodando: nRodando,
                              prontas: nProntas, linha: p.tarefa, agente: Fonte.nome(p.fonte),
                              chave: p.chave, atualizadoEm: data)
        }
        if nRodando > 0 {
            let linha = rodando.first?.titulo ?? respondendo.first?.tarefa ?? "Respondendo"
            let fonte = rodando.first?.fonte ?? respondendo.first?.fonte ?? ""
            return ResumoIlha(estado: .trabalhando, rodando: nRodando, prontas: nProntas,
                              linha: linha, agente: fonte.isEmpty ? "" : Fonte.nome(fonte),
                              chave: rodando.first?.chave ?? respondendo.first?.chave, atualizadoEm: data)
        }
        if let p = relatorios.first {
            return ResumoIlha(estado: .pronto, prontas: nProntas, linha: p.tarefa,
                              agente: Fonte.nome(p.fonte), chave: p.chave, atualizadoEm: data)
        }
        if let j = jobsProntos.first {
            return ResumoIlha(estado: .pronto, prontas: nProntas, linha: j.titulo,
                              agente: Fonte.nome(j.fonte), chave: j.chave, atualizadoEm: data)
        }
        return ResumoIlha(estado: .quieto, linha: "Nada esperando você", atualizadoEm: data)
    }

    public static func gravar(_ r: ResumoIlha, em defaults: UserDefaults) {
        if let dados = try? JSONEncoder().encode(r) { defaults.set(dados, forKey: chaveResumo) }
    }

    public static func ler(de defaults: UserDefaults) -> ResumoIlha? {
        guard let dados = defaults.data(forKey: chaveResumo) else { return nil }
        return try? JSONDecoder().decode(ResumoIlha.self, from: dados)
    }
}

/// Links `noah://` que widgets e ilha usam para abrir o app num lugar certo.
public enum Atalho {
    public static let esquema = "noah"

    public static func pendencia(_ chave: String) -> URL {
        var c = URLComponents()
        c.scheme = esquema
        c.host = "pendencia"
        c.queryItems = [URLQueryItem(name: "chave", value: chave)]
        return c.url!
    }

    public static let lista = URL(string: "noah://pendencias")!
    public static let fluxo = URL(string: "noah://fluxo")!

    public enum Destino: Equatable, Sendable {
        case lista, fluxo
        case pendencia(String)
    }

    public static func destino(_ url: URL) -> Destino? {
        guard url.scheme == esquema else { return nil }
        switch url.host {
        case "pendencias": return .lista
        case "fluxo": return .fluxo
        case "pendencia":
            let chave = URLComponents(url: url, resolvingAgainstBaseURL: false)?
                .queryItems?.first { $0.name == "chave" }?.value
            return chave.map { $0.isEmpty ? .lista : .pendencia($0) } ?? .lista
        default: return nil
        }
    }

    /// Para o caminho de um atalho, o resumo leva à pendência ou à lista.
    public static func para(_ r: ResumoIlha) -> URL {
        switch r.estado {
        case .esperando: r.chave.map(pendencia) ?? lista
        case .trabalhando, .pronto: fluxo
        case .quieto: lista
        }
    }
}

extension Fonte {
    /// App do Mac de cada agente, para o botão "Abrir no app" da barra de menus.
    /// O Codex vem dentro do app do ChatGPT (mesmo identificador).
    public static func app(_ fonte: String) -> String? {
        ["claude": "com.anthropic.claudefordesktop", "codex": "com.openai.codex"][fonte]
    }
}
