import Foundation

/// Feed "Ao vivo" do painel lateral: o que mudou entre duas leituras da
/// central. Só compara listas que o app já tem; não lê nada a mais.
public struct Evento: Identifiable, Hashable, Sendable {
    public enum Tipo: String, Sendable { case nova, resolvida, respondendo, respondeu, falhou }

    public var id: String
    public var quando: Date
    public var tipo: Tipo
    public var fonte: String
    public var titulo: String

    public init(quando: Date, tipo: Tipo, fonte: String, titulo: String, chave: String) {
        self.id = "\(quando.timeIntervalSince1970)-\(tipo.rawValue)-\(chave)"
        self.quando = quando
        self.tipo = tipo
        self.fonte = fonte
        self.titulo = titulo
    }

    public var texto: String {
        let nome = Fonte.nome(fonte)
        switch tipo {
        case .nova: return fonte == "noah" ? "Noah gerou: \(titulo)" : "\(nome) espera você: \(titulo)"
        case .resolvida: return "Saiu da lista: \(titulo)"
        case .respondendo: return "\(nome) está respondendo: \(titulo)"
        case .respondeu: return "\(nome) respondeu: \(titulo)"
        case .falhou: return "\(nome) falhou: \(titulo)"
        }
    }
}

public enum Atividade {
    /// Quantos eventos o painel guarda.
    public static let limite = 30

    /// Eventos entre a leitura anterior e a atual, do mais novo para o mais
    /// antigo. `anteriores == nil` é a primeira leitura: nada vira evento, para
    /// não encher o painel com o que já estava lá.
    public static func eventos(anteriores: [Pendencia]?, atuais: [Pendencia],
                               jobsAnteriores: [Job], jobsAtuais: [Job],
                               agora: Date = Date()) -> [Evento] {
        guard let anteriores else { return [] }
        var saida: [Evento] = []
        let antes = Dictionary(anteriores.map { ($0.chave, $0) }, uniquingKeysWith: { a, _ in a })
        let depois = Set(atuais.map(\.chave))
        for p in atuais where antes[p.chave] == nil || antes[p.chave]?.versao != p.versao {
            if p.respondendo { continue }
            saida.append(Evento(quando: agora, tipo: .nova, fonte: p.fonte, titulo: p.tarefa, chave: p.chave))
        }
        let respondendoAgora = Set(jobsAtuais.filter(\.rodando).map(\.chave))
        for p in anteriores where !depois.contains(p.chave) && !respondendoAgora.contains(p.chave) {
            saida.append(Evento(quando: agora, tipo: .resolvida, fonte: p.fonte, titulo: p.tarefa, chave: p.chave))
        }
        let jobsAntes = Dictionary(jobsAnteriores.map { ($0.id, $0.estado) }, uniquingKeysWith: { a, _ in a })
        for j in jobsAtuais where jobsAntes[j.id] != j.estado {
            let tipo: Evento.Tipo
            switch j.estado {
            case "rodando": tipo = .respondendo
            case "concluido": tipo = .respondeu
            case "erro": tipo = .falhou
            default: continue
            }
            saida.append(Evento(quando: agora, tipo: tipo, fonte: j.fonte, titulo: j.titulo, chave: j.chave))
        }
        return saida
    }

    /// Junta os novos no topo e corta no limite.
    public static func juntar(_ novos: [Evento], em feed: [Evento]) -> [Evento] {
        Array((novos + feed).prefix(limite))
    }
}
