import Foundation
import XCTest
@testable import NoahCore

final class SincroniaTests: XCTestCase {
    func p(_ id: String, _ versao: String, respondendo: Bool = false) -> Pendencia {
        Pendencia(fonte: "claude", ident: id, titulo: id, versao: versao, respondendo: respondendo)
    }

    func testPrimeiraLeituraNaoDisparaRajada() {
        let (m, estado) = Sincronia.comparar(Avisados(), com: [p("a", "1"), p("b", "1")])
        XCTAssertEqual(m.novas, [])
        XCTAssertTrue(estado.iniciado)
        XCTAssertEqual(estado.versoes, ["claude:a": "1", "claude:b": "1"])
    }

    func testAvisaSoONovoEOQueMudouDeVersao() {
        let antes = Avisados(versoes: ["claude:a": "1", "claude:b": "1"], iniciado: true)
        let (m, _) = Sincronia.comparar(antes, com: [p("a", "1"), p("b", "2"), p("c", "1")])
        XCTAssertEqual(m.novas.map(\.chave), ["claude:b", "claude:c"])
        XCTAssertEqual(m.sumidas, [])
    }

    func testRespondidoOuDispensadoNoOutroAparelhoSomeDaqui() {
        let antes = Avisados(versoes: ["claude:a": "1", "claude:b": "1"], iniciado: true)
        let (m, estado) = Sincronia.comparar(antes, com: [p("b", "1")])
        XCTAssertEqual(m.sumidas, ["claude:a"])
        XCTAssertEqual(m.novas, [])
        XCTAssertEqual(estado.versoes, ["claude:b": "1"])
    }

    func testQuemJaEstaRespondendoNaoViraAviso() {
        let antes = Avisados(versoes: [:], iniciado: true)
        let (m, estado) = Sincronia.comparar(antes, com: [p("a", "1", respondendo: true)])
        XCTAssertEqual(m.novas, [])
        // Mas fica registrado: se terminar e voltar com a mesma versão, não avisa de novo.
        XCTAssertEqual(estado.versoes["claude:a"], "1")
    }

    func testEstadoSobreviveACodificacao() throws {
        let e = Avisados(versoes: ["claude:a": "1"], iniciado: true)
        XCTAssertEqual(try JSONDecoder().decode(Avisados.self, from: JSONEncoder().encode(e)), e)
    }

    func testIntervaloEJobsVisiveis() {
        let rodando = Job(id: "1", chave: "claude:a", titulo: "a", fonte: "claude", estado: "rodando", inicio: 0)
        let recente = Job(id: "2", chave: "claude:b", titulo: "b", fonte: "claude", estado: "concluido", inicio: 0, fim: 1000)
        let velho = Job(id: "3", chave: "claude:c", titulo: "c", fonte: "claude", estado: "erro", inicio: 0, fim: 100)
        XCTAssertEqual(Sincronia.proximoIntervalo([rodando, recente]), 4)
        XCTAssertEqual(Sincronia.proximoIntervalo([recente]), 20)
        XCTAssertEqual(Sincronia.proximoIntervalo([recente], vendoFluxo: true), 10)
        XCTAssertEqual(Sincronia.proximoIntervalo([rodando], vendoFluxo: true), 4)
        XCTAssertEqual(Sincronia.proximoIntervalo([recente], aoVivo: true), 2)
        XCTAssertEqual(Sincronia.proximoIntervalo([rodando], aoVivo: true), 2)
        XCTAssertEqual(Sincronia.jobsVisiveis([rodando, recente, velho], agora: 1300).map(\.id), ["1", "2"])
        XCTAssertEqual(recente.rotuloEstado, "respondeu")
        XCTAssertEqual(velho.rotuloEstado, "falhou")
    }

    func testHaQuantoNaEscalaDoPwa() {
        let base = ISO8601DateFormatter().date(from: "2026-10-19T12:00:00Z")!
        func ha(_ s: Double) -> String {
            Sincronia.haQuanto(ISO8601DateFormatter().string(from: base.addingTimeInterval(-s)), agora: base)
        }
        XCTAssertEqual(ha(10), "agora")
        XCTAssertEqual(ha(5 * 60), "há 5 min")
        XCTAssertEqual(ha(3 * 3600), "há 3 h")
        XCTAssertEqual(ha(30 * 3600), "ontem")
        XCTAssertEqual(ha(4 * 86400), "há 4 dias")
        XCTAssertEqual(Sincronia.haQuanto("", agora: base), "")
        XCTAssertEqual(Sincronia.haQuanto("lixo", agora: base), "")
        // A aba Central passa a data direto (o feed vem em segundos Unix).
        XCTAssertEqual(Sincronia.haQuanto(base.addingTimeInterval(-90), agora: base), "há 1 min")
    }

    func testHaQuantoSemFusoEhHoraLocal() {
        var c = DateComponents()
        (c.year, c.month, c.day, c.hour, c.minute) = (2026, 10, 19, 10, 0)
        let agora = Calendar.current.date(from: c)!.addingTimeInterval(120)
        XCTAssertEqual(Sincronia.haQuanto("2026-10-19T10:00", agora: agora), "há 2 min")
        XCTAssertEqual(Sincronia.haQuanto("2026-10-19T10:00:00.123456", agora: agora), "há 1 min")
    }

    func testNomesDasFontes() {
        XCTAssertEqual(Fonte.nome("codex"), "Codex")
        XCTAssertEqual(Fonte.nome("outra"), "outra")
    }
}
