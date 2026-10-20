import XCTest
@testable import NoahCore

final class AtividadeTests: XCTestCase {
    let agora = Date(timeIntervalSince1970: 1000)
    func p(_ id: String, _ versao: String = "1", fonte: String = "claude") -> Pendencia {
        Pendencia(fonte: fonte, ident: id, titulo: id, versao: versao)
    }
    func job(_ id: String, _ estado: String) -> Job {
        Job(id: id, chave: "claude:\(id)", titulo: id, fonte: "claude", estado: estado, inicio: 0)
    }

    func testPrimeiraLeituraNaoGeraEventos() {
        XCTAssertEqual(Atividade.eventos(anteriores: nil, atuais: [p("a")], jobsAnteriores: [], jobsAtuais: []), [])
    }

    func testNovaMudouESumiu() {
        let ev = Atividade.eventos(anteriores: [p("a"), p("b")], atuais: [p("b", "2"), p("c", fonte: "noah")],
                                   jobsAnteriores: [], jobsAtuais: [], agora: agora)
        XCTAssertEqual(ev.map(\.tipo), [.nova, .nova, .resolvida])
        XCTAssertEqual(ev.map(\.texto), ["Claude espera você: b", "Noah gerou: c", "Saiu da lista: a"])
    }

    func testRespostaEmAndamentoNaoContaComoResolvida() {
        let ev = Atividade.eventos(anteriores: [p("a")], atuais: [], jobsAnteriores: [],
                                   jobsAtuais: [job("a", "rodando")], agora: agora)
        XCTAssertEqual(ev.map(\.tipo), [.respondendo])
    }

    func testJobQueTerminaOuFalhaViraEvento() {
        let ev = Atividade.eventos(anteriores: [], atuais: [],
                                   jobsAnteriores: [job("a", "rodando"), job("b", "rodando")],
                                   jobsAtuais: [job("a", "concluido"), job("b", "erro")], agora: agora)
        XCTAssertEqual(ev.map(\.texto), ["Claude respondeu: a", "Claude falhou: b"])
    }

    func testJuntarCortaNoLimite() {
        let muitos = (0..<40).map { Evento(quando: agora, tipo: .nova, fonte: "claude", titulo: "\($0)", chave: "\($0)") }
        let feed = Atividade.juntar(Array(muitos.prefix(5)), em: Array(muitos.suffix(35)))
        XCTAssertEqual(feed.count, Atividade.limite)
        XCTAssertEqual(feed.first?.titulo, "0")
    }
}
