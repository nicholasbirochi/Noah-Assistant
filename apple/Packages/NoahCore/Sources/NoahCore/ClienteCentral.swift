import Foundation

/// Erros que a tela mostra. A central responde `{"erro": "..."}`; o texto vem dela.
public enum ErroCentral: Error, Equatable, LocalizedError {
    case enderecoInvalido
    case semToken
    case naoAutorizado
    case textoVazio
    case textoLongo
    case servidor(status: Int, mensagem: String)
    case rede(String)

    public var errorDescription: String? {
        switch self {
        case .enderecoInvalido: "Endereço da central inválido. Confira nos Ajustes (ex.: http://192.168.0.10:8769)."
        case .semToken: "Falta o token da central nos Ajustes."
        case .naoAutorizado: "Token recusado pela central. Confira nos Ajustes."
        case .textoVazio: "Escreva a resposta antes de enviar."
        case .textoLongo: "Resposta acima de \(ClienteCentral.maxTexto) caracteres."
        case let .servidor(status, mensagem): "\(mensagem) (\(status))"
        case let .rede(detalhe): "Sem conexão com a central: \(detalhe)"
        }
    }
}

/// Fala com a API da central (src/central/servidor.py). Não manda `Origin`,
/// então a trava contra outros sites não se aplica; o token vai como Bearer.
public struct ClienteCentral: Sendable {
    /// MAX_TEXTO em src/central/resposta.py.
    public static let maxTexto = 4000

    public let base: URL
    public let token: String?
    private let sessao: URLSession

    public init(base: URL, token: String?, sessao: URLSession = .shared) {
        self.base = base
        self.token = token?.isEmpty == true ? nil : token
        self.sessao = sessao
    }

    /// Aceita "192.168.0.10:8769", "http://192.168.0.10:8769" ou com barra no fim.
    public static func endereco(_ texto: String) -> URL? {
        var t = texto.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return nil }
        if !t.contains("://") { t = "http://" + t }
        while t.hasSuffix("/") { t.removeLast() }
        guard let url = URL(string: t), let esquema = url.scheme?.lowercased(),
              ["http", "https"].contains(esquema), url.host?.isEmpty == false,
              url.path.isEmpty || url.path == "/" else { return nil }
        return url
    }

    public func pendencias() async throws -> RespostaPendencias {
        try await pedir("GET", "pendencias")
    }

    public func presenca() async throws -> EstadoPresenca {
        try await pedir("GET", "presenca")
    }

    /// Sinal ao vivo do Cérebro. `nil` quando a central é anterior à rota (404):
    /// o app mantém essas ligações como "sem sinal ao vivo".
    public func cerebro() async throws -> SinalCerebro? {
        do {
            return try await pedir("GET", "cerebro") as SinalCerebro
        } catch ErroCentral.servidor(status: 404, mensagem: _) {
            return nil
        }
    }

    @discardableResult
    public func responder(_ p: Pendencia, texto: String) async throws -> Job {
        let limpo = texto.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !limpo.isEmpty else { throw ErroCentral.textoVazio }
        guard limpo.count <= Self.maxTexto else { throw ErroCentral.textoLongo }
        let r: RespostaJob = try await pedir("POST", "responder", ["fonte": p.fonte, "id": p.ident, "texto": limpo])
        return r.job
    }

    public func dispensar(_ p: Pendencia) async throws {
        let _: [String: String] = try await pedir("POST", "dispensar", ["fonte": p.fonte, "id": p.ident])
    }

    /// Para os avisos: só a chave chega de volta, e a central só aceita o que lista agora.
    public static func partes(daChave chave: String) -> (fonte: String, ident: String)? {
        guard let i = chave.firstIndex(of: ":") else { return nil }
        let fonte = String(chave[..<i]), ident = String(chave[chave.index(after: i)...])
        return fonte.isEmpty || ident.isEmpty ? nil : (fonte, ident)
    }

    func requisicao(_ metodo: String, _ rota: String, _ corpo: [String: String]? = nil) throws -> URLRequest {
        var r = URLRequest(url: base.appendingPathComponent("central/api/\(rota)"))
        r.httpMethod = metodo
        r.timeoutInterval = 15
        r.cachePolicy = .reloadIgnoringLocalCacheData
        r.setValue("application/json", forHTTPHeaderField: "Accept")
        if let token { r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let corpo {
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
            r.httpBody = try JSONEncoder().encode(corpo)
        }
        return r
    }

    private func pedir<T: Decodable>(_ metodo: String, _ rota: String, _ corpo: [String: String]? = nil) async throws -> T {
        let r = try requisicao(metodo, rota, corpo)
        let dados: Data, resposta: URLResponse
        do {
            (dados, resposta) = try await sessao.data(for: r)
        } catch {
            throw ErroCentral.rede(error.localizedDescription)
        }
        let status = (resposta as? HTTPURLResponse)?.statusCode ?? 0
        if status == 401 { throw token == nil ? ErroCentral.semToken : ErroCentral.naoAutorizado }
        guard (200..<300).contains(status) else {
            let mensagem = (try? JSONDecoder().decode([String: String].self, from: dados))?["erro"]
            throw ErroCentral.servidor(status: status, mensagem: mensagem ?? "Erro da central")
        }
        do {
            return try JSONDecoder().decode(T.self, from: dados)
        } catch {
            throw ErroCentral.servidor(status: status, mensagem: "Resposta inesperada da central")
        }
    }
}
