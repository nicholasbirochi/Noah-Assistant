import XCTest
@testable import NoahCore

final class FluxoTests: XCTestCase {
    func p(_ id: String, fonte: String = "claude", respondendo: Bool = false) -> Pendencia {
        var item = Pendencia(fonte: fonte, ident: id, titulo: id)
        item.respondendo = respondendo
        return item
    }
    func job(_ id: String, _ estado: String, fonte: String = "claude") -> Job {
        Job(id: id, chave: "\(fonte):\(id)", titulo: id, fonte: fonte, estado: estado, inicio: 0)
    }
    func ligacao(_ lista: [Fluxo.Ligacao], _ de: Fluxo.No, _ para: Fluxo.No) -> Fluxo.Ligacao? {
        lista.first { $0.de == de && $0.para == para }
    }

    func testSemDadosNadaFicaVivo() {
        let lista = Fluxo.ligacoes(itens: [], jobs: [])
        XCTAssertEqual(lista.count, 11)
        XCTAssertFalse(lista.contains { $0.estado == .viva })
        XCTAssertEqual(ligacao(lista, .claude, .central)?.rotulo, "nada esperando")
        XCTAssertEqual(Set(lista.map(\.id)).count, lista.count)
    }

    func testPendenciaAcendeAgenteECentral() {
        let lista = Fluxo.ligacoes(itens: [p("a"), p("b", respondendo: true), p("c", fonte: "codex")], jobs: [])
        XCTAssertEqual(ligacao(lista, .claude, .central)?.estado, .viva)
        XCTAssertEqual(ligacao(lista, .claude, .central)?.quantidade, 1)
        XCTAssertEqual(ligacao(lista, .claude, .central)?.rotulo, "1 pendência")
        XCTAssertEqual(ligacao(lista, .codex, .central)?.estado, .viva)
        XCTAssertEqual(ligacao(lista, .central, .aparelhos)?.rotulo, "2 para fazer")
        XCTAssertEqual(ligacao(lista, .noah, .central)?.estado, .parada)
    }

    func testGeradaPeloNoahAcendeNoah() {
        let lista = Fluxo.ligacoes(itens: [p("x", fonte: "noah"), p("y", fonte: "noah")], jobs: [])
        XCTAssertEqual(ligacao(lista, .noah, .central)?.rotulo, "2 geradas pelo Noah")
        XCTAssertEqual(ligacao(lista, .claude, .central)?.estado, .parada)
    }

    func testRespostaRodandoVoltaAoAgente() {
        let lista = Fluxo.ligacoes(itens: [], jobs: [job("a", "rodando", fonte: "codex"), job("b", "concluido")])
        XCTAssertEqual(ligacao(lista, .aparelhos, .central)?.rotulo, "1 resposta enviada")
        XCTAssertEqual(ligacao(lista, .central, .codex)?.estado, .viva)
        XCTAssertEqual(ligacao(lista, .central, .claude)?.estado, .parada)
    }

    func testCerebroNuncaFingeAtividade() {
        let lista = Fluxo.ligacoes(itens: [p("a"), p("b", fonte: "noah")], jobs: [job("a", "rodando")])
        let cerebro = lista.filter { $0.de == .cerebro || $0.para == .cerebro }
        XCTAssertEqual(cerebro.count, 4)
        XCTAssertTrue(cerebro.allSatisfy { $0.estado == .semSinal && $0.rotulo.contains(Fluxo.semSinal) })
    }
}
