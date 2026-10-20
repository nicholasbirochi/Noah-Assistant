import Foundation

/// Sincronização entre iPhone e Mac. Não há servidor na nuvem: a central no Mac
/// é a única fonte de verdade (lista, respostas em andamento, dispensadas). Cada
/// aparelho só lê dela, então responder ou dispensar num aparelho some do outro
/// na próxima leitura. O que cada aparelho guarda é só "o que já avisei", para
/// não repetir a notificação.
public struct Avisados: Codable, Equatable, Sendable {
    /// chave -> versão já avisada (ou já vista).
    public var versoes: [String: String]
    /// Falso até a primeira leitura: o que já estava pendente ao instalar não vira
    /// uma rajada de notificações (aparece na lista do app).
    public var iniciado: Bool

    public init(versoes: [String: String] = [:], iniciado: Bool = false) {
        self.versoes = versoes
        self.iniciado = iniciado
    }
}

public struct MudancaAvisos: Equatable, Sendable {
    /// Pendências novas, ou que mudaram de versão (o agente perguntou de novo): avisar.
    public var novas: [Pendencia]
    /// Chaves que saíram da lista (respondidas ou dispensadas em qualquer aparelho):
    /// tirar o aviso da central de notificações.
    public var sumidas: [String]

    public init(novas: [Pendencia] = [], sumidas: [String] = []) {
        self.novas = novas
        self.sumidas = sumidas
    }
}

public enum Sincronia {
    /// Intervalos do PWA: 20 s parado, 4 s enquanto alguma resposta roda.
    public static let intervalo: TimeInterval = 20
    public static let intervaloRespondendo: TimeInterval = 4
    /// Com a aba Fluxo aberta o mapa precisa do sinal do Cérebro mais fresco.
    public static let intervaloFluxo: TimeInterval = 10
    /// Respostas terminadas ficam visíveis por 10 min.
    public static let jobVisivel: TimeInterval = 600

    public static func proximoIntervalo(_ jobs: [Job], vendoFluxo: Bool = false) -> TimeInterval {
        if jobs.contains(where: \.rodando) { return intervaloRespondendo }
        return vendoFluxo ? intervaloFluxo : intervalo
    }

    public static func jobsVisiveis(_ jobs: [Job], agora: Double = Date().timeIntervalSince1970) -> [Job] {
        jobs.filter { $0.rodando || ($0.fim.map { agora - $0 < jobVisivel } ?? false) }
    }

    public static func comparar(_ anterior: Avisados, com atuais: [Pendencia]) -> (MudancaAvisos, Avisados) {
        let novoEstado = Avisados(versoes: Dictionary(atuais.map { ($0.chave, $0.versao) }, uniquingKeysWith: { a, _ in a }),
                                  iniciado: true)
        let presentes = Set(novoEstado.versoes.keys)
        let sumidas = anterior.versoes.keys.filter { !presentes.contains($0) }.sorted()
        guard anterior.iniciado else { return (MudancaAvisos(sumidas: sumidas), novoEstado) }
        // Quem está respondendo agora já foi atendido em algum aparelho.
        let novas = atuais.filter { !$0.respondendo && anterior.versoes[$0.chave] != $0.versao }
        return (MudancaAvisos(novas: novas, sumidas: sumidas), novoEstado)
    }

    /// Mesma escala do PWA: "agora", "há 5 min", "há 3 h", "ontem", "há 4 dias".
    public static func haQuanto(_ iso: String, agora: Date = Date()) -> String {
        guard !iso.isEmpty, let data = lerData(iso) else { return "" }
        let s = max(0, agora.timeIntervalSince(data))
        if s < 60 { return "agora" }
        if s < 3600 { return "há \(Int(s / 60)) min" }
        if s < 86400 { return "há \(Int(s / 3600)) h" }
        let d = Int(s / 86400)
        return d == 1 ? "ontem" : "há \(d) dias"
    }

    static func lerData(_ iso: String) -> Date? {
        let completo = ISO8601DateFormatter()
        completo.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = completo.date(from: iso) { return d }
        completo.formatOptions = [.withInternetDateTime]
        if let d = completo.date(from: iso) { return d }
        // Sem fuso ("2026-10-19T10:00" ou com segundos), como o JS: hora local.
        let local = DateFormatter()
        local.locale = Locale(identifier: "en_US_POSIX")
        local.timeZone = .current
        for formato in ["yyyy-MM-dd'T'HH:mm:ss.SSSSSS", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm"] {
            local.dateFormat = formato
            if let d = local.date(from: iso) { return d }
        }
        return nil
    }
}

/// Resposta de um toque, para aceitar pelo aviso sem abrir o app.
public enum RespostaRapida {
    public static let aceitar = "Pode seguir."
}
